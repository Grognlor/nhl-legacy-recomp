#!/usr/bin/env python3
"""Offline MangoHud 0.8.4 / ally-profiler analysis. No launch or live reads.

Elapsed is explicitly ns, frametime explicitly ms. Filename-derived alignment
must be supplied as an interval; it is never inferred as exact synchronization.
Outputs are exclusive aggregate artifacts in reports/artifacts/011 only.
"""
import argparse
import csv
import hashlib
import json
import math
import statistics as st
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def percentile(values, p):
    a = sorted(values)
    if not a:
        return None
    i = (len(a) - 1) * p / 100
    j = int(i)
    return a[j] + (a[min(j + 1, len(a) - 1)] - a[j]) * (i - j)


def describe(a):
    a = [x for x in a if x is not None and math.isfinite(x)]
    return dict(n=len(a), mean=st.mean(a) if a else None,
                min=min(a) if a else None, median=st.median(a) if a else None,
                max=max(a) if a else None)


def read_frames(path):
    result, header = [], None
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        for line, row in enumerate(csv.reader(stream), 1):
            if not any(x.strip() for x in row):
                continue
            names = [x.strip().lower() for x in row]
            if 'frametime' in names:
                if header is not None or len(set(names)) != len(names):
                    raise ValueError('Repeated or duplicate header')
                if 'elapsed' not in names:
                    raise ValueError('elapsed ns required')
                header = names
                continue
            if header is None:
                continue
            if len(row) != len(header):
                raise ValueError(f'Column count at line {line}')
            d = dict(zip(header, map(float, row)))
            if not all(math.isfinite(x) for x in d.values()):
                raise ValueError(f'Nonfinite value at line {line}')
            if d['frametime'] <= 0 or d['elapsed'] < 0:
                raise ValueError(f'Invalid interval at line {line}')
            d['t'] = d['elapsed'] / 1e9
            if result and d['t'] <= result[-1]['t']:
                raise ValueError('Nonincreasing elapsed')
            result.append(d)
    if not result:
        raise ValueError('No frame data')
    return result


def frame_stats(rows):
    f = [r['frametime'] for r in rows]
    total = math.fsum(f)
    return dict(n=len(f), sum_seconds=total / 1000,
                duration_fps=1000 * len(f) / total if total else None,
                mean_ms=st.mean(f) if f else None,
                **{f'p{p}_ms': percentile(f, p) for p in (50, 90, 95, 99)},
                min_ms=min(f) if f else None, max_ms=max(f) if f else None,
                **{f'over_{x}': sum(v > x for v in f) for x in (16.67, 33.33, 50, 100)},
                under_5=sum(v < 5 for v in f))


def cadence(rows):
    residual = [(b['t'] - a['t']) * 1000 - b['frametime']
                for a, b in zip(rows, rows[1:])]
    return dict(first_elapsed_s=rows[0]['t'], last_elapsed_s=rows[-1]['t'],
                elapsed_span_s=rows[-1]['t'] - rows[0]['t'],
                residual_ms=describe(residual),
                p99_abs_residual_ms=percentile([abs(x) for x in residual], 99),
                interval_sum_minus_elapsed_s=math.fsum(r['frametime'] for r in rows[1:]) / 1000
                - (rows[-1]['t'] - rows[0]['t']))


def windows(rows, width, step=1):
    end = math.floor(rows[-1]['t'])
    return [dict(start_s=t, end_s=t + width,
                 **frame_stats([r for r in rows if t <= r['t'] < t + width]))
            for t in range(1, end - width + 1, step)]


def runs(rows, threshold):
    result, group = [], []
    for r in rows + [dict(frametime=0)]:
        if r['frametime'] > threshold:
            group.append(r)
        elif group:
            result.append(dict(n=len(group), start_s=group[0]['t'] - group[0]['frametime'] / 1000,
                               end_s=group[-1]['t'], sum_ms=math.fsum(x['frametime'] for x in group)))
            group = []
    return sorted(result, key=lambda d: d['sum_ms'], reverse=True)


def clusters(rows, threshold, gap=1):
    groups = []
    for r in rows:
        if r['frametime'] <= threshold:
            continue
        if not groups or r['t'] - groups[-1][-1]['t'] > gap:
            groups.append([])
        groups[-1].append(r)
    return sorted([dict(n=len(g), start_s=g[0]['t'], end_s=g[-1]['t'],
                        span_s=g[-1]['t'] - g[0]['t']) for g in groups],
                  key=lambda d: d['n'], reverse=True)


def sensor(sample, unit, label, suffix):
    matches = []
    for g in sample['gpus']:
        for s in g['sensors'].values():
            if s.get('unit') == unit and (s.get('label') or {}).get('value') == label and s['path'].endswith(suffix):
                if s.get('error') is None and s.get('value') is not None:
                    matches.append(s['value'])
    return matches[0] if len(matches) == 1 else None


def telemetry_rows(samples):
    output = []
    for s in samples:
        if len(s['processes']) != 1:
            raise ValueError('Exactly one selected process required')
        p = s['processes'][0]
        proc = p.get('process') or {}
        output.append(dict(t=s['elapsed_seconds'], utc=s['utc'],
                           mono=s['monotonic_ns'], cpu=proc.get('cpu_percent_one_core'),
                           process=proc, threads=p['threads'], errors=p['errors'],
                           collection=s['collection_seconds'],
                           sclk=sensor(s, 'MHz', 'sclk', 'freq1_input'),
                           temp=sensor(s, 'C', 'edge', 'temp1_input'),
                           slowPPT_average=sensor(s, 'W', 'slowPPT', 'power1_average'),
                           slowPPT_input=sensor(s, 'W', 'slowPPT', 'power1_input')))
    return output


def thread_stats(samples):
    groups = defaultdict(list)
    for s in samples:
        for t in s['threads']:
            groups[(t['id'], t.get('start_ticks'), t.get('name'))].append((s['t'], t))
    out = []
    for (tid, start, name), rows in groups.items():
        span = rows[-1][0] - rows[0][0]
        switches = {}
        for key in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches'):
            a = rows[0][1].get('context_switches', {}).get(key)
            b = rows[-1][1].get('context_switches', {}).get(key)
            switches[key + '_per_s'] = (b - a) / span if a is not None and b is not None and b >= a and span else None
        out.append(dict(tid=tid, start_ticks=start, name=name, samples=len(rows),
                        cpu=describe([t.get('cpu_percent_one_core') for _, t in rows]),
                        observed_running=sum(t.get('state') == 'R' for _, t in rows), **switches))
    return sorted(out, key=lambda d: d['cpu']['mean'] or 0, reverse=True)


def pearson(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    x, y = zip(*pairs)
    mx, my = st.mean(x), st.mean(y)
    den = math.sqrt(sum((v-mx)**2 for v in x) * sum((v-my)**2 for v in y))
    return sum((u-mx)*(v-my) for u,v in pairs)/den if den else None


def aligned_bins(frames, telemetry, offset, width=5):
    out = []
    for start in range(5, 116, width):
        end = start + width
        f = [r for r in frames if start <= r['t'] < end]
        s = [r for r in telemetry if start + offset <= r['t'] < end + offset]
        if f and s:
            out.append(dict(start_s=start, end_s=end, **frame_stats(f),
                            **{k: describe([r[k] for r in s])['mean'] for k in ('cpu','sclk','temp','slowPPT_average','slowPPT_input')}))
    return out


def analyze(frames, telemetry, offsets):
    bins = {str(o): aligned_bins(frames, telemetry, o) for o in offsets}
    return dict(frames=frame_stats(frames), cadence=cadence(frames),
                rolling={str(w): windows(frames, w) for w in (1,5,10)},
                consecutive={str(t):runs(frames,t)[:10] for t in (16.67,33.33,50)},
                clusters_over_33ms_gap_1s=clusters(frames,33.33),
                telemetry={k:describe([r[k] for r in telemetry]) for k in ('cpu','sclk','temp','slowPPT_average','slowPPT_input','collection')},
                threads=thread_stats(telemetry), aligned_5s_bins=bins,
                alignment_sensitivity={o:{k:pearson([r['mean_ms'] for r in b],[r[k] for r in b])
                    for k in ('cpu','sclk','temp','slowPPT_average','slowPPT_input')} for o,b in bins.items()})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=Path, required=True)
    p.add_argument('--comparison', type=Path, required=True)
    p.add_argument('--telemetry', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--summary', type=Path, required=True)
    p.add_argument('--offset-min', type=float, required=True)
    p.add_argument('--offset-max', type=float, required=True)
    a = p.parse_args()
    if not all(math.isfinite(v) for v in (a.offset_min, a.offset_max)) or a.offset_min > a.offset_max:
        p.error('offset-min must not exceed offset-max')
    fs, earlier = read_frames(a.frames), read_frames(a.comparison)
    raw = [json.loads(line) for line in a.telemetry.open()]
    ts = telemetry_rows(raw)
    offsets = [a.offset_min,(a.offset_min+a.offset_max)/2,a.offset_max]
    result = analyze(fs, ts, offsets)
    result['phases_assumed_midpoint'] = {f'{lo}-{hi}': dict(
        threads=thread_stats([s for s in ts if lo + offsets[1] <= s['t'] < hi + offsets[1]]),
        **{k:describe([s[k] for s in ts if lo + offsets[1] <= s['t'] < hi + offsets[1]])
           for k in ('cpu','sclk','temp','slowPPT_average','slowPPT_input')})
        for lo,hi in [(17,22),(40,50),(57,65)]}
    result['fixed_10s_frames'] = [dict(start_s=t,end_s=t+10,
        **frame_stats([r for r in fs if t <= r['t'] < t+10])) for t in range(0,120,10)]
    result['zero_slowPPT_average_elapsed_s'] = [s['t'] for s in ts if s['slowPPT_average'] == 0]
    result['comparison'] = dict(frames=frame_stats(earlier),cadence=cadence(earlier))
    result['metadata'] = json.loads(a.metadata.read_text())
    result['input_identity'] = {p.name:dict(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                                for p in (a.frames,a.comparison,a.telemetry,a.metadata,a.summary)}
    result['telemetry_clock'] = dict(first_utc=ts[0]['utc'],last_utc=ts[-1]['utc'],n=len(ts),
        first_monotonic_ns=ts[0]['mono'],last_monotonic_ns=ts[-1]['mono'],
        utc_minus_monotonic_span_s=(datetime.fromisoformat(ts[-1]['utc'])-datetime.fromisoformat(ts[0]['utc'])).total_seconds()-(ts[-1]['mono']-ts[0]['mono'])/1e9,
        max_interval_s=max(b['t']-a['t'] for a,b in zip(ts,ts[1:])),
        process_identities=sorted(set((s['process'].get('id'),s['process'].get('start_ticks')) for s in ts)),
        process_error_samples=sum(bool(s['errors']) for s in ts))
    result['gpu_utilization'] = dict(samples=len(raw),invalid=sum(s['gpus'][0]['sensors']['utilization']['error'] is not None for s in raw))
    out = Path(__file__).resolve().parents[2]/'reports/artifacts/011'
    root = Path(__file__).resolve().parents[2]
    if out.resolve() != out or not out.is_relative_to(root):
        raise ValueError('Artifact directory must not contain symlinks')
    out.mkdir(parents=True, exist_ok=True)
    with (out/'analysis.json').open('x') as f:
        json.dump(result,f,indent=2,allow_nan=False)
        f.write('\n')
    for name, rows in [('rolling_1s',result['rolling']['1']),('rolling_10s',result['rolling']['10']),
                       ('aligned_5s_assumed_midpoint',bins_mid(result, offsets[1]))]:
        with (out/(name+'.csv')).open('x',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    print(out)


def bins_mid(result, midpoint):
    return result['aligned_5s_bins'][str(midpoint)]


if __name__ == '__main__':
    main()
