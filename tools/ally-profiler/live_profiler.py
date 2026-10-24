#!/usr/bin/env python3
"""Single-command passive NHL collection and offline local reporting. Never launches NHL."""
import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import select
import stat
import struct
import sys

import ally_profiler as cpu
import thread_wait_sampler as waits
import analyze_wait_capture as offline

SCENES = {'w': 'wide', 'b': 'bench', 'p': 'player-closeup', 'o': 'other',
          'u': 'unknown', 'r': 'replay', 'i': 'intro'}
LABELS = set(SCENES.values())
EVENTS = {710: 'CAMERA_CHANGE_LEFT', 708: 'FREEZE_RIGHT'}
CPU_LIMIT = 32 * 1024 * 1024
WAIT_LIMIT = 8 * 1024 * 1024
EVENT_LIMIT = 1024 * 1024


class Writer:
    def __init__(self, stream, limit, record_limit=256 * 1024):
        self.stream, self.limit, self.record_limit, self.size = stream, limit, record_limit, 0

    def write(self, record, final=False):
        data = (json.dumps(record, allow_nan=False, ensure_ascii=True, separators=(',', ':'))+'\n').encode()
        if len(data) > self.record_limit or self.size + len(data) > self.limit - (0 if final else 8192):
            raise ValueError('Output limit reached')
        self.stream.write(data)
        self.stream.flush()
        self.size += len(data)


def find_process(proc):
    found, skipped, examined = [], 0, 0
    for entry in proc.root.iterdir():
        if not entry.name.isdigit():
            continue
        examined += 1
        if examined > 65536:
            raise ValueError('Process discovery limit exceeded')
        try:
            p = proc.stat(int(entry.name))
        except (OSError, ValueError, IndexError):
            skipped += 1
            continue
        if p['name'].casefold() in ('nhllegacy.exe', 'nhllegacy') and p['state'] not in ('Z', 'X', 'x'):
            found.append((int(entry.name), p['start_ticks']))
    if len(found) != 1:
        raise ValueError(f'Expected one readable NHL process; found {len(found)}. No PID guessed.')
    return found[0], skipped


class MarkerLog:
    """Tail only new lines; do not execute or change the external recorder."""
    def __init__(self, path):
        self.path, self.stream, self.buffer = Path(path), None, b''
        self.status = 'External marker recorder must already be running; zero events do not prove it is active.'
        self.initial = True
        self.open_if_present()

    def open_if_present(self):
        if self.stream is not None:
            return
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
            self.stream = os.fdopen(fd, 'rb', buffering=0)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                self.close()
                raise ValueError('Marker log is not a regular file')
            if self.initial:
                self.stream.seek(0, os.SEEK_END)
            self.status = 'Tailing existing log; recorder activity unverified until events arrive.'
        except (OSError, ValueError) as exc:
            self.close()
            self.status = f'Marker log unavailable: {type(exc).__name__}'
        self.initial = False

    def poll(self, clock):
        self.open_if_present()
        if self.stream is None:
            return []
        if self.path.is_symlink() or self.path.stat().st_ino != os.fstat(self.stream.fileno()).st_ino:
            raise ValueError('Marker log replaced; refusing to follow it')
        if os.fstat(self.stream.fileno()).st_size < self.stream.tell():
            raise ValueError('Marker log truncated; refusing uncertain coverage')
        data = self.stream.read(16384)
        self.buffer += data
        if len(self.buffer) > 65536:
            raise ValueError('Marker line/buffer exceeds limit')
        lines = self.buffer.split(b'\n')
        self.buffer = lines.pop()
        result = []
        for line in lines:
            try:
                m = json.loads(line)
                if m['event'] not in EVENTS.values() or not isinstance(m['monotonic_ns'], int):
                    raise ValueError('Unknown marker')
                offline.utc(m)
                result.append({k: m[k] for k in ('event', 'monotonic_ns', 'utc')})
            except (ValueError, KeyError, TypeError):
                self.status = 'Malformed marker lines skipped; coverage incomplete.'
        return result

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class ButtonDevice:
    """Optional explicit evdev node; read only, no grab/ioctl/remapping or raw input log."""
    def __init__(self, path):
        if not re.fullmatch(r'/dev/input/event[0-9]+', str(path)):
            raise ValueError('Expected explicit /dev/input/eventN node')
        self.event = struct.Struct('@llHHi')
        if self.event.size != 24:
            raise ValueError('Only verified 64-bit Linux input_event layout supported')
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if not stat.S_ISCHR(os.fstat(self.fd).st_mode):
                raise ValueError('Input node is not a character device')
        except (OSError, ValueError):
            os.close(self.fd)
            raise
        self.buffer = b''
        self.status = 'Explicit input node (device identity unverified); only rear-button presses retained.'

    def poll(self, clock):
        result = []
        for _ in range(16):  # Bounded drain; avoid stale markers behind normal input traffic.
            try:
                data = os.read(self.fd, self.event.size * 64)
            except BlockingIOError:
                return result
            if not data:
                raise OSError('Input device closed')
            self.buffer += data
            while len(self.buffer) >= self.event.size:
                _, _, kind, code, value = self.event.unpack(self.buffer[:self.event.size])
                self.buffer = self.buffer[self.event.size:]
                if kind == 0 and code == 3:  # EV_SYN / SYN_DROPPED
                    raise ValueError('Input overflow; event timing is unreliable')
                if kind == 1 and value == 1 and code in EVENTS:
                    result.append({**waits.stamp(clock), 'event': EVENTS[code]})
        if select.select([self.fd], [], [], 0)[0]:
            raise ValueError('Input backlog exceeds bounded drain; marker timing unverified')
        return result

    def close(self):
        os.close(self.fd)


def terminal_command(stream):
    if not select.select([stream], [], [], 0)[0]:
        return None
    line = stream.readline(128)
    return 'eof' if line == '' else line.strip().lower()


def load_lines(path):
    rows, errors = [], []
    if not path.exists():
        return rows, ['File missing']
    if path.stat().st_size > CPU_LIMIT + 8192:
        return rows, ['Input exceeds analysis limit']
    for n, line in enumerate(path.read_text().splitlines(), 1):
        try:
            row=json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            if not isinstance(row,dict):
                raise ValueError('Expected JSON object')
            rows.append(row)
        except (ValueError, TypeError):
            errors.append(f'Malformed JSONL line {n}; ignored')
            if len(errors) >= 20:
                break
    return rows, errors


def scene_at(ns, scenes):
    label = 'unknown'
    for s in scenes:
        if s['monotonic_ns'] > ns:
            break
        label = s['scene']
    return label


def sensor_stats(samples):
    values = {}
    for row in samples:
        for n, gpu in enumerate(row.get('gpus', [])):
            for key, item in gpu.get('sensors', {}).items():
                if key == 'utilization':
                    continue
                label = (item.get('label') or {}).get('value')
                name = f'GPU{n} {key} ({label or "unlabelled"}, {item.get("unit")})'
                values.setdefault(name, []).append(item.get('value'))
    return {key: {**offline.describe([v for v in vals if v is not None]),
                  'missing': sum(v is None for v in vals)} for key, vals in values.items()}


def summarize(rows, kind, selected, hz):
    samples, issues, rates = [], [], []
    for row in rows:
        if row.get('kind','sample') != 'sample':
            continue
        try:
            if not isinstance(row['monotonic_ns'],int) or row['collection_seconds'] < 0:
                raise ValueError('Invalid sample clock')
            offline.utc(row)
            samples.append(row)
        except (KeyError,TypeError,ValueError):
            if len(issues)<20:
                issues.append('Malformed sample excluded; coverage incomplete.')
    for a, b in zip(samples, samples[1:]):
        try:
            dt = (b['monotonic_ns']-a['monotonic_ns'])/1e9
            if dt <= 0:
                raise ValueError('Nonincreasing sample clock')
            maps = [offline.thread_map(r, kind) for r in (a, b)]
            rate = {'interval_begin_ns': a['monotonic_ns'], 'monotonic_ns': b['monotonic_ns'], 'snapshot': b, 'threads': {}}
            for tid, start in selected.items():
                old, new = [m[tid] for m in maps]
                if old['start_ticks'] != start or new['start_ticks'] != start or new['ticks'] < old['ticks']:
                    raise ValueError('Selected identity/counter discontinuity')
                rate['threads'][tid] = {'cpu': 100*(new['ticks']-old['ticks'])/hz/dt,
                    'switches_per_second': {key: ((new['context_switches'][key]-old['context_switches'][key])/dt
                        if old['context_switches'].get(key) is not None and
                           new['context_switches'].get(key) is not None and
                           new['context_switches'][key] >= old['context_switches'][key] else None)
                        for key in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches')}}
            rates.append(rate)
        except (KeyError, TypeError, ValueError, IndexError):
            if len(issues) < 20:
                issues.append('Invalid adjacent interval excluded; identity continuity required.')
    result = {'samples': len(samples), 'valid_intervals': len(rates), 'issues': issues, 'threads': {}}
    result['clock_valid'] = False
    if samples:
        result['first_ns'], result['last_ns'] = samples[0]['monotonic_ns'], samples[-1]['monotonic_ns']
        result['first_utc'], result['last_utc'] = samples[0]['utc'], samples[-1]['utc']
    if len(samples) >= 2:
        try:
            result['timing'] = offline.times(samples)
            result['clock_valid'] = True
        except (ValueError, KeyError, TypeError):
            issues.append('Clock validation failed; correlation disabled.')
    for tid in selected:
        values = []
        for r in samples:
            try:
                t = offline.thread_map(r, kind)[tid]
                if t['start_ticks'] == selected[tid]:
                    values.append(t)
            except (KeyError, TypeError, ValueError, IndexError):
                pass
        result['threads'][str(tid)] = {
            'cpu': offline.describe([r['threads'][tid]['cpu'] for r in rates]),
            'states': dict(Counter(t['state'] for t in values)),
            'switches_per_second': {key: offline.describe([r['threads'][tid]['switches_per_second'][key]
                 for r in rates if r['threads'][tid]['switches_per_second'][key] is not None])
                 for key in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches')}}
        if kind == 'wait':
            result['threads'][str(tid)]['wchan'] = dict(Counter(
                t.get('wchan', {}).get('value') or '<unavailable>' for t in values))
    result['sensors'] = {}
    result['process_cpu'] = offline.describe([r['processes'][0]['process']['cpu_percent_one_core']
        for r in samples if kind == 'telemetry' and r.get('processes') and
        r['processes'][0].get('process') and r['processes'][0]['process'].get('cpu_percent_one_core') is not None])
    if kind == 'telemetry':
        result['sensors'] = sensor_stats(samples)
    return result, rates, samples


def analyze_data(meta, wait_rows, cpu_rows, markers, scenes):
    selected = {meta['guest'][0]: meta['guest'][1], meta['gpu'][0]: meta['gpu'][1]}
    hz = meta['clock_ticks_per_second']
    result = {'reason': meta.get('stop_reason', 'unknown'), 'requested_seconds': meta['duration_seconds'],
              'guest_tid': meta['guest'][0], 'gpu_tid': meta['gpu'][0], 'marker_source': meta.get('marker_status'),
              'capture_detail': meta.get('stop_detail'), 'sensor_errors': meta.get('sensor_errors', []),
              'scene_status': meta.get('scene_status', 'Optional scene input not independently verified'),
              'scene_transition_intervals_excluded': {},
              'streams': {}, 'overlap_seconds': None, 'clock_compatible': False, 'scenes': {}, 'freeze_events': {}}
    state = {}
    for kind, rows in [('wait', wait_rows), ('telemetry', cpu_rows)]:
        summary, rates, samples = summarize(rows, kind, selected, hz)
        result['streams'][kind] = summary
        state[kind] = rates, samples
    w, c = result['streams']['wait'], result['streams']['telemetry']
    footers=[r for r in wait_rows if r.get('kind')=='end']
    result['wait_footer_valid']=(len(footers)==1 and wait_rows[-1] is footers[0]
        and footers[0].get('samples')==w['samples'])
    if w['clock_valid'] and c['clock_valid']:
        offsets = [offline.utc(state[k][1][0])-state[k][1][0]['monotonic_ns']/1e9 for k in state]
        result['clock_compatible'] = abs(offsets[0]-offsets[1]) <= .05
        if result['clock_compatible']:
            lo, hi = max(w['first_ns'], c['first_ns']), min(w['last_ns'], c['last_ns'])
            result['overlap_seconds'] = max(0, hi-lo)/1e9
    for kind,interval in [('wait',.2),('telemetry',.5)]:
        result['streams'][kind]['nominal_samples']=math.ceil(meta['duration_seconds']/interval)
    result['coverage_ok'] = (result['clock_compatible'] and result['overlap_seconds'] >= .8*meta['duration_seconds']
        and result['wait_footer_valid']
        and all(v['samples'] >= .8*v['nominal_samples'] and
                v['valid_intervals'] >= max(1,.8*(v['samples']-1)) for v in result['streams'].values()))
    for kind, (rates, samples) in state.items():
        good_markers, good_scenes = [], []
        if result['streams'][kind]['clock_valid']:
            try:
                good_markers = offline.markers_in(markers, samples)
                offset = offline.utc(samples[0])-samples[0]['monotonic_ns']/1e9
                for s in scenes:
                    if s.get('scene') not in LABELS:
                        continue
                    # Carry a same-session label into a slightly later stream start.
                    if not samples[0]['monotonic_ns']-(meta['duration_seconds']+2)*1e9 <= s['monotonic_ns'] <= samples[-1]['monotonic_ns']:
                        continue
                    if abs(offline.utc(s)-s['monotonic_ns']/1e9-offset) > .05:
                        raise ValueError('Scene clock mismatch')
                    good_scenes.append(s)
                good_scenes.sort(key=lambda s:s['monotonic_ns'])
            except (ValueError, KeyError, TypeError):
                result['streams'][kind]['issues'].append('Marker/scene clocks inconsistent; correlation disabled.')
                good_markers, good_scenes = [], []
        freezes = [m for m in good_markers if m['event'] == 'FREEZE_RIGHT']
        near = [r for r in rates if any(abs(r['monotonic_ns']-m['monotonic_ns']) < 1e9 for m in freezes)]
        near_ns = {r['monotonic_ns'] for r in near}
        other = [r for r in rates if r['monotonic_ns'] not in near_ns]
        avg = lambda rows, tid: offline.describe([r['threads'][tid]['cpu'] for r in rows])
        def channels(sub):
            return dict(Counter(offline.thread_map(r['snapshot'],kind)[meta['gpu'][0]]
                .get('wchan',{}).get('value') or '<unavailable>' for r in sub)) if kind=='wait' else {}
        result['freeze_events'][kind] = {'counts': dict(Counter(m['event'] for m in good_markers)),
            'near_intervals': len(near), 'other_intervals': len(other),
            'near_wait_channels': channels(near), 'unmarked_wait_channels': channels(other),
            'near_sensors': sensor_stats([r['snapshot'] for r in near]) if kind=='telemetry' else {},
            'unmarked_sensors': sensor_stats([r['snapshot'] for r in other]) if kind=='telemetry' else {},
            'near_cpu': {str(t): avg(near,t) for t in selected},
            'unmarked_cpu': {str(t): avg(other,t) for t in selected},
            'events': [{'utc': m['utc'], 'relative_seconds': (m['monotonic_ns']-samples[0]['monotonic_ns'])/1e9,
                        'cpu': {str(t): avg([r for r in rates if abs(r['monotonic_ns']-m['monotonic_ns'])<1e9],t)
                                for t in selected}} for m in freezes]}
        stable=[r for r in rates if scene_at(r['interval_begin_ns'],good_scenes)==scene_at(r['monotonic_ns'],good_scenes)]
        result['scene_transition_intervals_excluded'][kind]=len(rates)-len(stable)
        result['scenes'][kind] = {label: {'intervals': len(sub), 'cpu': {str(t): avg(sub,t) for t in selected},
                     'gpu_wait_channels': dict(Counter(offline.thread_map(r['snapshot'],kind)[meta['gpu'][0]]
                         .get('wchan', {}).get('value') or '<unavailable>' for r in sub)) if kind=='wait' else {}}
                for label in sorted(LABELS)
                for sub in [[r for r in stable if scene_at(r['monotonic_ns'],good_scenes)==label]]}
        for label,v in result['scenes'][kind].items():
            v['sensors']=sensor_stats([r['snapshot'] for r in stable if scene_at(r['monotonic_ns'],good_scenes)==label]) if kind=='telemetry' else {}
    return result


def markdown(a):
    def number(v):
        return 'Unavailable' if v is None else f'{v:.2f}'
    guest, gpu = str(a['guest_tid']), str(a['gpu_tid'])
    overlap = 'unverified' if a['overlap_seconds'] is None else f'{a["overlap_seconds"]:.3f} s'
    lines = ['# NHL local performance diagnostic', '',
             f'Stop reason: **{a["reason"]}**. Requested duration: {a["requested_seconds"]:.1f} s.',
             f'**Measured sample overlap: {overlap}**. Clock compatible: {a["clock_compatible"]}; '
             f'usable overlap/interval coverage: {a["coverage_ok"]}; wait footer valid: {a.get("wait_footer_valid")}.', '',
             'No frame-time/FPS, simulation-step, unique-image, input-latency or GPU-completion measurements were collected.',
             'Process and thread CPU overlap; 100% is one logical core. Unknown measurements are not zero.', '',
             f'Marker source: {a.get("marker_source") or "unavailable/unverified"}.',
             f'Capture detail: {a.get("capture_detail") or "none"}. Sensor discovery errors: {a.get("sensor_errors")}.',
             f'Scene input: {a.get("scene_status")}.', '',
             '| Stream | Samples / valid intervals | Guest mean CPU | GPU Commands mean CPU |',
             '| --- | --- | --- | --- |']
    for k, s in a['streams'].items():
        lines.append(f'| {k} | {s["samples"]} / {s["valid_intervals"]} | '
                     f'{number(s["threads"][guest]["cpu"]["mean"])}% | {number(s["threads"][gpu]["cpu"]["mean"])}% |')
    lines += ['', '## Observed thread states, waits and collection cost', '']
    for k,s in a['streams'].items():
        lines += [f'### {k}', '', f'Coverage: {s.get("first_utc", "none")} to {s.get("last_utc", "none")}.']
        if 'timing' in s:
            lines += [f'Read cost mean/max: {number(s["timing"]["collection_ms"]["mean"])} / '
                      f'{number(s["timing"]["collection_ms"]["max"])} ms; '
                      f'max sample gap: {number(s["timing"]["gap_seconds"]["max"])} s.']
        for t in (guest,gpu):
            v=s['threads'][t]
            lines += [f'- TID {t}: states {json.dumps(v["states"])}; CPU range '
                      f'{number(v["cpu"]["min"])}–{number(v["cpu"]["max"])}%; switches/s '
                      f'voluntary {number(v["switches_per_second"]["voluntary_ctxt_switches"]["mean"])} / '
                      f'involuntary {number(v["switches_per_second"]["nonvoluntary_ctxt_switches"]["mean"])}.']
            if 'wchan' in v:
                lines += [f'  Wait symbols (snapshot counts): {json.dumps(v["wchan"])}.']
        if k == 'telemetry':
            lines += [f'Process CPU mean: {number(s["process_cpu"]["mean"])}% (overlaps threads).']
        lines += [f'Validation notes: {"; ".join(s["issues"]) or "none"}.', '']
    lines += ['## Freeze correlations', '',
              '±1-second interval-ending neighborhoods; unmarked does not mean smooth. Human reaction and sampling skew apply.']
    for k,f in a['freeze_events'].items():
        lines += ['', f'### {k}', '', f'In-window markers: {json.dumps(f["counts"])}. '
                  f'Near/unmarked intervals: {f["near_intervals"]}/{f["other_intervals"]}.',
                  f'Guest near/unmarked CPU: {number(f["near_cpu"][guest]["mean"])} / '
                  f'{number(f["unmarked_cpu"][guest]["mean"])}%; CP: {number(f["near_cpu"][gpu]["mean"])} / '
                  f'{number(f["unmarked_cpu"][gpu]["mean"])}%.']
        if f['near_wait_channels'] or f['unmarked_wait_channels']:
            lines += [f'CP wait symbols near: {json.dumps(f["near_wait_channels"])}; '
                      f'unmarked: {json.dumps(f["unmarked_wait_channels"])} (snapshot hits, not durations).']
        for name,v in f['near_sensors'].items():
            baseline=f['unmarked_sensors'].get(name,{})
            lines += [f'- {name} near/unmarked mean: {number(v["mean"])} / {number(baseline.get("mean"))}.']
        for e in f['events']:
            lines += [f'- Freeze at {e["relative_seconds"]:.3f} s: guest '
                      f'{number(e["cpu"][guest]["mean"])}%, CP {number(e["cpu"][gpu]["mean"])}% '
                      f'(intervals={e["cpu"][guest]["n"]}; edge windows may be clipped).']
    lines += ['', '## Scene comparisons', '', 'Scene labels are optional human observations, never inferred from camera presses.',
              f'Intervals crossing a label transition are excluded: {a.get("scene_transition_intervals_excluded")}.', '',
              '| Stream / scene | Intervals | Guest CPU | CP CPU | CP DRM-label hits |', '| --- | ---: | ---: | ---: | ---: |']
    for k,scenes in a['scenes'].items():
        for label,v in scenes.items():
            drm = str(sum(n for symbol,n in v['gpu_wait_channels'].items() if 'drm_syncobj' in symbol)) if k=='wait' else 'Unavailable'
            lines += [f'| {k} / {label} | {v["intervals"]} | {number(v["cpu"][guest]["mean"])}% | '
                      f'{number(v["cpu"][gpu]["mean"])}% | {drm} |']
    lines += ['', 'Scene sensor means (only labelled, non-transition intervals):']
    for label,v in a['scenes']['telemetry'].items():
        if v['intervals']:
            for name,sensor in v['sensors'].items():
                lines += [f'- {label} / {name}: {number(sensor["mean"])} (n={sensor["n"]}).']
    lines += ['', '## Valid sensor summaries', '', 'Entire gpu_busy_percent source excluded; no rescaling. '
              'DPM states are not instantaneous clocks. slowPPT is not GPU-only power; do not add channels.', '']
    for label,v in a['streams']['telemetry']['sensors'].items():
        lines += [f'- {label}: n={v["n"]}, missing={v["missing"]}, mean {number(v["mean"])}, '
                  f'range {number(v["min"])}–{number(v["max"])}.']
    if not a['streams']['telemetry']['sensors']:
        lines += ['No valid sensor channels available.']
    lines += ['', '## Interpretation and limitations', '',
              'Observed CPU occupancy includes useful work and polling. R is running or runnable; S/D do not identify '
              'lock ownership or the waited dependency. Wait hit counts are not durations. DRM sync-object waits '
              'do not establish GPU saturation, shader compilation or a specific Vulkan caller. Generic futex waits '
              'do not identify a GPU fence. A match clock or high presentation FPS cannot prove smooth simulation.',
              'Hypotheses: serial guest execution, synchronization/backpressure and presentation freshness remain '
              'competing possibilities. Correlations alone select no root cause or optimization.',
              'Correlations are per stream; joint interpretation requires actual overlap and compatible clocks. '
              'Read durations omit some discovery/guard/input work and are not measured gameplay slowdown. Scene entry typing/focus and marker '
              'reaction add uncertainty; camera markers do not alternate scene types. Partial/missing data and low '
              'overlap limit interpretation; inspect raw metadata/errors and sampling gaps. No absent marker proves '
              'that no freeze occurred. Publish only reviewed aggregates; keep raw logs local.', '']
    return '\n'.join(lines)


def finish_report(run, meta):
    data, issues = {}, []
    for key,path in [('wait','wait/thread-waits.jsonl'),('cpu','telemetry/telemetry.jsonl'),
                     ('markers','markers.jsonl'),('scenes','scenes.jsonl')]:
        data[key], e = load_lines(run/path)
        issues += [f'{key}: {x}' for x in e]
    analysis = analyze_data(meta, data['wait'], data['cpu'], data['markers'], data['scenes'])
    analysis['input_issues'] = issues
    return analysis, markdown(analysis) + ('\nInput read issues: '+ '; '.join(issues)+'\n' if issues else '')


def advance(previous, period, now):
    scheduled = previous+period
    return now+period if scheduled <= now else scheduled


def capture(duration=120., scenes=False, marker_device=None, proc=None, clock=None, base=None,
            cpu_factory=None, sensors=None, input_poll=None, marker_factory=None):
    if not math.isfinite(duration) or not 1 <= duration <= 600:
        raise ValueError('Duration must be 1..600 seconds')
    proc, clock = proc or waits.Proc(), clock or waits.Clock()
    (pid, process_start), skipped = find_process(proc)
    choice = waits.discover(pid, proc=proc, clock=clock)
    if choice['ambiguous'] or choice['process_start_ticks'] != process_start:
        raise ValueError('Thread activity ambiguous or process changed; no capture started')
    guest = choice['selected']['guest']; gpu = choice['selected']['gpu']
    selected = [(guest['tid'],guest['start_ticks']), (gpu['tid'],gpu['start_ticks'])]
    def guard():
        proc.validate(pid, process_start)
        for r, pair in zip(('guest','gpu'), selected):
            t=proc.selected(pid,*pair)
            if waits.role(t['name']) != r or t['name'] != choice['selected'][r]['name']:
                raise waits.IdentityError('Selected name/role changed')
    if find_process(proc)[0] != (pid,process_start):
        raise ValueError('NHL process set changed during discovery')
    guard()
    sampler = (cpu_factory or (lambda: cpu.ProcSampler(thread_limit=waits.MAX_THREADS)))()
    devices, sensor_errors = sensors if sensors is not None else cpu.discover(Path('/sys/class/drm'))
    run = cpu.new_run(base)
    for name in ('wait','telemetry'):
        (run/name).mkdir(mode=0o700)
    meta = {'schema': 1, 'tool': 'live_profiler', 'pid': pid, 'process_start_ticks': process_start,
            'guest': list(selected[0]), 'gpu': list(selected[1]), 'clock_ticks_per_second': sampler.hz,
            'boot_id': proc.boot(), 'duration_seconds': duration, 'cpu_interval_seconds': .5,
            'wait_interval_seconds': .2, 'discovery_skipped_processes': skipped, 'discovery': choice,
            'sensor_errors': sensor_errors, 'limits_bytes': {'cpu':CPU_LIMIT,'wait':WAIT_LIMIT,'events':EVENT_LIMIT},
            'note': 'Single scheduling loop interleaves both streams; actual overlap is measured after recording.'}
    cpu.write_json(run/'wait/metadata.json', {'schema':1,'tool':'thread_wait_sampler','pid':pid,
        'process_start_ticks':process_start,'guest':list(selected[0]),'gpu':list(selected[1]),
        'names':{str(t['tid']):t['name'] for t in (guest,gpu)},'clock_ticks_per_second':sampler.hz,
        'requested_duration_seconds':duration,'interval_seconds':.2,'boot_id':proc.boot()})
    cpu.write_json(run/'telemetry/metadata.json', {'schema':1,'session':'desktop','pids':[pid],
        'requested_duration_seconds':duration,'interval_seconds':.5,'clock_ticks_per_second':sampler.hz,
        'discovery_errors':sensor_errors,'boot_id':proc.boot()})
    marker = None
    try:
        factory = marker_factory or (lambda: ButtonDevice(marker_device) if marker_device else
                                     MarkerLog(cpu.default_output_base()/'scene-markers.jsonl'))
        marker = factory()
        meta['marker_status'] = marker.status
    except (OSError, ValueError) as exc:
        meta['marker_status'] = f'Markers unavailable: {type(exc).__name__}; no elevation attempted.'
    scene_poll = input_poll if scenes else None
    if scenes and scene_poll is None:
        if sys.stdin.isatty():
            scene_poll = lambda: terminal_command(sys.stdin)
        else:
            meta['scene_status'] = 'Scene input disabled: stdin is not a TTY'
    print(f'Profiling PID {pid}; guest {selected[0][0]}, GPU Commands {selected[1][0]}. Output: {run}', flush=True)
    print('Optional labels: w wide, b bench, p player, o other, u unknown, r replay, i intro; '
          'f freeze, c camera, q stop. Type a letter then Enter when --scenes is enabled.', flush=True)
    start = clock.monotonic_ns(); deadline = start + int(duration*1e9)
    next_cpu = next_wait = start
    meta.update(stop_reason='incomplete',begin_monotonic_ns=start)
    cpu.write_json(run/'session.json',meta)
    reason, detail, wait_count, hidden = 'duration', None, 0, 0
    previous = {}
    with ExitStack() as stack:
        writers = {k: Writer(stack.enter_context((run/p).open('xb')),limit,record)
                   for k,p,limit,record in [('cpu','telemetry/telemetry.jsonl',CPU_LIMIT,256*1024),
                       ('wait','wait/thread-waits.jsonl',WAIT_LIMIT,16384),
                       ('markers','markers.jsonl',EVENT_LIMIT,16384),('scenes','scenes.jsonl',EVENT_LIMIT,16384)]}
        writers['scenes'].write({**waits.stamp(clock),'scene':'unknown'})
        try:
            while clock.monotonic_ns() < deadline:
                now=clock.monotonic_ns()
                if now >= next_cpu:
                    guard()
                    sample = {**waits.stamp(clock),'elapsed_seconds':(now-start)/1e9,
                              'processes':[sampler.sample(pid,now/1e9)],
                              'gpus':[cpu.gpu_sample(d) for d in devices]}
                    guard()
                    sample['collection_seconds']=(clock.monotonic_ns()-sample['monotonic_ns'])/1e9
                    writers['cpu'].write(sample)
                    if sample['processes'][0].get('process') is None:
                        raise ValueError('Process telemetry unavailable; partial record preserved')
                    next_cpu=advance(next_cpu,500000000,clock.monotonic_ns())
                now=clock.monotonic_ns()
                if now >= next_wait and now < deadline:
                    guard()
                    sample={**waits.stamp(clock),'kind':'sample','threads':[]}
                    for tid,ticks in selected:
                        t=proc.snapshot(pid,tid,ticks)
                        if t['ticks'] < previous.get(tid,t['ticks']):
                            raise waits.IdentityError('Selected CPU counter regressed')
                        sample['threads'].append(t)
                    guard()
                    sample['read_end_monotonic_ns']=clock.monotonic_ns()
                    sample['collection_seconds']=(sample['read_end_monotonic_ns']-sample['monotonic_ns'])/1e9
                    writers['wait'].write(sample)
                    previous={t['tid']:t['ticks'] for t in sample['threads']}
                    wait_count+=1
                    hidden+=sum(t['wchan']['status']!='symbol' for t in sample['threads'])
                    next_wait=advance(next_wait,200000000,clock.monotonic_ns())
                if marker:
                    try:
                        for m in marker.poll(clock):
                            writers['markers'].write(m)
                        meta['marker_status']=marker.status
                    except (OSError,ValueError) as exc:
                        meta['marker_status']=f'Marker reader stopped: {type(exc).__name__}: {str(exc)[:128]}'
                        marker.close(); marker=None
                if scene_poll:
                    command=scene_poll()
                    if command in SCENES:
                        writers['scenes'].write({**waits.stamp(clock),'scene':SCENES[command]})
                    elif command in ('f','c'):
                        writers['markers'].write({**waits.stamp(clock),'event':EVENTS[708 if command=='f' else 710]})
                    elif command=='q':
                        reason='user_stop'; break
                    elif command=='eof':
                        scene_poll=None
                now=clock.monotonic_ns()
                clock.sleep(max(0,(min(next_cpu,next_wait,deadline,now+100000000)-now)/1e9))
        except KeyboardInterrupt:
            reason='interrupted'
        except (OSError,ValueError,IndexError) as exc:
            reason,detail='capture_error',f'{type(exc).__name__}: {exc}'[:512]
        finally:
            if marker:
                marker.close()
        writers['wait'].write({'kind':'end',**waits.stamp(clock),'reason':reason,'detail':detail,
                               'samples':wait_count,'unavailable_wchan_observations':hidden},final=True)
    meta.update(stop_reason=reason,stop_detail=detail,begin_monotonic_ns=start,end=waits.stamp(clock))
    cpu.write_json(run/'completion.json',meta)
    analysis, report = finish_report(run,meta)
    cpu.write_json(run/'analysis.json',analysis)
    with (run/'report.md').open('x') as f:
        f.write(report)
    overlap = 'unverified' if analysis['overlap_seconds'] is None else f'{analysis["overlap_seconds"]:.3f}s'
    print(f'Finished: {reason}; measured overlap {overlap}. Report: {run / "report.md"}')
    return run,analysis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration',type=float,default=120.)
    parser.add_argument('--scenes',action='store_true',help='Optional nonblocking terminal labels (letter + Enter)')
    parser.add_argument('--marker-device',help='Optional explicit existing /dev/input/eventN; read-only, no grab')
    parser.add_argument('--analyze',type=Path,help='Offline reanalysis of one coordinator run; prints Markdown only')
    args=parser.parse_args()
    try:
        if args.analyze:
            meta=json.loads((args.analyze/'session.json').read_text())
            if (args.analyze/'completion.json').exists():
                meta.update(json.loads((args.analyze/'completion.json').read_text()))
            print(finish_report(args.analyze,meta)[1])
            return 0
        _,analysis=capture(args.duration,args.scenes,args.marker_device)
        return 0 if analysis['reason']=='duration' and analysis['coverage_ok'] else 2
    except KeyboardInterrupt:
        parser.exit(130,'Stopped before recording/report setup finished; no target signal sent.\n')
    except (OSError,ValueError,KeyError,IndexError) as exc:
        parser.exit(2,f'Profiler error: {exc}\nPartial files, if any, are preserved.\n')


if __name__=='__main__':
    sys.exit(main())
