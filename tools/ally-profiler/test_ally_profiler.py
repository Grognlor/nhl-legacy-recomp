"""Synthetic-only tests: temporary fake sysfs/proc trees, no game access."""
import errno
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ally_profiler as profiler


def fake_stat(pid, ticks, start=100, name='GPU (Commands)'):
    fields = ['S'] + ['0'] * 49
    fields[11], fields[12], fields[19] = str(ticks), '0', str(start)
    return f'{pid} ({name}) ' + ' '.join(fields)


class ProfilerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)
        return target

    def analyze(self, text, **kwargs):
        path = self.put('input.csv', text)
        return profiler.analyze_csv(path, 'synthetic', **kwargs)

    def test_statistics_known_distribution(self):
        result = self.analyze('frametime_ms\n10\n20\n30\n40\n', per_frame=True)
        self.assertEqual(result['fps_from_frame_durations'], 40)
        self.assertEqual(result['sample_frametime_percentiles_ms'],
                         {'p50': 25, 'p90': 37, 'p95': 38.5, 'p99': 39.7})
        self.assertEqual(result['thresholds']['33.33'], {'count': 1, 'fraction': .25})

    def test_mangohud_preamble_bom_crlf_and_units(self):
        result = self.analyze('\ufeffv1\r\n0.8.4\r\nos,cpu\r\nLinux,"test,cpu"\r\n'
                              'fps,frametime,elapsed\r\n100,10000,10000000\r\n50,20000,30000000\r\n',
                              per_frame=True, unit='us')
        self.assertAlmostEqual(result['fps_from_frame_durations'], 2000 / 30)
        self.assertEqual(result['source'], 'synthetic')

    def test_ambiguous_units_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.analyze('fps,frametime\n60,16.6\n')

    def test_unknown_sampling_does_not_claim_fps(self):
        result = self.analyze('frametime_ms\n16\n17\n')
        self.assertIsNone(result['fps_from_frame_durations'])
        self.assertTrue(result['warnings'])

    def test_invalid_rows_reported_and_fps_suppressed(self):
        result = self.analyze('fps,frametime_ms\n60,16\n60,nan\n60,inf\n60,0\n60,-1\n60,no\n60\n',
                              per_frame=True)
        self.assertEqual(len(result['invalid_rows']), 6)
        self.assertEqual(result['rows_selected_valid'], 1)
        self.assertIsNone(result['fps_from_frame_durations'])
        json.dumps(result, allow_nan=False)

    def test_empty_summary_and_fps_only_rejected(self):
        for text in ('', 'Average FPS,Average Frame Time\n60,16\n', 'fps\n60\n', 'frametime_ms\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.analyze(text)

    def test_duplicate_and_concatenated_headers_rejected(self):
        for text in ('frametime_ms,frametime_ms\n10,10\n',
                     'frametime_ms\n10\nframetime_ms\n20\n'):
            with self.assertRaises(ValueError):
                self.analyze(text)

    def test_single_frame_row_selection_and_seconds(self):
        result = self.analyze('frametime\n.01\n.02\n.03\n', unit='s',
                              per_frame=True, skip=1, take=1)
        self.assertEqual(result['fps_from_frame_durations'], 50)
        self.assertEqual(result['sample_frametime_percentiles_ms']['p99'], 20)

    def test_missing_sensors_and_permission_denied(self):
        result = profiler.gpu_sample(self.root / 'absent')
        self.assertIsNone(result['sensors']['utilization']['value'])
        self.assertTrue(result['errors'])
        with patch.object(Path, 'read_text', side_effect=PermissionError(errno.EACCES, 'denied')):
            value = profiler.reading(self.root / 'denied')
            self.assertIsNone(value['value'])
            self.assertIn('PermissionError', value['error'])

    def test_gpu_units_labels_and_dpm(self):
        device = self.root / 'gpu'
        self.put('gpu/gpu_busy_percent', '37')
        self.put('gpu/hwmon/hwmon9/temp1_input', '42000')
        self.put('gpu/hwmon/hwmon9/temp1_label', 'edge')
        self.put('gpu/hwmon/hwmon9/power1_average', '12500000')
        self.put('gpu/hwmon/hwmon9/power1_label', 'slowPPT')
        self.put('gpu/hwmon/hwmon9/freq1_input', '800000000')
        self.put('gpu/pp_dpm_sclk', '0: 400Mhz\n1: 0.8Ghz *\n')
        self.put('gpu/pp_dpm_mclk', 'unknown')
        result = profiler.gpu_sample(device)['sensors']
        self.assertEqual(result['hwmon9/temp1_input']['value'], 42)
        self.assertEqual(result['hwmon9/power1_average']['value'], 12.5)
        self.assertEqual(result['hwmon9/power1_average']['label']['value'], 'slowPPT')
        self.assertEqual(result['hwmon9/freq1_input']['value'], 800)
        self.assertEqual(result['dpm_sclk']['value'], 800)
        self.assertIsNone(result['dpm_mclk']['value'])
        self.assertIsNotNone(result['hwmon9/freq1_input']['label']['error'])

    def test_discovery_zero_and_multiple(self):
        devices, errors = profiler.discover(self.root)
        self.assertFalse(devices)
        self.assertTrue(errors)
        for number in (1, 2):
            device = self.root / f'card{number}/device'
            device.mkdir(parents=True)
            (self.root / f'amdgpu-{number}/amdgpu').mkdir(parents=True)
            (device / 'driver').symlink_to(self.root / f'amdgpu-{number}/amdgpu')
        self.assertEqual(len(profiler.discover(self.root)[0]), 2)

    def test_process_thread_rates_first_sample_and_reuse(self):
        self.put('123/stat', fake_stat(123, 10))
        self.put('123/status', 'voluntary_ctxt_switches:\t7\n')
        self.put('123/task/124/stat', fake_stat(124, 5))
        self.put('123/task/124/status', 'nonvoluntary_ctxt_switches:\t2\n')
        sampler = profiler.ProcSampler(self.root, hz=100)
        first = sampler.sample(123, 1)
        self.assertIsNone(first['process']['cpu_percent_one_core'])
        self.put('123/stat', fake_stat(123, 110))
        self.put('123/task/124/stat', fake_stat(124, 55))
        second = sampler.sample(123, 2)
        self.assertEqual(second['process']['cpu_percent_one_core'], 100)
        self.assertEqual(second['threads'][0]['cpu_percent_one_core'], 50)
        self.assertEqual(second['threads'][0]['name'], 'GPU (Commands)')
        self.assertEqual(second['threads'][0]['context_switches']['nonvoluntary_ctxt_switches'], 2)
        self.put('123/stat', fake_stat(123, 1000, start=200))
        self.assertIn('PID reused', sampler.sample(123, 3)['errors'][0])

    def test_thread_churn_and_missing_process(self):
        self.put('123/stat', fake_stat(123, 10))
        self.put('123/status', '')
        self.put('123/task/124/stat', 'truncated')
        sampler = profiler.ProcSampler(self.root, hz=100)
        result = sampler.sample(123, 1)
        self.assertTrue(result['errors'])
        self.assertFalse(result['threads'])
        self.assertIsNone(sampler.sample(999, 1)['process'])

    def test_output_is_unique_and_rejects_symlink(self):
        base = self.root / 'logs'
        a, b = profiler.new_run(base), profiler.new_run(base)
        self.assertNotEqual(a, b)
        link = self.root / 'link'
        link.symlink_to(base)
        with self.assertRaises(ValueError):
            profiler.new_run(link)
        profiler.write_json(a / 'summary.json', {'synthetic': True})
        with self.assertRaises(FileExistsError):
            profiler.write_json(a / 'summary.json', {})

    def test_collector_writes_schema_without_live_reads(self):
        args = SimpleNamespace(session='desktop', pid=[123], duration=.01, interval=.5)
        with patch.object(profiler, 'default_output_base', return_value=self.root / 'runs'), \
             patch.object(profiler, 'discover', return_value=([], ['synthetic missing GPU'])), \
             patch.object(profiler.ProcSampler, 'sample', return_value={'pid': 123, 'process': None,
                                                                       'errors': ['synthetic missing PID']}):
            run = profiler.collect(args)
        metadata = json.loads((run / 'metadata.json').read_text())
        samples = [json.loads(x) for x in (run / 'telemetry.jsonl').read_text().splitlines()]
        self.assertEqual(metadata['discovery_errors'], ['synthetic missing GPU'])
        self.assertTrue(samples)
        self.assertGreater(samples[0]['monotonic_ns'], 0)
        self.assertIn('utc', samples[0])
        self.assertEqual(samples[0]['processes'][0]['errors'], ['synthetic missing PID'])

    def test_nonfinite_sensor_and_thread_identity_change(self):
        path = self.put('sensor', 'nan')
        self.assertIsNone(profiler.reading(path)['value'])
        self.put('123/stat', fake_stat(123, 10))
        self.put('123/status', '')
        self.put('123/task/124/stat', fake_stat(124, 5))
        self.put('123/task/124/status', '')
        sampler = profiler.ProcSampler(self.root, hz=100)
        sampler.sample(123, 1)
        self.put('123/task/124/stat', fake_stat(124, 100, start=101))
        self.assertIsNone(sampler.sample(123, 2)['threads'][0]['cpu_percent_one_core'])

    def bazzite_home(self):
        canonical = self.root / 'var/home/cody'
        canonical.mkdir(parents=True)
        (self.root / 'home').symlink_to('var/home', target_is_directory=True)
        return self.root / 'home/cody', canonical

    def test_bazzite_home_alias_creates_unique_canonical_runs(self):
        alias, canonical = self.bazzite_home()
        with patch.object(Path, 'home', return_value=alias):
            self.assertEqual(profiler.default_output_base(), canonical / 'nhl-ally-profiles')
            first, second = profiler.new_run(), profiler.new_run()
        self.assertEqual(first.parent, canonical / 'nhl-ally-profiles')
        self.assertEqual(second.parent, first.parent)
        self.assertNotEqual(first, second)
        profiler.write_json(first / 'metadata.json', {'synthetic': True})
        with self.assertRaises(FileExistsError):
            profiler.write_json(first / 'metadata.json', {})

    def test_bazzite_home_rejects_output_symlink_and_dangling_link(self):
        alias, canonical = self.bazzite_home()
        outside = self.root / 'unintended'
        outside.mkdir()
        base = canonical / 'nhl-ally-profiles'
        for target in (outside, self.root / 'nonexistent'):
            with self.subTest(target=target):
                base.symlink_to(target, target_is_directory=True)
                with patch.object(Path, 'home', return_value=alias), self.assertRaises(ValueError):
                    profiler.new_run()
                base.unlink()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.root / 'nonexistent').exists())

    def test_rejects_symlink_below_output_base_and_traversal(self):
        base = self.root / 'nhl-ally-profiles'
        base.mkdir()
        outside = self.root / 'unintended'
        outside.mkdir()
        (base / 'redirect').symlink_to(outside, target_is_directory=True)
        for path in (base / 'redirect/child', base / '../unintended', Path('relative')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                profiler.new_run(path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_home_roots_fail_before_output_creation(self):
        plain_file = self.put('not-a-directory', 'synthetic')
        for home in (Path('/'), Path('relative'), self.root / '../escape',
                     self.root / 'missing', plain_file):
            with self.subTest(home=home), patch.object(Path, 'home', return_value=home), \
                 self.assertRaises((ValueError, OSError)):
                profiler.new_run()


if __name__ == '__main__':
    unittest.main()
