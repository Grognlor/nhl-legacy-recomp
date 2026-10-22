"""Synthetic proc fixtures only; never identify, sample or signal NHL."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import thread_wait_sampler as sampler
from test_ally_profiler import fake_stat


class FakeClock:
    def __init__(self, callback=None):
        self.ns = 1000000000
        self.callback = callback

    def monotonic_ns(self):
        return self.ns

    def utc(self):
        return '2026-10-22T16:00:00.000000+00:00'

    def sleep(self, seconds):
        self.ns += round(seconds * 1e9)
        if self.callback:
            self.callback()


class WaitSamplerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc_root = self.root / 'proc'
        self.proc = sampler.Proc(self.proc_root)
        self.put('23/stat', fake_stat(23, 100, start=10, name='nhllegacy.exe'))
        self.thread(24, 'XThread0204 (F8', 30, 20)
        self.thread(25, 'GPU Commands (F', 40, 21)
        self.thread(26, 'GPU Commands (F', 0, 22)
        self.put('sys/kernel/random/boot_id', 'synthetic-boot')

    def put(self, name, text):
        p = self.proc_root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def thread(self, tid, name, ticks, start, state='S'):
        self.put(f'23/task/{tid}/stat', fake_stat(tid, ticks, start=start, name=name).replace(') S ', f') {state} '))
        self.put(f'23/task/{tid}/wchan', 'futex_wait_queue')
        self.put(f'23/task/{tid}/status', 'voluntary_ctxt_switches: 100\nnonvoluntary_ctxt_switches: 5\n')

    def collect(self, **kwargs):
        opts = dict(pid=23, process_start=10, guest=(24, 20), gpu=(25, 21),
                    duration=.6, interval=.2, confirmed=True, proc=self.proc,
                    clock=FakeClock(), base=self.root / 'runs')
        opts.update(kwargs)
        run, footer = sampler.collect(**opts)
        records = [json.loads(line) for line in (run / 'thread-waits.jsonl').read_text().splitlines()]
        return run, footer, records

    def test_snapshot_identity_counters_and_wchan(self):
        row = self.proc.snapshot(23, 24, 20)
        self.assertEqual(row['ticks'], 30)
        self.assertEqual(row['context_switches']['voluntary_ctxt_switches'], 100)
        self.assertEqual(row['wchan']['value'], 'futex_wait_queue')
        self.assertEqual(row['name'], 'XThread0204 (F8')
        self.assertEqual(row['state'], 'S')

    def test_explicit_confirmation_and_role_required(self):
        for kwargs in [dict(confirmed=False), dict(gpu=(24, 20)), dict(guest=(25, 21), gpu=(24, 20))]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.collect(**kwargs)
        self.assertFalse((self.root / 'runs').exists())

    def test_wrong_process_or_thread_identity_rejected_before_output(self):
        for kwargs in [dict(process_start=999), dict(guest=(24, 999)), dict(gpu=(100, 20))]:
            with self.subTest(kwargs=kwargs), self.assertRaises(sampler.IdentityError):
                self.collect(**kwargs)
        self.assertFalse((self.root / 'runs').exists())

    def test_stat_numeric_identity_validated(self):
        self.put('23/task/24/stat', fake_stat(999, 30, start=20))
        with self.assertRaises(sampler.IdentityError):
            self.proc.snapshot(23, 24, 20)

    def test_multiple_gpu_names_and_cpu_activity_selection(self):
        def activity():
            for tid, delta in [(24, 18), (25, 6), (26, 0)]:
                t = self.proc.stat(23, tid)
                self.put(f'23/task/{tid}/stat', fake_stat(tid, t['ticks'] + delta,
                         start=t['start_ticks'], name=t['name']))
        result = sampler.discover(23, .6, .2, self.proc, FakeClock(activity))
        self.assertFalse(result['ambiguous'])
        self.assertEqual(result['selected']['gpu']['tid'], 25)
        self.assertEqual(result['selected']['guest']['tid'], 24)
        self.assertEqual(len(result['candidates']), 3)
        self.assertGreater(result['selected']['guest']['cpu_percent_one_core'], 0)

    def test_no_activity_and_near_ties_are_ambiguous(self):
        result = sampler.discover(23, .2, .2, self.proc, FakeClock())
        self.assertTrue(result['ambiguous'])
        self.assertIsNone(result['selected']['gpu'])
        self.assertIsNone(sampler.pick([{'tid': 25, 'delta_ticks': 20}, {'tid': 26, 'delta_ticks': 19}]))
        self.assertIsNone(sampler.pick([]))

    def test_discovery_cli_ambiguous_exit(self):
        with patch.object(sampler, 'discover', return_value={'ambiguous': True}), \
             patch('sys.argv', ['sampler', 'discover', '--pid', '23']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sampler.main(), 2)

    def test_discovery_stops_on_pid_reuse(self):
        clock = FakeClock(lambda: self.put('23/stat', fake_stat(23, 0, start=99)))
        with self.assertRaises(sampler.IdentityError):
            sampler.discover(23, .2, .2, self.proc, clock)

    def test_discovery_stops_on_candidate_change_or_reuse(self):
        for reuse in [False, True]:
            def change():
                if reuse:
                    self.put('23/task/24/stat', fake_stat(24, 99, start=999, name='XThread0204 (F8'))
                else:
                    self.thread(27, 'XThread0300', 0, 50)
            with self.subTest(reuse=reuse), self.assertRaises(sampler.IdentityError):
                sampler.discover(23, .2, .2, self.proc, FakeClock(change))
            for p in (self.proc_root / '23/task/27').glob('*'):
                p.unlink()
            if (self.proc_root / '23/task/27').exists():
                (self.proc_root / '23/task/27').rmdir()
            self.thread(24, 'XThread0204 (F8', 30, 20)

    def test_hidden_missing_and_restricted_wait_channels(self):
        path = self.proc_root / '23/task/24/wchan'
        for value in ['0', '', '-', '1234', 'ffffffff1234', '0xffff1234']:
            with self.subTest(value=value):
                path.write_text(value)
                row = self.proc.snapshot(23, 24, 20)
                self.assertIsNone(row['wchan']['value'])
                self.assertEqual(row['wchan']['status'], 'unavailable_or_not_exposed')
        path.unlink()
        self.assertEqual(self.proc.snapshot(23, 24, 20)['wchan']['status'], 'unavailable')
        original = self.proc.text
        def restricted(p, limit=65536):
            if p.name == 'wchan':
                raise PermissionError('synthetic denial')
            return original(p, limit)
        with patch.object(self.proc, 'text', side_effect=restricted):
            row = self.proc.snapshot(23, 24, 20)
            self.assertEqual(row['wchan']['status'], 'restricted')
            self.assertEqual(row['wchan']['error'], 'PermissionError')

    def test_status_missing_invalid_and_partial_fields(self):
        path = self.proc_root / '23/task/24/status'
        for text in ['', 'voluntary_ctxt_switches: nope', 'voluntary_ctxt_switches: -1']:
            path.write_text(text)
            row = self.proc.snapshot(23, 24, 20)
            self.assertIsNotNone(row['status_error'])
        path.unlink()
        self.assertIsNotNone(self.proc.snapshot(23, 24, 20)['status_error'])

    def test_thread_reuse_during_snapshot_discarded(self):
        original = self.proc.text
        def replace_after_status(p, limit=65536):
            value = original(p, limit)
            if p.name == 'status':
                self.put('23/task/24/stat', fake_stat(24, 1, start=999))
            return value
        with patch.object(self.proc, 'text', side_effect=replace_after_status), self.assertRaises(sampler.IdentityError):
            self.proc.snapshot(23, 24, 20)

    def test_pid_reuse_thread_reuse_and_disappearance_stop_collection(self):
        changes = [lambda: self.put('23/stat', fake_stat(23, 1, start=999)),
                   lambda: self.put('23/task/24/stat', fake_stat(24, 1, start=999)),
                   lambda: (self.proc_root / '23/task/24/stat').unlink()]
        for change in changes:
            self.put('23/stat', fake_stat(23, 100, start=10))
            self.thread(24, 'XThread0204 (F8', 30, 20)
            with self.subTest(change=change):
                _, footer, records = self.collect(clock=FakeClock(change))
                self.assertEqual(footer['reason'], 'target_or_read_error')
                self.assertEqual(footer['samples'], 1)
                self.assertEqual(len(records), 2)

    def test_process_termination_and_zombie(self):
        def terminate():
            (self.proc_root / '23/stat').unlink()
        _, footer, _ = self.collect(clock=FakeClock(terminate))
        self.assertEqual(footer['reason'], 'target_or_read_error')
        self.put('23/stat', fake_stat(23, 1, start=10).replace(') S ', ') Z '))
        with self.assertRaises(sampler.IdentityError):
            self.collect()

    def test_process_reuse_during_sample_rejects_entire_record(self):
        original = self.proc.snapshot
        def change(*args):
            row = original(*args)
            self.put('23/stat', fake_stat(23, 1, start=999))
            return row
        with patch.object(self.proc, 'snapshot', side_effect=change):
            _, footer, records = self.collect()
        self.assertEqual(footer['samples'], 0)
        self.assertEqual([r['kind'] for r in records], ['end'])

    def test_duration_timestamps_jsonl_and_no_continuous_output(self):
        clock = FakeClock()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            run, footer, records = self.collect(clock=clock)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(footer['samples'], 3)
        self.assertEqual(footer['reason'], 'duration')
        self.assertEqual(clock.ns, 1600000000)
        self.assertEqual(records[0]['monotonic_ns'], 1000000000)
        self.assertTrue(records[0]['utc'].endswith('+00:00'))
        self.assertEqual(records[0]['threads'][0]['tid'], 24)
        meta = json.loads((run / 'metadata.json').read_text())
        self.assertEqual(meta['boot_id']['value'], 'synthetic-boot')
        self.assertIn('monotonic', meta['clock'])

    def test_ctrl_c_flush_and_close(self):
        def interrupt():
            raise KeyboardInterrupt()
        run, footer, records = self.collect(clock=FakeClock(interrupt))
        self.assertEqual(footer['reason'], 'interrupted')
        self.assertEqual(footer['samples'], 1)
        self.assertEqual(records[-1]['kind'], 'end')
        with (run / 'thread-waits.jsonl').open('ab'):
            pass

    def test_output_and_sample_bounds(self):
        run, footer, records = self.collect(byte_limit=sampler.MAX_LINE + 700)
        self.assertEqual(footer['reason'], 'output_limit')
        self.assertEqual(records[-1]['kind'], 'end')
        self.assertLessEqual((run / 'thread-waits.jsonl').stat().st_size, sampler.MAX_LINE + 700)
        with patch.object(sampler, 'MAX_SAMPLES', 1):
            _, footer, _ = self.collect()
        self.assertEqual(footer['reason'], 'sample_limit')
        stream = io.BytesIO()
        writer = sampler.BoundedWriter(stream)
        self.assertFalse(writer.write({'oversized': 'x' * sampler.MAX_LINE}))
        self.assertEqual(stream.getvalue(), b'')

    def test_no_catch_up_burst(self):
        clock = FakeClock()
        original = self.proc.snapshot
        def slow(*args):
            clock.ns += 150000000
            return original(*args)
        with patch.object(self.proc, 'snapshot', side_effect=slow):
            _, footer, records = self.collect(clock=clock, duration=1)
        samples = [x for x in records if x['kind'] == 'sample']
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[1]['monotonic_ns'] - samples[0]['monotonic_ns'], 500000000)

    def test_read_and_thread_bounds(self):
        p = self.put('oversized', 'x' * 300)
        with self.assertRaises(ValueError):
            self.proc.text(p, 256)
        with patch.object(sampler, 'MAX_THREADS', 2), self.assertRaises(ValueError):
            sampler.discover(23, .2, .2, self.proc, FakeClock())

    def test_limits_identity_arguments(self):
        for kwargs in [dict(duration=float('nan')), dict(interval=float('inf')),
                       dict(interval=.01), dict(duration=601), dict(pid=-1)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.collect(**kwargs)
        self.assertEqual(sampler.identity('24:20'), (24, 20))
        for text in ['24', '0:20', '24:-1', 'a:b', '1:2:3']:
            with self.assertRaises(sampler.argparse.ArgumentTypeError):
                sampler.identity(text)

    def test_cpu_counter_decrease_stops(self):
        def reset():
            self.put('23/task/24/stat', fake_stat(24, 0, start=20, name='XThread0204 (F8'))
        _, footer, _ = self.collect(clock=FakeClock(reset))
        self.assertEqual(footer['reason'], 'target_or_read_error')
        self.assertIn('counter decreased', footer['detail'])

    def test_missing_boot_id_is_explicit(self):
        (self.proc_root / 'sys/kernel/random/boot_id').unlink()
        self.assertIsNone(self.proc.boot()['value'])
        self.assertIsNotNone(self.proc.boot()['error'])

    def test_real_timestamp_format_and_unknown_read_errors(self):
        from datetime import datetime
        event = sampler.stamp(sampler.Clock())
        self.assertIsNotNone(datetime.fromisoformat(event['utc']).utcoffset())
        self.assertGreater(event['monotonic_ns'], 0)
        self.put('23/task/24/wchan', 'x' * 300)
        self.assertEqual(self.proc.snapshot(23, 24, 20)['wchan']['error'], 'ValueError')

    def test_no_target_writes_signals_or_attach(self):
        before = {p.relative_to(self.proc_root): hashlib.sha256(p.read_bytes()).digest()
                  for p in self.proc_root.rglob('*') if p.is_file()}
        with patch('os.kill', side_effect=AssertionError('must not signal')):
            self.collect()
        after = {p.relative_to(self.proc_root): hashlib.sha256(p.read_bytes()).digest()
                 for p in self.proc_root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertNotIn('subprocess', sampler.__dict__)


if __name__ == '__main__':
    unittest.main()
