#!/usr/bin/env python3
"""Offline analysis of separate wait/CPU recordings and multi-session markers.

Reads only explicitly supplied recording files; writes aggregate JSON to stdout.
No proc/sysfs access, live sampling, target control or automatic synchronization.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics


def load(path, lines=False):
    def reject(value):
        raise ValueError(f'Nonfinite JSON constant: {value}')
    text = Path(path).read_text(encoding='utf-8')
    return ([json.loads(line, parse_constant=reject) for line in text.splitlines()]
            if lines else json.loads(text, parse_constant=reject))


def utc(row):
    value = datetime.fromisoformat(row['utc'])
    if value.utcoffset() is None:
        raise ValueError('Timezone-aware UTC required')
    return value.timestamp()


def times(rows):
    if len(rows) < 2:
        raise ValueError('At least two samples required')
    gaps = []
    for a, b in zip(rows, rows[1:]):
        gap = (b['monotonic_ns'] - a['monotonic_ns']) / 1e9
        if gap <= 0 or utc(b) <= utc(a):
            raise ValueError('Nonincreasing sample clocks')
        gaps.append(gap)
    offsets = [utc(r) - r['monotonic_ns'] / 1e9 for r in rows]
    if max(offsets) - min(offsets) > .05:
        raise ValueError('UTC/monotonic offset discontinuity exceeds 50ms')
    overhead = [r['collection_seconds'] for r in rows]
    if any(not math.isfinite(x) or x < 0 for x in overhead):
        raise ValueError('Invalid collection duration')
    return {'samples': len(rows), 'start_utc': rows[0]['utc'], 'last_sample_utc': rows[-1]['utc'],
            'span_seconds': (rows[-1]['monotonic_ns'] - rows[0]['monotonic_ns']) / 1e9,
            'gap_seconds': describe(gaps), 'collection_ms': describe([x * 1000 for x in overhead]),
            'utc_minus_monotonic_spread_ms': (max(offsets) - min(offsets)) * 1000}


def describe(values):
    if not values:
        return {'n': 0, 'mean': None, 'min': None, 'max': None}
    if any(not math.isfinite(v) for v in values):
        raise ValueError('Nonfinite statistic')
    return {'n': len(values), 'mean': statistics.mean(values), 'min': min(values),
            'max': max(values), 'median': statistics.median(values)}


def markers_in(markers, rows):
    """UTC filters old boots/sessions first; monotonic must then agree."""
    start, end = rows[0], rows[-1]
    reference = utc(start) - start['monotonic_ns'] / 1e9
    result = []
    for marker in markers:
        if marker['event'] not in ('FREEZE_RIGHT', 'CAMERA_CHANGE_LEFT'):
            raise ValueError('Unknown marker event')
        if not utc(start) <= utc(marker) <= utc(end):
            continue
        if not start['monotonic_ns'] <= marker['monotonic_ns'] <= end['monotonic_ns']:
            raise ValueError('Marker UTC and monotonic coverage disagree')
        if abs(utc(marker) - marker['monotonic_ns'] / 1e9 - reference) > .05:
            raise ValueError('Marker clock offset inconsistent with recording')
        if result and marker['monotonic_ns'] <= result[-1]['monotonic_ns']:
            raise ValueError('Nonincreasing in-window markers')
        result.append(marker)
    return result


def thread_map(row, kind):
    items = row['threads'] if kind == 'wait' else row['processes'][0]['threads']
    key = 'tid' if kind == 'wait' else 'id'
    result = {t[key]: t for t in items}
    if len(result) != len(items):
        raise ValueError('Duplicate TID')
    return result


def intervals(rows, kind, identities, hz):
    if not isinstance(hz, int) or hz <= 0:
        raise ValueError('Positive clock tick frequency required')
    for row in rows:
        for tid, start in identities.items():
            t = thread_map(row, kind).get(tid)
            if t is None or t['start_ticks'] != start:
                raise ValueError('Missing or changed selected thread identity')
    result = []
    for a, b in zip(rows, rows[1:]):
        seconds = ((b['elapsed_seconds'] - a['elapsed_seconds']) if kind == 'telemetry'
                   else (b['monotonic_ns'] - a['monotonic_ns']) / 1e9)
        if seconds <= 0:
            raise ValueError('Invalid CPU interval')
        record = {'monotonic_ns': b['monotonic_ns'], 'seconds': seconds, 'snapshot': b, 'threads': {}}
        for tid in identities:
            old, new = thread_map(a, kind)[tid], thread_map(b, kind)[tid]
            if old['name'] != new['name']:
                raise ValueError('Selected thread renamed')
            delta = new['ticks'] - old['ticks']
            if delta < 0:
                raise ValueError('CPU counter regression')
            switches = {}
            for name in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches'):
                x, y = old['context_switches'].get(name), new['context_switches'].get(name)
                if x is None or y is None:
                    switches[name] = None
                elif y < x:
                    raise ValueError('Context-switch counter regression')
                else:
                    switches[name] = (y - x) / seconds
            record['threads'][tid] = {'cpu': 100 * delta / hz / seconds, 'switches': switches}
        if kind == 'telemetry':
            old, new = a['processes'][0]['process'], b['processes'][0]['process']
            delta = new['ticks'] - old['ticks']
            if delta < 0:
                raise ValueError('Process CPU counter regression')
            record['process_cpu'] = 100 * delta / hz / seconds
            for tid in identities:
                reported = thread_map(b, kind)[tid]['cpu_percent_one_core']
                if reported is None or abs(reported - record['threads'][tid]['cpu']) > 1e-8:
                    raise ValueError('Recorded CPU rate disagrees with counters/elapsed time')
        result.append(record)
    return result


def group(rows, kind, ids):
    out = {'n': len(rows), 'threads': {}}
    for tid in ids:
        states = Counter(thread_map(r['snapshot'], kind)[tid]['state'] for r in rows)
        t = {'cpu': describe([r['threads'][tid]['cpu'] for r in rows]), 'states': dict(states),
             'switches_per_second': {name: describe([r['threads'][tid]['switches'][name] for r in rows
                                                   if r['threads'][tid]['switches'][name] is not None])
                                    for name in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches')}}
        if kind == 'wait':
            channels = Counter(thread_map(r['snapshot'], kind)[tid]['wchan']['raw'] for r in rows)
            t['wchan_raw_counts'] = dict(channels)
            t['wchan_status_counts'] = dict(Counter(thread_map(r['snapshot'], kind)[tid]['wchan']['status']
                                                   for r in rows))
        out['threads'][tid] = t
    if kind == 'telemetry':
        out['process_cpu'] = describe([r['process_cpu'] for r in rows])
        out['sensors'] = {}
        if rows:
            for key, item in rows[0]['snapshot']['gpus'][0]['sensors'].items():
                if key == 'utilization':
                    continue  # Entire known-invalid source, including nominally in-range values.
                values = [r['snapshot']['gpus'][0]['sensors'][key]['value'] for r in rows]
                out['sensors'][key] = {'unit': item['unit'], 'label': item.get('label'),
                                       'missing': sum(v is None for v in values),
                                       **describe([v for v in values if v is not None])}
    return out


def around(rows, marker, lo, hi):
    return [r for r in rows if lo <= (r['monotonic_ns'] - marker['monotonic_ns']) / 1e9 < hi]


def event_analysis(rows, kind, ids, markers, first_ns, half=1.):
    freezes = [m for m in markers if m['event'] == 'FREEZE_RIGHT']
    cameras = [m for m in markers if m['event'] == 'CAMERA_CHANGE_LEFT']
    def selected(width):
        return [r for r in rows if any(-width * 1e9 <= r['monotonic_ns'] - m['monotonic_ns'] < width * 1e9
                                      for m in freezes)]
    near = selected(half)
    near_times = {r['monotonic_ns'] for r in near}
    events = []
    for m in freezes:
        prior = [c for c in cameras if c['monotonic_ns'] <= m['monotonic_ns']]
        events.append({'t': (m['monotonic_ns'] - first_ns) / 1e9,
                       'since_camera_s': (m['monotonic_ns'] - prior[-1]['monotonic_ns']) / 1e9 if prior else None,
                       'pre': group(around(rows, m, -3, -1), kind, ids),
                       'near': group(around(rows, m, -half, half), kind, ids),
                       'post': group(around(rows, m, 1, 3), kind, ids)})
    return {'marker_counts': dict(Counter(m['event'] for m in markers)),
            'near': group(near, kind, ids),
            'unmarked': group([r for r in rows if r['monotonic_ns'] not in near_times], kind, ids),
            'events': events,
            'sensitivity': {str(w): group(selected(w), kind, ids) for w in (.5, 1., 2.)},
            'cameras': [{'t': (m['monotonic_ns'] - first_ns) / 1e9,
                         'pre': group(around(rows, m, -2, 0), kind, ids),
                         'post': group(around(rows, m, 0, 2), kind, ids)} for m in cameras]}


def analyze(wait_dir, telemetry_dir, marker_path):
    wait_dir, telemetry_dir = Path(wait_dir), Path(telemetry_dir)
    wm, tm = load(wait_dir / 'metadata.json'), load(telemetry_dir / 'metadata.json')
    if wm.get('schema') != 1 or tm.get('schema') != 1 or wm.get('tool') != 'thread_wait_sampler':
        raise ValueError('Unsupported recording schema/tool')
    raw = load(wait_dir / 'thread-waits.jsonl', True)
    if not raw or raw[-1].get('kind') != 'end' or any(x.get('kind') != 'sample' for x in raw[:-1]):
        raise ValueError('Expected samples and exactly one final end record')
    waits, footer = raw[:-1], raw[-1]
    if footer['samples'] != len(waits) or footer.get('detail') is not None:
        raise ValueError('Footer sample count/error disagreement')
    if footer['monotonic_ns'] < waits[-1]['monotonic_ns'] or utc(footer) < utc(waits[-1]):
        raise ValueError('End timestamp precedes samples')
    missing = sum(t['wchan']['status'] != 'symbol' for r in waits for t in r['threads'])
    if footer['unavailable_wchan_observations'] != missing:
        raise ValueError('Footer wait-channel count disagreement')
    tele = load(telemetry_dir / 'telemetry.jsonl', True)
    markers = load(marker_path, True)
    ids = dict([wm['guest'], wm['gpu']])
    if len(ids) != 2 or tm['pids'] != [wm['pid']]:
        raise ValueError('Process/TID metadata disagreement')
    for row in waits:
        if set(thread_map(row, 'wait')) != set(ids):
            raise ValueError('Wait snapshot TIDs disagree with metadata')
        for tid in ids:
            if thread_map(row, 'wait')[tid]['name'] != wm['names'][str(tid)]:
                raise ValueError('Wait thread name disagrees with metadata')
        if row['read_end_monotonic_ns'] < row['monotonic_ns']:
            raise ValueError('Negative read span')
    for row in tele:
        if len(row['processes']) != 1:
            raise ValueError('Expected one process')
        if len(row['gpus']) != 1:
            raise ValueError('Expected one GPU; multi-device analysis unsupported')
        p = row['processes'][0]
        if p['pid'] != wm['pid'] or p['errors'] or p['process']['start_ticks'] != wm['process_start_ticks']:
            raise ValueError('Telemetry process identity/error disagreement')
    result = {'schema': 1, 'wait': {}, 'telemetry': {},
              'identity': {'pid': wm['pid'], 'process_start_ticks': wm['process_start_ticks'],
                           'selected_start_ticks': ids}}
    for name, samples, meta in [('wait', waits, wm), ('telemetry', tele, tm)]:
        result[name]['validation'] = times(samples)
        validation = result[name]['validation']
        validation['requested_duration_seconds'] = meta.get('requested_duration_seconds')
        validation['requested_interval_seconds'] = meta.get('interval_seconds')
        if meta.get('interval_seconds') is not None:
            interval = meta['interval_seconds']
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError('Invalid requested interval')
            validation['gaps_over_1_5x_interval'] = sum(
                b['monotonic_ns'] - a['monotonic_ns'] > 1.5 * interval * 1e9
                for a, b in zip(samples, samples[1:]))
        filtered = markers_in(markers, samples)
        rates = intervals(samples, name, ids, meta['clock_ticks_per_second'])
        result[name]['all'] = group(rates, name, ids)
        result[name]['events'] = event_analysis(rates, name, ids, filtered, samples[0]['monotonic_ns'])
        result[name]['bins_10s'] = [group([r for r in rates if start <=
                    (r['monotonic_ns'] - samples[0]['monotonic_ns']) / 1e9 < start + 10], name, ids)
                    for start in range(0, math.ceil(result[name]['validation']['span_seconds']), 10)]
        result[name]['snapshot_states'] = {tid: dict(Counter(thread_map(r, name)[tid]['state'] for r in samples))
                                           for tid in ids}
    result['wait']['footer'] = {k: footer[k] for k in ('reason', 'samples', 'unavailable_wchan_observations')}
    result['separation_seconds'] = (tele[0]['monotonic_ns'] - waits[-1]['monotonic_ns']) / 1e9
    result['overlap_seconds'] = max(0, (min(waits[-1]['monotonic_ns'], tele[-1]['monotonic_ns']) -
                                       max(waits[0]['monotonic_ns'], tele[0]['monotonic_ns'])) / 1e9)
    result['source_files'] = [{'name': p.name, 'bytes': p.stat().st_size,
                              'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                             for p in [wait_dir / 'metadata.json', wait_dir / 'thread-waits.jsonl',
                                       telemetry_dir / 'metadata.json', telemetry_dir / 'telemetry.jsonl', Path(marker_path)]]
    result['markers_total'] = len(markers)
    result['note'] = ('CPU percent is one logical core; process/thread values overlap. '
                      'Windows use interval-ending timestamps; unmarked is not proven smooth. '
                      'Recordings are analyzed separately, with no cross-record event alignment.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-dir', type=Path, required=True)
    parser.add_argument('--telemetry-dir', type=Path, required=True)
    parser.add_argument('--markers', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(analyze(args.wait_dir, args.telemetry_dir, args.markers), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        parser.exit(2, f'Invalid/incomplete recording: {exc}\n')


if __name__ == '__main__':
    main()
