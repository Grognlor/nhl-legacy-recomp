"""Offline synthetic tests; no proc, game, controller or sensor access."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import analyze_wait_capture as analysis


def row(ns, ticks=0, kind='wait'):
    stamp = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=ns / 1e9)).isoformat()
    threads = [{'tid': tid, 'id': tid, 'start_ticks': start, 'name': name, 'state': 'S',
                'ticks': ticks, 'context_switches': {'voluntary_ctxt_switches': ticks,
                                                  'nonvoluntary_ctxt_switches': ticks},
                'wchan': {'raw': '0', 'status': 'unavailable_or_not_exposed', 'value': None}}
               for tid, start, name in [(2, 20, 'XThread0204'), (3, 30, 'GPU Commands')]]
    result = {'monotonic_ns': ns, 'utc': stamp, 'collection_seconds': .001}
    if kind == 'wait':
        result.update(kind='sample', threads=threads, read_end_monotonic_ns=ns + 1000000)
    else:
        result.update(elapsed_seconds=ns / 1e9, processes=[{'pid': 1, 'errors': [],
                      'process': {'start_ticks': 10, 'ticks': ticks * 2}, 'threads': threads}],
                      gpus=[{'sensors': {'utilization': {'value': 9999, 'unit': '%'}}}])
    return result


class AnalysisTests(unittest.TestCase):
    def test_filters_old_boot_markers_by_utc_before_monotonic(self):
        rows = [row(1000000000), row(2000000000)]
        good = {k: rows[0][k] for k in ('monotonic_ns', 'utc')}
        good['event'] = 'FREEZE_RIGHT'
        old = dict(good, utc='2025-12-30T00:00:01+00:00')  # Same uptime, another boot/date.
        outside = dict(good, monotonic_ns=3000000000, utc=row(3000000000)['utc'])
        self.assertEqual(analysis.markers_in([old, good, outside], rows), [good])

    def test_inconsistent_marker_clock_rejected(self):
        rows = [row(1000000000), row(2000000000)]
        marker = dict(row(1000000000), monotonic_ns=1900000000, event='FREEZE_RIGHT')
        with self.assertRaisesRegex(ValueError, 'offset'):
            analysis.markers_in([marker], rows)

    def test_clocks_and_order_validate(self):
        rows = [row(1000000000), row(1200000000)]
        self.assertAlmostEqual(analysis.times(rows)['span_seconds'], .2)
        for bad in [[rows[0], rows[0]], [dict(rows[0], utc='2026-01-01T00:00:01'), rows[1]]]:
            with self.assertRaises(ValueError):
                analysis.times(bad)

    def test_tick_delta_rate_and_unknown_wait_not_zero(self):
        rows = [row(1000000000), row(1200000000, ticks=19)]
        rates = analysis.intervals(rows, 'wait', {2: 20, 3: 30}, 100)
        result = analysis.group(rates, 'wait', [2, 3])
        self.assertAlmostEqual(result['threads'][2]['cpu']['mean'], 95)
        self.assertEqual(result['threads'][2]['wchan_raw_counts'], {'0': 1})
        self.assertEqual(result['threads'][2]['wchan_status_counts'], {'unavailable_or_not_exposed': 1})

    def test_counter_regression_and_identity_reuse_rejected(self):
        rows = [row(1000000000, ticks=19), row(1200000000, ticks=0)]
        with self.assertRaisesRegex(ValueError, 'regression'):
            analysis.intervals(rows, 'wait', {2: 20, 3: 30}, 100)
        rows[1]['threads'][0]['start_ticks'] = 999
        with self.assertRaisesRegex(ValueError, 'identity'):
            analysis.intervals(rows, 'wait', {2: 20, 3: 30}, 100)

    def test_duplicate_tid_rejected(self):
        r = row(1)
        r['threads'].append(deepcopy(r['threads'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            analysis.thread_map(r, 'wait')

    def test_neighborhood_union_deduplicates_and_no_markers_has_no_fake_events(self):
        rows = [row(i * 200000000, ticks=i * 10) for i in range(1, 20)]
        rates = analysis.intervals(rows, 'wait', {2: 20, 3: 30}, 100)
        markers = [dict(row(n), event='FREEZE_RIGHT') for n in [1800000000, 2000000000]]
        result = analysis.event_analysis(rates, 'wait', [2, 3], markers, rows[0]['monotonic_ns'])
        self.assertLess(result['near']['n'], sum(e['near']['n'] for e in result['events']))
        empty = analysis.event_analysis(rates, 'wait', [2, 3], [], rows[0]['monotonic_ns'])
        self.assertEqual(empty['near']['n'], 0)
        self.assertEqual(empty['unmarked']['n'], len(rates))

    def make_inputs(self, root):
        wd, td = root / 'wait', root / 'cpu'
        wd.mkdir(); td.mkdir()
        wm = {'schema': 1, 'tool': 'thread_wait_sampler', 'pid': 1, 'process_start_ticks': 10, 'guest': [2, 20], 'gpu': [3, 30],
              'names': {'2': 'XThread0204', '3': 'GPU Commands'}, 'clock_ticks_per_second': 100}
        tm = {'schema': 1, 'pids': [1], 'clock_ticks_per_second': 100}
        waits = [row(1000000000), row(1200000000, ticks=10)]
        footer = dict(row(1200000001), kind='end', samples=2, detail=None, reason='duration',
                      unavailable_wchan_observations=4)
        tele = [row(10000000000, kind='telemetry'), row(10500000000, ticks=20, kind='telemetry')]
        for t in tele[0]['processes'][0]['threads']:
            t['cpu_percent_one_core'] = None
        for t in tele[1]['processes'][0]['threads']:
            t['cpu_percent_one_core'] = 40.
        for p, obj, lines in [(wd/'metadata.json', wm, False), (td/'metadata.json', tm, False),
                               (wd/'thread-waits.jsonl', waits+[footer], True),
                               (td/'telemetry.jsonl', tele, True), (root/'markers.jsonl', [], True)]:
            p.write_text(''.join(json.dumps(x)+'\n' for x in obj) if lines else json.dumps(obj))
        return wd, td, root/'markers.jsonl'

    def test_end_to_end_separate_recordings_and_input_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = self.make_inputs(root)
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = analysis.analyze(*args)
            self.assertEqual(result['overlap_seconds'], 0)
            self.assertAlmostEqual(result['separation_seconds'], 8.8)
            self.assertNotIn('utilization', result['telemetry']['all']['sensors'])
            self.assertEqual(before, {p:p.read_bytes() for p in before})
            json.dumps(result, allow_nan=False)

    def test_footer_count_mismatch_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.make_inputs(Path(temp))
            path = args[0]/'thread-waits.jsonl'
            records = analysis.load(path, True)
            records[-1]['samples'] = 3
            path.write_text(''.join(json.dumps(x)+'\n' for x in records))
            with self.assertRaisesRegex(ValueError, 'Footer'):
                analysis.analyze(*args)
            path.write_text(json.dumps(records[0])+'\n')
            with self.assertRaisesRegex(ValueError, 'end record'):
                analysis.analyze(*args)

    def test_process_identity_and_multi_gpu_disagreement_rejected(self):
        for field in ('pid', 'gpus'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                args = self.make_inputs(Path(temp))
                p = args[1]/'telemetry.jsonl'
                rows = analysis.load(p, True)
                if field == 'pid':
                    rows[0]['processes'][0]['pid'] = 999
                else:
                    rows[0]['gpus'].append(deepcopy(rows[0]['gpus'][0]))
                p.write_text(''.join(json.dumps(x)+'\n' for x in rows))
                with self.assertRaises(ValueError):
                    analysis.analyze(*args)

    def test_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)/'bad.json'
            p.write_text('{"x":NaN}')
            with self.assertRaises(ValueError):
                analysis.load(p)


if __name__ == '__main__':
    unittest.main()
