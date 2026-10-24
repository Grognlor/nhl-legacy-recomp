"""Synthetic timed sessions plus optional read-only regression of local recordings."""
import contextlib
from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import ally_profiler as cpu
import live_profiler as live
import thread_wait_sampler as waits
from test_ally_profiler import fake_stat


class Clock:
    def __init__(self, callback=None):
        self.ns=1000000000
        self.callback=callback

    def monotonic_ns(self):
        return self.ns

    def utc(self):
        return (datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=self.ns/1e9)).isoformat()

    def sleep(self,seconds):
        self.ns+=round(seconds*1e9)
        if self.callback:
            self.callback(seconds)


class NoMarkers:
    status='Synthetic marker source'
    def poll(self,clock):
        return []
    def close(self):
        pass


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.proc_root=self.root/'proc'
        self.proc=waits.Proc(self.proc_root)
        self.put('23/stat',fake_stat(23,100,start=10,name='nhllegacy.exe'))
        for tid,name,start in [(24,'XThread0204 (F8',20),(25,'GPU Commands (F',21),(26,'GPU Commands (F',22)]:
            self.put(f'23/task/{tid}/stat',fake_stat(tid,0,start=start,name=name))
            self.put(f'23/task/{tid}/status','voluntary_ctxt_switches: 10\nnonvoluntary_ctxt_switches: 2')
            self.put(f'23/task/{tid}/wchan','drm_syncobj_array_wait_timeout' if tid==25 else '0')
        self.clock=Clock(self.activity)

    def put(self,path,text):
        p=self.proc_root/path
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(text)
        return p

    def activity(self,seconds):
        for tid,rate in [(24,90),(25,30),(26,0)]:
            p=self.proc_root/f'23/task/{tid}/stat'
            if not p.exists():
                continue
            t=self.proc.stat(23,tid)
            p.write_text(fake_stat(tid,t['ticks']+round(seconds*rate),start=t['start_ticks'],name=t['name']))
        p=self.proc_root/'23/stat'
        if p.exists():
            t=self.proc.stat(23)
            p.write_text(fake_stat(23,t['ticks']+round(seconds*200),start=t['start_ticks'],name=t['name']))

    def capture(self,**kwargs):
        opts=dict(duration=3,proc=self.proc,clock=self.clock,base=self.root/'runs',
                  cpu_factory=lambda:cpu.ProcSampler(self.proc_root,hz=100,thread_limit=512),
                  sensors=([],['Synthetic missing GPU']),marker_factory=NoMarkers)
        opts.update(kwargs)
        with contextlib.redirect_stdout(io.StringIO()):
            return live.capture(**opts)

    def test_automatic_process_discovery_zero_multiple_and_zombie(self):
        self.assertEqual(live.find_process(self.proc)[0],(23,10))
        self.put('27/stat',fake_stat(27,0,start=55,name='nhllegacy.exe'))
        with self.assertRaisesRegex(ValueError,'found 2'):
            live.find_process(self.proc)
        self.put('23/stat',fake_stat(23,0,start=10,name='unrelated'))
        self.put('27/stat',fake_stat(27,0,start=55,name='nhllegacy.exe').replace(') S ',') Z '))
        with self.assertRaisesRegex(ValueError,'found 0'):
            live.find_process(self.proc)

    def test_rejects_ambiguous_threads_before_output(self):
        self.clock.callback=None
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            self.capture()
        self.assertFalse((self.root/'runs').exists())

    def test_process_set_changes_during_discovery(self):
        original=waits.discover
        def changed(*args,**kwargs):
            result=original(*args,**kwargs)
            self.put('29/stat',fake_stat(29,0,start=1,name='nhllegacy.exe'))
            return result
        with patch.object(waits,'discover',side_effect=changed),self.assertRaises(ValueError):
            self.capture()

    def test_shared_timer_overlap_identity_and_reports(self):
        run,a=self.capture()
        self.assertEqual(a['reason'],'duration')
        self.assertTrue(a['coverage_ok'])
        self.assertAlmostEqual(a['overlap_seconds'],2.5)
        self.assertEqual(a['streams']['telemetry']['samples'],6)
        self.assertEqual(a['streams']['wait']['samples'],15)
        self.assertEqual(self.clock.ns,6000000000)  # 2s discovery +3s collection after 1s initial uptime.
        self.assertTrue((run/'report.md').exists())
        self.assertTrue((run/'analysis.json').exists())
        self.assertIn('No frame-time/FPS',(run/'report.md').read_text())
        self.assertEqual(a['streams']['telemetry']['sensors'],{})
        self.assertEqual(a['guest_tid'],24)
        self.assertEqual(a['gpu_tid'],25)

    def test_read_delay_reduces_measured_overlap(self):
        sampler=cpu.ProcSampler(self.proc_root,hz=100,thread_limit=512)
        original=sampler.sample
        def slow(pid,now):
            result=original(pid,now)
            self.clock.ns+=50000000
            return result
        with patch.object(sampler,'sample',side_effect=slow):
            _,a=self.capture(cpu_factory=lambda:sampler)
        self.assertAlmostEqual(a['overlap_seconds'],2.45)
        self.assertEqual(a['streams']['wait']['first_ns']-a['streams']['telemetry']['first_ns'],50000000)

    def test_custom_300_second_timer(self):
        _,a=self.capture(duration=300)
        self.assertEqual(a['streams']['telemetry']['samples'],600)
        self.assertEqual(a['streams']['wait']['samples'],1500)
        self.assertAlmostEqual(a['overlap_seconds'],299.5)
        self.assertEqual(self.clock.ns,303000000000)

    def test_no_catch_up_burst_scheduling(self):
        self.assertEqual(live.advance(100,100,500),600)
        self.assertEqual(live.advance(100,100,150),200)

    def test_cpu_enumeration_limit_is_explicit(self):
        sample=cpu.ProcSampler(self.proc_root,hz=100,thread_limit=1).sample(23,1)
        self.assertIsNone(sample['process'])
        self.assertTrue(any('limit' in x for x in sample['errors']))

    def test_pid_exit_and_thread_reuse_partial_reports(self):
        for mode in ['exit','reuse']:
            with self.subTest(mode=mode):
                self.setUp()
                original=self.activity
                def change(seconds):
                    original(seconds)
                    if self.clock.ns>=3600000000:
                        if mode=='exit':
                            p=self.proc_root/'23/stat'
                            if p.exists():p.unlink()
                        else:
                            self.put('23/task/24/stat',fake_stat(24,0,start=999,name='XThread0204 (F8'))
                self.clock.callback=change
                run,a=self.capture()
                self.assertEqual(a['reason'],'capture_error')
                self.assertFalse(a['coverage_ok'])
                self.assertTrue((run/'report.md').exists())

    def test_ctrl_c_generates_partial_report_no_signals(self):
        original=self.activity
        def interrupt(seconds):
            original(seconds)
            if self.clock.ns>=3600000000:
                raise KeyboardInterrupt()
        self.clock.callback=interrupt
        with patch('os.kill',side_effect=AssertionError('No target signal permitted')):
            run,a=self.capture()
        self.assertEqual(a['reason'],'interrupted')
        self.assertTrue((run/'report.md').exists())

    def test_optional_scene_and_terminal_freeze_markers(self):
        commands=iter(['w',None,None,None,None,'b','f',None,None,None,'p']+[None]*100)
        run,a=self.capture(scenes=True,input_poll=lambda:next(commands,None))
        labels=json.loads((run/'analysis.json').read_text())['scenes']['wait']
        self.assertGreater(labels['wide']['intervals'],0)
        self.assertGreater(labels['bench']['intervals'],0)
        self.assertGreater(labels['player-closeup']['intervals'],0)
        self.assertEqual(a['freeze_events']['wait']['counts']['FREEZE_RIGHT'],1)

    def test_q_stops_observer_and_eof_disables_interface(self):
        commands=iter([None]*8+['q'])
        _,a=self.capture(scenes=True,input_poll=lambda:next(commands,None))
        self.assertEqual(a['reason'],'user_stop')
        _,b=self.capture(scenes=True,input_poll=lambda:'eof')
        self.assertEqual(b['reason'],'duration')

    def test_markers_permission_failure_degrades_without_elevation(self):
        def denied():raise PermissionError('synthetic')
        run,a=self.capture(marker_factory=denied)
        self.assertIn('unavailable',a['marker_source'])
        self.assertTrue((run/'report.md').exists())

    def test_writer_budgets_exclusive_output_and_symlink_boundary(self):
        stream=io.BytesIO();writer=live.Writer(stream,10000,record_limit=10)
        with self.assertRaises(ValueError):writer.write({'x':'y'*30})
        self.assertEqual(stream.getvalue(),b'')
        first,_=self.capture();second,_=self.capture()
        self.assertNotEqual(first,second)
        original=(first/'report.md').read_text()
        with self.assertRaises(FileExistsError):(first/'report.md').open('x')
        self.assertEqual(original,(first/'report.md').read_text())
        outside=self.root/'outside';outside.mkdir()
        link=self.root/'redirect';link.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):self.capture(base=link)
        self.assertEqual(list(outside.iterdir()),[])

    def test_marker_log_appends_missing_file_and_symlink_rejection(self):
        p=self.root/'markers.jsonl'
        old={'event':'FREEZE_RIGHT','utc':self.clock.utc(),'monotonic_ns':0}
        p.write_text(json.dumps(old)+'\n')
        reader=live.MarkerLog(p)
        try:
            self.assertEqual(reader.poll(self.clock),[])
            new={**old,'monotonic_ns':self.clock.ns}
            with p.open('a') as f:f.write(json.dumps(new)+'\n')
            self.assertEqual(reader.poll(self.clock),[new])
            self.assertEqual(reader.poll(self.clock),[])
        finally:reader.close()
        link=self.root/'link';link.symlink_to(p)
        reader=live.MarkerLog(link)
        self.assertIn('unavailable',reader.status)
        reader.close()

    def test_input_events_keep_only_existing_press_mappings(self):
        device=object.__new__(live.ButtonDevice)
        device.fd=123;device.event=struct.Struct('@llHHi');device.buffer=b''
        data=b''.join(device.event.pack(0,0,k,c,v)for k,c,v in
                      [(1,710,1),(1,708,1),(1,708,2),(1,708,0),(1,30,1),(3,710,1)])
        with patch.object(os,'read',side_effect=[data,BlockingIOError()]):
            result=device.poll(self.clock)
        self.assertEqual([r['event']for r in result],['CAMERA_CHANGE_LEFT','FREEZE_RIGHT'])
        with patch.object(os,'read',side_effect=BlockingIOError()):
            self.assertEqual(device.poll(self.clock),[])
        with self.assertRaises(ValueError):live.ButtonDevice('/tmp/not-input')

    def test_input_overflow_and_bounded_backlog_are_explicit(self):
        d=object.__new__(live.ButtonDevice)
        d.fd=123;d.event=struct.Struct('@llHHi');d.buffer=b''
        with patch.object(os,'read',return_value=d.event.pack(0,0,0,3,0)),self.assertRaisesRegex(ValueError,'overflow'):
            d.poll(self.clock)
        d.buffer=b''
        with patch.object(os,'read',return_value=d.event.pack(0,0,3,0,0)), \
             patch.object(live.select,'select',return_value=([123],[],[])),self.assertRaisesRegex(ValueError,'backlog'):
            d.poll(self.clock)

    def test_invalid_duration_rejected_without_discovery(self):
        for duration in [0,float('nan'),float('inf'),601]:
            with self.subTest(duration=duration),self.assertRaises(ValueError):
                self.capture(duration=duration)

    def test_report_partial_corrupt_tail_offline_no_writes(self):
        run,_=self.capture()
        p=run/'wait/thread-waits.jsonl'
        with p.open('a') as f:f.write('{truncated')
        before={p:p.read_bytes()for p in run.rglob('*')if p.is_file()}
        a,report=live.finish_report(run,json.loads((run/'session.json').read_text()))
        self.assertTrue(a['input_issues'])
        self.assertIn('Malformed',report)
        self.assertEqual(before,{p:p.read_bytes()for p in before})

    def test_missing_thread_metrics_do_not_become_zero(self):
        run,_=self.capture()
        rows,_=live.load_lines(run/'telemetry/telemetry.jsonl')
        rows[1]['processes'][0]['threads']=[]
        meta=json.loads((run/'session.json').read_text())
        result=live.analyze_data(meta,[],rows,[],[])
        self.assertFalse(result['coverage_ok'])
        self.assertTrue(result['streams']['telemetry']['issues'])
        self.assertEqual(result['streams']['wait']['threads']['24']['cpu']['mean'],None)

    def test_scene_before_stream_start_carries_forward(self):
        run,_=self.capture()
        wr,_=live.load_lines(run/'wait/thread-waits.jsonl');cr,_=live.load_lines(run/'telemetry/telemetry.jsonl')
        m=json.loads((run/'session.json').read_text())
        s={'scene':'bench','monotonic_ns':wr[0]['monotonic_ns']-1000,
           'utc':wr[0]['utc']}
        result=live.analyze_data(m,wr,cr,[],[s])
        self.assertEqual(result['scenes']['wait']['bench']['intervals'],len(wr)-2)

    def test_default_cli_duration_is_120(self):
        with patch('sys.argv',['live_profiler']),patch.object(live,'capture',return_value=(None,{'reason':'duration','coverage_ok':True})) as mocked:
            self.assertEqual(live.main(),0)
        self.assertEqual(mocked.call_args.args[0],120)

    def test_explicit_button_device_open_is_read_only_no_grab(self):
        import stat
        from types import SimpleNamespace
        with patch.object(os,'open',return_value=123) as opened, \
             patch.object(os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
             patch.object(os,'close') as closed:
            d=live.ButtonDevice('/dev/input/event17')
            self.assertEqual(opened.call_args.args[1] & os.O_ACCMODE,os.O_RDONLY)
            d.close()
            closed.assert_called_once_with(123)

    def test_clock_mismatch_reports_unverified_not_zero_overlap(self):
        run,_=self.capture()
        w,_=live.load_lines(run/'wait/thread-waits.jsonl');c,_=live.load_lines(run/'telemetry/telemetry.jsonl')
        for r in c:
            r['utc']=(datetime.fromisoformat(r['utc'])+timedelta(days=1)).isoformat()
        meta=json.loads((run/'session.json').read_text())
        a=live.analyze_data(meta,w,c,[],[])
        self.assertIsNone(a['overlap_seconds'])
        self.assertFalse(a['coverage_ok'])
        self.assertIn('overlap: unverified',live.markdown(a))

    def test_zero_sample_report_and_marker_reader_error(self):
        class Broken(NoMarkers):
            def poll(self,clock):raise OSError('synthetic disconnect')
        _,a=self.capture(marker_factory=Broken)
        self.assertIn('stopped',a['marker_source'])
        meta={'guest':[24,20],'gpu':[25,21],'clock_ticks_per_second':100,'duration_seconds':120}
        b=live.analyze_data(meta,[],[],[],[])
        self.assertIsNone(b['overlap_seconds'])
        self.assertIn('Unavailable',live.markdown(b))

    def test_sparse_samples_and_missing_footer_fail_coverage(self):
        run,_=self.capture()
        w,_=live.load_lines(run/'wait/thread-waits.jsonl');c,_=live.load_lines(run/'telemetry/telemetry.jsonl')
        meta=json.loads((run/'completion.json').read_text())
        sparse=[w[0],w[-2],dict(w[-1],samples=2)]
        a=live.analyze_data(meta,sparse,c,[],[])
        self.assertGreater(a['overlap_seconds'],2)
        self.assertFalse(a['coverage_ok'])
        b=live.analyze_data(meta,w[:-1],c,[],[])
        self.assertFalse(b['wait_footer_valid'])
        self.assertFalse(b['coverage_ok'])

    def test_truncated_external_marker_log_is_not_silently_followed(self):
        p=self.root/'markers.jsonl';p.write_text('old data\n')
        reader=live.MarkerLog(p)
        try:
            p.write_text('')
            with self.assertRaisesRegex(ValueError,'truncated'):
                reader.poll(self.clock)
        finally:reader.close()

    def test_existing_recordings_read_only_nonoverlap_and_marker_filter(self):
        root=Path(__file__).resolve().parents[2]/'diagnostics/capture-017'
        if not root.exists():self.skipTest('Local recordings intentionally not in Git')
        w=root/'20261024T045305Z-6yf86ze1';c=root/'20261024T045511Z-d6zw9zsz'
        paths=[w/'metadata.json',w/'thread-waits.jsonl',c/'telemetry.jsonl',root/'scene-markers.jsonl']
        before={p:p.read_bytes()for p in paths}
        wm=json.loads(paths[0].read_text())
        meta={'guest':wm['guest'],'gpu':wm['gpu'],'clock_ticks_per_second':100,'duration_seconds':60}
        result=live.analyze_data(meta,live.load_lines(paths[1])[0],live.load_lines(paths[2])[0],
                                 live.load_lines(paths[3])[0],[])
        self.assertEqual(result['overlap_seconds'],0)
        self.assertFalse(result['coverage_ok'])
        self.assertEqual(result['freeze_events']['wait']['counts']['FREEZE_RIGHT'],7)
        self.assertEqual(result['freeze_events']['telemetry']['counts']['FREEZE_RIGHT'],4)
        self.assertAlmostEqual(result['streams']['wait']['threads']['8519']['cpu']['mean'],95.6686,places=3)
        self.assertEqual(before,{p:p.read_bytes()for p in before})
        self.assertIn('Measured sample overlap: 0.000',live.markdown(result))


if __name__=='__main__':unittest.main()
