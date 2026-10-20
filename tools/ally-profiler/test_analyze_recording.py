"""Synthetic offline-analysis tests; no real capture or live-system access."""
import tempfile
from pathlib import Path
import unittest
import analyze_recording as a


class RecordingTests(unittest.TestCase):
    def parse(self, body):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.csv';p.write_text(body)
            return a.read_frames(p)

    def test_cadence_ns_ms_and_sum(self):
        r=self.parse('os,cpu\nTest,Test\nfps,frametime,elapsed\n100,10,10000000\n50,20,30000000\n')
        self.assertAlmostEqual(a.cadence(r)['residual_ms']['max'],0)
        self.assertAlmostEqual(a.frame_stats(r)['duration_fps'],2000/30)

    def test_reject_nonmonotonic_and_missing_elapsed(self):
        for s in ['frametime,elapsed\n10,100\n20,100\n','frametime\n10\n']:
            with self.assertRaises(ValueError):self.parse(s)

    def test_reject_bad_intervals_and_concatenation(self):
        for s in ['frametime,elapsed\n0,100\n','frametime,elapsed\nnan,100\n',
                  'frametime,elapsed\n10,100\nframetime,elapsed\n10,200\n']:
            with self.assertRaises(ValueError):self.parse(s)

    def test_strict_thresholds_and_percentiles(self):
        r=[dict(frametime=v) for v in [10,20,33.33,50,100]]
        x=a.frame_stats(r)
        self.assertEqual(x['over_33.33'],2)
        self.assertEqual(x['over_50'],1)
        self.assertEqual(x['over_100'],0)
        self.assertEqual(x['p50_ms'],33.33)

    def test_window_boundary_assignment(self):
        r=[dict(t=t,frametime=10) for t in [0.5,1,1.5,2,3]]
        x=a.windows(r,1)
        self.assertEqual([(d['start_s'],d['n']) for d in x],[(1,2),(2,1)])

    def test_runs_vs_gapped_clusters(self):
        r=[dict(t=t,frametime=f) for t,f in [(1,40),(1.04,40),(1.06,10),(1.5,40),(3,40)]]
        self.assertEqual(a.runs(r,33.33)[0]['n'],2)
        self.assertEqual(a.clusters(r,33.33)[0]['n'],3)

    def test_sensor_rejects_error_and_ambiguous_devices(self):
        s=dict(path='/s/freq1_input',unit='MHz',label=dict(value='sclk'),value=1000,error=None)
        d=dict(gpus=[dict(sensors=dict(clock=s))])
        self.assertEqual(a.sensor(d,'MHz','sclk','freq1_input'),1000)
        s['error']='permission denied'
        self.assertIsNone(a.sensor(d,'MHz','sclk','freq1_input'))
        s['error']=None;d['gpus']*=2
        self.assertIsNone(a.sensor(d,'MHz','sclk','freq1_input'))

    def test_thread_identity_and_switch_rates(self):
        rows=[]
        for time,tick,cpu in [(0,10,None),(2,20,25)]:
            rows.append(dict(t=time,threads=[dict(id=1,start_ticks=100,name='worker',state='S',
                cpu_percent_one_core=cpu,context_switches=dict(voluntary_ctxt_switches=tick))]))
        x=a.thread_stats(rows)[0]
        self.assertEqual(x['cpu']['mean'],25)
        self.assertEqual(x['voluntary_ctxt_switches_per_s'],5)
        rows[-1]['threads'][0]['start_ticks']=200
        self.assertEqual(len(a.thread_stats(rows)),2)

    def test_alignment_offset_controls_membership(self):
        frames=[dict(t=6,frametime=10),dict(t=120,frametime=10)]
        samples=[dict(t=8,**{k:1 for k in ['cpu','sclk','temp','slowPPT_average','slowPPT_input']})]
        self.assertEqual(len(a.aligned_bins(frames,samples,2)),1)
        self.assertEqual(len(a.aligned_bins(frames,samples,20)),0)

    def test_correlation_missing_and_constant(self):
        self.assertIsNone(a.pearson([1,1,1],[2,3,4]))
        self.assertEqual(a.pearson([1,2,None,3],[2,4,50,6]),1)


if __name__=='__main__':unittest.main()
