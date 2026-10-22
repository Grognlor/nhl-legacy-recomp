#!/usr/bin/env python3
"""Bounded read-only thread discovery/wait snapshots. No attach, signals or memory reads."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from ally_profiler import new_run, parse_stat, write_json

MAX_THREADS = 512
MAX_SAMPLES = 6000
MAX_BYTES = 8 * 1024 * 1024
MAX_LINE = 16 * 1024


class Clock:
    monotonic_ns = staticmethod(time.monotonic_ns)
    sleep = staticmethod(time.sleep)

    @staticmethod
    def utc():
        return datetime.now(timezone.utc).isoformat()


def stamp(clock):
    return {'monotonic_ns': clock.monotonic_ns(), 'utc': clock.utc()}


class IdentityError(ValueError):
    """Refuse to follow a vanished/reused process or selected thread."""


class Proc:
    def __init__(self, root=Path('/proc')):
        self.root = Path(root)  # Injectable only through Python tests, never the CLI.

    @staticmethod
    def text(path, limit=65536):
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('proc field exceeds read limit')
        return data.decode('utf-8', errors='replace').strip()

    def stat(self, pid, tid=None):
        base = self.root / str(pid)
        if tid is not None:
            base = base / 'task' / str(tid)
        raw = self.text(base / 'stat')
        expected = pid if tid is None else tid
        if int(raw.split(' ', 1)[0]) != expected:
            raise IdentityError('stat PID/TID mismatch')
        result = parse_stat(raw)
        if len(result['name']) > 128 or result['start_ticks'] < 0 or result['ticks'] < 0:
            raise ValueError('Invalid stat values')
        return result

    def validate(self, pid, process_start):
        try:
            result = self.stat(pid)
        except OSError as exc:
            raise IdentityError(f'Process unavailable: {type(exc).__name__}') from exc
        if result['start_ticks'] != process_start or result['state'] in ('Z', 'X', 'x'):
            raise IdentityError('Process identity changed or process terminated')
        return result

    def selected(self, pid, tid, start):
        try:
            result = self.stat(pid, tid)
        except OSError as exc:
            raise IdentityError(f'Selected TID {tid} unavailable: {type(exc).__name__}') from exc
        if result['start_ticks'] != start or result['state'] in ('Z', 'X', 'x'):
            raise IdentityError(f'Selected TID {tid} identity changed or terminated')
        return result

    def task_ids(self, pid):
        tids = []
        for path in (self.root / str(pid) / 'task').iterdir():
            if path.name.isdigit():
                tids.append(int(path.name))
                if len(tids) > MAX_THREADS:
                    raise ValueError('Thread discovery limit exceeded; refusing partial selection')
        return sorted(tids)

    def boot(self):
        try:
            return {'value': self.text(self.root / 'sys/kernel/random/boot_id', 128), 'error': None}
        except (OSError, ValueError) as exc:
            return {'value': None, 'error': type(exc).__name__}

    def snapshot(self, pid, tid, start):
        result = self.selected(pid, tid, start)
        result['tid'] = tid
        base = self.root / str(pid) / 'task' / str(tid)
        try:
            raw = self.text(base / 'wchan', 256)
            if raw in ('', '0', '-') or re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]+', raw):
                status = 'unavailable_or_not_exposed'
            else:
                status = 'symbol'
            result['wchan'] = {'raw': raw, 'value': raw if status == 'symbol' else None,
                               'status': status, 'error': None}
        except (OSError, ValueError) as exc:
            result['wchan'] = {'raw': None, 'value': None,
                               'status': 'restricted' if isinstance(exc, PermissionError) else 'unavailable',
                               'error': type(exc).__name__}
        result['context_switches'] = {'voluntary_ctxt_switches': None,
                                      'nonvoluntary_ctxt_switches': None}
        result['status_error'] = None
        try:
            for line in self.text(base / 'status').splitlines():
                key, sep, value = line.partition(':')
                if sep and key in result['context_switches']:
                    count = int(value.strip())
                    if count < 0:
                        raise ValueError('negative counter')
                    result['context_switches'][key] = count
            if None in result['context_switches'].values():
                result['status_error'] = 'Missing context-switch counter'
        except (OSError, ValueError) as exc:
            result['context_switches'] = dict.fromkeys(result['context_switches'])
            result['status_error'] = type(exc).__name__
        self.selected(pid, tid, start)  # Detect disappearance/reuse during the reads.
        return result


def role(name):
    if name.startswith('XThread'):
        return 'guest'
    if name.startswith('GPU Commands'):
        return 'gpu'
    return None


def pick(candidates):
    """Select a clearly active leader; ties/zero/near-ties remain ambiguous."""
    ordered = sorted(candidates, key=lambda x: (-x['delta_ticks'], x['tid']))
    if not ordered or ordered[0]['delta_ticks'] <= 0:
        return None
    if len(ordered) > 1:
        margin = max(2, math.ceil(ordered[0]['delta_ticks'] * .1))
        if ordered[0]['delta_ticks'] - ordered[1]['delta_ticks'] < margin:
            return None
    return ordered[0]


def discover(pid, duration=2., interval=.2, proc=None, clock=None):
    proc, clock = proc or Proc(), clock or Clock()
    if pid <= 0 or not .2 <= duration <= 10 or not .1 <= interval <= duration:
        raise ValueError('Discovery requires PID>0, duration 0.2..10s and interval 0.1..duration')
    process = proc.stat(pid)
    process_start = process['start_ticks']
    proc.validate(pid, process_start)
    begin = stamp(clock)
    initial = {}
    for tid in proc.task_ids(pid):
        t = proc.stat(pid, tid)
        if role(t['name']):
            initial[tid] = t
    if not initial:
        raise ValueError('No named guest/GPU candidates')
    deadline = begin['monotonic_ns'] + int(duration * 1e9)
    current = initial
    # Check the full candidate set throughout; do not silently rank only survivors.
    while clock.monotonic_ns() < deadline:
        clock.sleep(max(0, min(interval, (deadline - clock.monotonic_ns()) / 1e9)))
        proc.validate(pid, process_start)
        current = {}
        for tid in proc.task_ids(pid):
            t = proc.stat(pid, tid)
            if role(t['name']):
                current[tid] = t
        if set(current) != set(initial):
            raise IdentityError('Candidate set changed; repeat discovery after thread churn')
        for tid, t in current.items():
            if (t['start_ticks'], t['name']) != (initial[tid]['start_ticks'], initial[tid]['name']):
                raise IdentityError('Candidate identity/name changed during discovery')
            if t['ticks'] < initial[tid]['ticks']:
                raise IdentityError('Candidate CPU counter decreased')
    proc.validate(pid, process_start)
    end = stamp(clock)
    elapsed = (end['monotonic_ns'] - begin['monotonic_ns']) / 1e9
    hz = os.sysconf('SC_CLK_TCK')
    candidates = [{'tid': tid, 'start_ticks': t['start_ticks'], 'name': t['name'],
                   'role': role(t['name']), 'delta_ticks': t['ticks'] - initial[tid]['ticks'],
                   'cpu_percent_one_core': 100 * (t['ticks'] - initial[tid]['ticks']) / hz / elapsed}
                  for tid, t in current.items()]
    chosen = {r: pick([t for t in candidates if t['role'] == r]) for r in ('guest', 'gpu')}
    return {'schema': 1, 'kind': 'discovery', 'pid': pid, 'process_start_ticks': process_start,
            'begin': begin, 'end': end, 'boot_id': proc.boot(), 'clock_ticks_per_second': hz,
            'candidates': candidates, 'selected': chosen,
            'ambiguous': any(v is None for v in chosen.values()),
            'note': 'Activity ranking only; not an NHL function identity. Review and explicitly confirm TIDs.'}


class BoundedWriter:
    def __init__(self, stream, limit=MAX_BYTES):
        self.stream, self.limit, self.bytes = stream, limit, 0

    def write(self, record, final=False):
        data = (json.dumps(record, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()
        reserve = 0 if final else MAX_LINE
        if len(data) > MAX_LINE or self.bytes + len(data) > self.limit - reserve:
            return False
        self.stream.write(data)
        self.stream.flush()
        self.bytes += len(data)
        return True


def collect(pid, process_start, guest, gpu, duration=60., interval=.2,
            confirmed=False, proc=None, clock=None, base=None, byte_limit=MAX_BYTES):
    if not confirmed:
        raise ValueError('Explicit --confirm-tids is required after reviewing discovery')
    if (pid <= 0 or process_start < 0 or guest[0] == gpu[0] or
            any(tid <= 0 or start < 0 for tid, start in (guest, gpu)) or
            not math.isfinite(duration) or not .1 <= duration <= 600 or
            not math.isfinite(interval) or not .1 <= interval <= 10):
        raise ValueError('Invalid identities or capture limits: duration 0.1..600s, interval 0.1..10s')
    proc, clock = proc or Proc(), clock or Clock()
    proc.validate(pid, process_start)
    expected_names = {}
    for r, (tid, start) in [('guest', guest), ('gpu', gpu)]:
        t = proc.selected(pid, tid, start)
        if role(t['name']) != r:
            raise ValueError(f'Confirmed {r} TID name does not match its role')
        expected_names[tid] = t['name']
    proc.validate(pid, process_start)
    run = new_run(base)
    write_json(run / 'metadata.json', {'schema': 1, 'tool': 'thread_wait_sampler', 'pid': pid,
               'process_start_ticks': process_start, 'guest': list(guest), 'gpu': list(gpu),
               'names': expected_names, 'boot_id': proc.boot(), 'clock': 'time.monotonic_ns / CLOCK_MONOTONIC',
               'clock_info': {'implementation': time.get_clock_info('monotonic').implementation,
                              'resolution_seconds': time.get_clock_info('monotonic').resolution},
               'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
               'interval_seconds': interval, 'requested_duration_seconds': duration,
               'max_samples': MAX_SAMPLES, 'max_jsonl_bytes': byte_limit,
               'max_record_bytes': MAX_LINE, 'note': 'No attach, signals, memory reads or target writes.'})
    start_ns = clock.monotonic_ns()
    end_ns = start_ns + int(duration * 1e9)
    next_ns = start_ns
    count, unavailable = 0, 0
    previous_ticks = {}
    reason, detail = 'duration', None
    with (run / 'thread-waits.jsonl').open('xb') as stream:
        writer = BoundedWriter(stream, byte_limit)
        try:
            while clock.monotonic_ns() < end_ns:
                if count >= MAX_SAMPLES:
                    reason = 'sample_limit'
                    break
                event = {'kind': 'sample', **stamp(clock)}
                proc.validate(pid, process_start)
                rows = []
                for tid, ticks in (guest, gpu):
                    t = proc.snapshot(pid, tid, ticks)
                    if t['name'] != expected_names[tid]:
                        raise IdentityError('Selected thread name changed; repeat discovery')
                    if t['ticks'] < previous_ticks.get(tid, t['ticks']):
                        raise IdentityError('Selected thread CPU counter decreased')
                    rows.append(t)
                proc.validate(pid, process_start)  # Reject mixed-process snapshots.
                event['threads'] = rows
                event['read_end_monotonic_ns'] = clock.monotonic_ns()
                event['collection_seconds'] = (event['read_end_monotonic_ns'] - event['monotonic_ns']) / 1e9
                if not writer.write(event):
                    reason = 'output_limit'
                    break
                count += 1
                previous_ticks = {t['tid']: t['ticks'] for t in rows}
                unavailable += sum(t['wchan']['status'] != 'symbol' for t in rows)
                next_ns += int(interval * 1e9)
                now = clock.monotonic_ns()
                if next_ns <= now:
                    next_ns = now + int(interval * 1e9)  # No catch-up burst.
                clock.sleep(max(0, (min(next_ns, end_ns) - now) / 1e9))
        except KeyboardInterrupt:
            reason = 'interrupted'
        except (OSError, ValueError, IndexError) as exc:
            reason, detail = 'target_or_read_error', f'{type(exc).__name__}: {exc}'[:512]
        footer = {'kind': 'end', **stamp(clock), 'reason': reason, 'detail': detail,
                  'samples': count, 'unavailable_wchan_observations': unavailable}
        if not writer.write(footer, final=True):
            raise ValueError('Output budget too small for end record')
    return run, footer


def identity(text):
    try:
        tid, start = map(int, text.split(':'))
        if tid <= 0 or start < 0:
            raise ValueError()
        return tid, start
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Expected positive TID:nonnegative_start_ticks') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    d = commands.add_parser('discover', help='Bounded read-only activity ranking; never starts a capture')
    d.add_argument('--pid', type=int, required=True)
    d.add_argument('--duration', type=float, default=2.)
    d.add_argument('--interval', type=float, default=.2)
    c = commands.add_parser('collect', help='Collect only explicitly confirmed thread identities')
    c.add_argument('--pid', type=int, required=True)
    c.add_argument('--process-start', type=int, required=True)
    c.add_argument('--guest', type=identity, required=True, metavar='TID:START')
    c.add_argument('--gpu', type=identity, required=True, metavar='TID:START')
    c.add_argument('--confirm-tids', action='store_true')
    c.add_argument('--duration', type=float, default=60.)
    c.add_argument('--interval', type=float, default=.2)
    args = parser.parse_args()
    try:
        if args.command == 'discover':
            result = discover(args.pid, args.duration, args.interval)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 2 if result['ambiguous'] else 0
        run, footer = collect(args.pid, args.process_start, args.guest, args.gpu,
                              args.duration, args.interval, args.confirm_tids)
        print(f'Wait-state output: {run}\nStop reason: {footer["reason"]}; samples: {footer["samples"]}')
        if footer['unavailable_wchan_observations']:
            print('Some wait channels were unavailable/hidden; never retry as root.', file=sys.stderr)
        return 0 if footer['reason'] == 'duration' else 2
    except KeyboardInterrupt:
        parser.exit(130, 'Stopped; no target signal sent.\n')
    except (OSError, ValueError, IndexError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    sys.exit(main())
