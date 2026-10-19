#!/usr/bin/env python3
"""Read-only numeric telemetry and explicit-provenance MangoHud analysis. Python 3.9+."""
import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
import unittest

def default_output_base():
    # HOME is the trusted boundary; Bazzite legitimately aliases /home to /var/home.
    # Resolve only that root, never the dedicated output directory beneath it.
    home = Path.home()
    if not home.is_absolute() or '..' in home.parts:
        raise ValueError('Home directory must be absolute and contain no traversal')
    root = home.resolve(strict=True)
    if not root.is_dir() or root == root.parent:
        raise ValueError('Home directory must resolve to a non-root directory')
    return root / 'nhl-ally-profiles'


def reading(path, scale=1.0, unit=None):
    result = {'path': str(path), 'value': None, 'unit': unit, 'error': None}
    try:
        value = float(path.read_text().strip()) * scale
        if not math.isfinite(value):
            raise ValueError('non-finite reading')
        result['value'] = value
    except (OSError, ValueError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
    return result


def label(path):
    try:
        return {'value': path.read_text().strip(), 'error': None}
    except OSError as exc:
        return {'value': None, 'error': f'{type(exc).__name__}: {exc}'}


def gpu_sample(device):
    out = {'device': str(device), 'sensors': {}, 'errors': []}
    specs = [('utilization', device / 'gpu_busy_percent', 1, '%')]
    try:
        hwmons = list((device / 'hwmon').glob('hwmon*'))
        if not hwmons:
            out['errors'].append('No hwmon directories available')
        for hw in hwmons:
            for pattern, scale, unit in [('temp*_input', .001, 'C'),
                                         ('freq*_input', 1e-6, 'MHz'),
                                         ('power*_average', 1e-6, 'W'),
                                         ('power*_input', 1e-6, 'W')]:
                for path in hw.glob(pattern):
                    specs.append((f'{hw.name}/{path.name}', path, scale, unit))
    except OSError as exc:
        out['errors'].append(str(exc))
    for name, path, scale, unit in specs:
        item = reading(path, scale, unit)
        prefix = path.name.split('_')[0]
        item['label'] = label(path.parent / f'{prefix}_label') if name != 'utilization' else None
        out['sensors'][name] = item
    for clock in ('sclk', 'mclk'):
        path = device / f'pp_dpm_{clock}'
        item = {'path': str(path), 'value': None, 'unit': 'MHz',
                'kind': 'active_dpm_state_not_instantaneous_clock', 'error': None}
        try:
            active = [line for line in path.read_text().splitlines() if '*' in line]
            values = [re.search(r'([\d.]+)\s*([GMK]?Hz)', x, re.I) for x in active]
            if len(values) != 1 or values[0] is None:
                raise ValueError('Expected exactly one active DPM clock with units')
            match = values[0]
            factor = {'mhz': 1, 'ghz': 1000, 'khz': .001, 'hz': .000001}[match[2].lower()]
            item['value'] = float(match[1]) * factor
            item['raw_active_state'] = active[0].strip()
        except (OSError, ValueError, KeyError) as exc:
            item['error'] = f'{type(exc).__name__}: {exc}'
        out['sensors'][f'dpm_{clock}'] = item
    if not any(x['unit'] == 'W' for x in out['sensors'].values()):
        out['errors'].append('No power sensors discovered; power is unavailable')
    if not any(x['unit'] == 'C' for x in out['sensors'].values()):
        out['errors'].append('No temperature sensors discovered; temperature is unavailable')
    return out


def discover(drm):
    devices, errors = [], []
    try:
        for card in sorted(drm.glob('card*')):
            if not re.fullmatch(r'card\d+', card.name):
                continue
            device = card / 'device'
            try:
                if (device / 'driver').resolve(strict=True).name == 'amdgpu':
                    devices.append(device)
            except OSError as exc:
                errors.append(f'{device}: {exc}')
    except OSError as exc:
        errors.append(str(exc))
    if not devices:
        errors.append('No AMD GPU discovered; GPU telemetry unavailable')
    return devices, errors


def parse_stat(text):
    # comm can contain spaces and parentheses. Fields after final ')' start at #3.
    end = text.rindex(')')
    fields = text[end + 1:].split()
    return {'name': text[text.index('(') + 1:end], 'state': fields[0],
            'ticks': int(fields[11]) + int(fields[12]), 'start_ticks': int(fields[19])}


class ProcSampler:
    def __init__(self, root=Path('/proc'), hz=None):
        self.root = root
        self.hz = hz if hz is not None else os.sysconf('SC_CLK_TCK')
        self.previous = {}
        self.identities = {}

    def sample(self, pid, now):
        base = self.root / str(pid)
        result = {'pid': pid, 'process': None, 'threads': [], 'errors': []}
        try:
            process = parse_stat((base / 'stat').read_text())
            identity = process['start_ticks']
            if pid in self.identities and self.identities[pid] != identity:
                result['errors'].append('PID reused: refusing to follow replacement process')
                return result
            self.identities[pid] = identity
            paths = [(base, 'process')]
            try:
                paths += [(p, 'thread') for p in (base / 'task').iterdir() if p.name.isdigit()]
            except OSError as exc:
                result['errors'].append(f'Thread enumeration: {exc}')
            current = set()
            for path, kind in paths:
                try:
                    stat = parse_stat((path / 'stat').read_text())
                    if kind == 'process' and stat['start_ticks'] != identity:
                        raise ValueError('Process identity changed during sample')
                    key = (pid, kind, int(path.name), stat['start_ticks'])
                    current.add(key)
                    old = self.previous.get(key)
                    stat['cpu_percent_one_core'] = None
                    if old and now > old[0] and stat['ticks'] >= old[1]:
                        stat['cpu_percent_one_core'] = 100 * (stat['ticks'] - old[1]) / self.hz / (now - old[0])
                    self.previous[key] = (now, stat['ticks'])
                    stat['id'] = int(path.name)
                    status = label(path / 'status')
                    stat['context_switches'] = {}
                    if status['error']:
                        stat['status_error'] = status['error']
                    else:
                        for line in status['value'].splitlines():
                            name, _, value = line.partition(':')
                            if name in ('voluntary_ctxt_switches', 'nonvoluntary_ctxt_switches'):
                                stat['context_switches'][name] = int(value.strip())
                    if kind == 'process':
                        result['process'] = stat
                    else:
                        result['threads'].append(stat)
                except (OSError, ValueError, IndexError) as exc:
                    result['errors'].append(f'{kind} {path.name}: {exc}')
            self.previous = {k: v for k, v in self.previous.items() if k[0] != pid or k in current}
        except (OSError, ValueError, IndexError) as exc:
            result['errors'].append(f'Process unavailable: {exc}')
        return result


def percentile(sorted_values, p):
    pos = (len(sorted_values) - 1) * p / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def analyze_csv(path, source, per_frame=False, unit=None, skip=0, take=None):
    frames, bad = [], []
    header = None
    total_rows = 0
    with path.open(newline='', encoding='utf-8-sig') as stream:
        for number, row in enumerate(csv.reader(stream), 1):
            names = [x.strip().lower() for x in row]
            if 'frametime' in names or 'frametime_ms' in names:
                if header is not None:
                    raise ValueError(f'Repeated header at line {number}; split concatenated logs')
                header = names
                if len(header) != len(set(header)):
                    raise ValueError('Duplicate column names')
                column = header.index('frametime_ms' if 'frametime_ms' in header else 'frametime')
                if 'frametime_ms' not in header and unit is None:
                    raise ValueError('Ambiguous frametime unit: supply --frametime-unit ms/us/ns/s')
                continue
            if header is None or not any(x.strip() for x in row):
                continue
            total_rows += 1
            if total_rows <= skip or (take is not None and total_rows > skip + take):
                continue
            try:
                if len(row) != len(header):
                    raise ValueError('column count mismatch')
                value = float(row[column])
                scale = 1 if header[column] == 'frametime_ms' else {'ms': 1, 'us': .001, 'ns': 1e-6, 's': 1000}[unit]
                value *= scale
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('frametime must be finite and positive')
                frames.append(value)
            except (ValueError, IndexError) as exc:
                bad.append({'line': number, 'error': str(exc)})
    if header is None:
        raise ValueError('No supported frametime header; FPS-only/summary logs are not per-frame data')
    if not frames:
        raise ValueError('No valid frame times in selected rows')
    ordered = sorted(frames)
    valid_per_frame = per_frame and not bad
    result = {'schema': 1, 'source': source, 'input': str(path),
              'per_frame_asserted_by_user': per_frame, 'rows_total': total_rows,
              'rows_selected_valid': len(frames), 'invalid_rows': bad,
              'mean_frametime_ms': statistics.mean(frames),
              'min_frametime_ms': min(frames), 'max_frametime_ms': max(frames),
              'sample_frametime_percentiles_ms': {f'p{p}': percentile(ordered, p) for p in (50, 90, 95, 99)},
              'percentile_method': 'linear interpolation, index=(n-1)*p/100',
              'fps_from_frame_durations': len(frames) * 1000 / math.fsum(frames) if valid_per_frame else None,
              'frame_duration_sum_seconds': math.fsum(frames) / 1000 if valid_per_frame else None,
              'thresholds': {str(t): {'count': sum(x > t for x in frames),
                                    'fraction': sum(x > t for x in frames) / len(frames)}
                             for t in (16.67, 33.33, 50, 100)},
              'warnings': ['No automatic time alignment with telemetry; CSV elapsed units/origin are not inferred.',
                           'Thresholds are descriptive, not a causal stutter diagnosis.']}
    if not per_frame:
        result['warnings'].append('Unverified sampling: sample distributions only; no gameplay FPS calculated.')
    if bad:
        result['warnings'].append('Invalid selected rows excluded; FPS suppressed to avoid claiming a complete frame stream.')
    return result


def new_run(base=None):
    # Fixed dedicated output boundary; no arbitrary installation paths accepted.
    base = default_output_base() if base is None else base.expanduser()
    if not base.is_absolute() or '..' in base.parts:
        raise ValueError('Output base must be absolute and contain no traversal')
    if base.is_symlink() or base.resolve() != base.absolute():
        raise ValueError('Output base must not contain symlinks')
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    import tempfile
    return Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=base))


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def collect(args):
    run = new_run()
    devices, errors = discover(Path('/sys/class/drm'))
    sampler = ProcSampler()
    write_json(run / 'metadata.json', {'schema': 1, 'session': args.session,
               'pids': args.pid, 'interval_seconds': args.interval, 'requested_duration_seconds': args.duration,
               'clock_ticks_per_second': sampler.hz, 'discovery_errors': errors,
               'cpu_scale': '100% = one logical core; process and thread totals overlap, never add them',
               'note': 'No game launch, memory reads, configuration changes, or automatic child discovery.'})
    print(f'Writing telemetry to {run}', flush=True)
    start = time.monotonic()
    deadline = start
    with (run / 'telemetry.jsonl').open('x') as stream:
        try:
            while time.monotonic() - start < args.duration:
                now = time.monotonic()
                sample = {'monotonic_ns': time.monotonic_ns(), 'utc': datetime.now(timezone.utc).isoformat(),
                          'elapsed_seconds': now - start,
                          'gpus': [gpu_sample(d) for d in devices],
                          'processes': [sampler.sample(pid, now) for pid in args.pid]}
                sample['collection_seconds'] = time.monotonic() - now
                stream.write(json.dumps(sample, allow_nan=False) + '\n')
                stream.flush()
                deadline += args.interval
                if deadline < time.monotonic():
                    deadline = time.monotonic()  # don't burst catch-up reads
                time.sleep(max(0, min(deadline, start + args.duration) - time.monotonic()))
        except KeyboardInterrupt:
            print('Stopped; partial telemetry preserved.', file=sys.stderr)
    return run


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be finite and positive')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('self-test', help='Synthetic fixtures only, no live telemetry')
    sub.add_parser('dry-run', help='Alias for synthetic self-test')
    collect_parser = sub.add_parser('collect', help='Observe existing PIDs; never launches a program')
    collect_parser.add_argument('--pid', type=int, action='append', required=True)
    collect_parser.add_argument('--session', choices=['desktop', 'gaming'], required=True)
    collect_parser.add_argument('--duration', type=positive, default=120)
    collect_parser.add_argument('--interval', type=positive, default=.5)
    analyze = sub.add_parser('analyze', help='Import MangoHud CSV; writes analysis under ~/nhl-ally-profiles')
    analyze.add_argument('csv', type=Path)
    analyze.add_argument('--source', choices=['mangohud-application', 'gamescope-mangoapp', 'synthetic'], required=True)
    analyze.add_argument('--per-frame', action='store_true', help='Assert verified one row per frame; not autodetected')
    analyze.add_argument('--frametime-unit', choices=['ms', 'us', 'ns', 's'])
    analyze.add_argument('--skip-rows', type=int, default=0)
    analyze.add_argument('--take-rows', type=int)
    args = parser.parse_args()
    if args.command in ('self-test', 'dry-run'):
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern='test_*.py')
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        if args.command == 'collect':
            if any(pid <= 0 for pid in args.pid) or args.interval < .1:
                raise ValueError('PIDs must be positive and interval at least 0.1 seconds')
            collect(args)
        else:
            if args.skip_rows < 0 or (args.take_rows is not None and args.take_rows < 1):
                raise ValueError('Invalid row selection')
            result = analyze_csv(args.csv, args.source, args.per_frame, args.frametime_unit,
                                 args.skip_rows, args.take_rows)
            run = new_run()
            write_json(run / 'summary.json', result)
            print(json.dumps(result, indent=2, allow_nan=False))
            print(f'Analysis saved: {run / "summary.json"}', file=sys.stderr)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Error: {exc}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
