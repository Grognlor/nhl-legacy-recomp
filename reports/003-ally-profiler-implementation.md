# 003 — Ally profiler implementation

## Objective and outcome

Implement a lightweight, read-only profiling harness for the ASUS ROG Ally Z2A on Bazzite Linux 44. Development/testing is in Desktop Mode; the eventual gameplay target is Steam Gaming Mode with Gamescope. Current game context remains Windows NHL Legacy Recomp v0.6.0 through Proton Experimental.

Read [report 001](001-initial-performance-investigation.md), [report 002](002-ally-profiling-and-linux-feasibility.md), and the [report index](README.md) before implementation. Starting branch: `perf/ally-investigation`; starting commit: `4faa76eb29c9c392d8e60cc27a251de4af796d96`. Date: 2026-10-19.

Implemented the independent standard-library Python tool in `tools/ally-profiler/`. It collects numeric GPU and process/thread statistics, analyzes explicit-provenance frame CSVs, and validates itself with synthetic fixtures. It never launches NHL, changes configuration, captures assets, reads process memory, or uploads data. **No real-game performance results are claimed.**

## Architecture and implementation

### Read-only telemetry collector

[`ally_profiler.py`](../tools/ally-profiler/ally_profiler.py) provides `collect`, `analyze`, `self-test`, and `dry-run` subcommands. Python 3.9+; no package dependencies.

- `discover()` enumerates DRM `cardN` devices and resolves their driver to select every `amdgpu` device. No hardcoded card number or implicit first-device choice.
- `gpu_sample()` reads `gpu_busy_percent`, hwmon temperature/frequency/power input and average nodes, and active `pp_dpm_sclk`/`pp_dpm_mclk` state lines. hwmon conversions are millidegrees to C, Hz to MHz, microwatts to W. DPM readings remain explicitly labelled active states, not instantaneous clocks.
- Each sensor retains its source path, unit, value/error and label/error. Missing, malformed, nonfinite and denied readings stay null with diagnostics. A missing label is not replaced with an invented sensor name. Absent power/temperature groups have explicit availability errors. Zero is valid only when actually read.
- `ProcSampler.sample()` reads only selected process/task stat/status files. It parses names containing spaces/parentheses, records state and cumulative context switches, and computes CPU rates from `utime+stime` deltas using `SC_CLK_TCK` and monotonic elapsed time. 100% means one logical core; process totals can exceed 100%. Thread totals overlap the process total.
- First observations have null CPU rates. Start ticks distinguish process/thread identity: replacement PIDs are refused; new/reused TIDs begin a new baseline. Disappearing or denied task files are reported rather than aborting the session. Counter regressions do not produce fabricated negative utilization.
- `collect()` accepts explicitly selected Linux PIDs; it never searches game files, reads process command lines/environments, follows descendants, or launches processes. Default duration is 120 s, interval 0.5 s; finite positive arguments are required, with a minimum interval of 0.1 s. Sampling does not burst to catch up after overruns. Collection duration per sample helps expose observer overhead.
- Each sample has UTC, host monotonic nanoseconds and elapsed seconds. Reads are sequential, not an atomic system snapshot. Ctrl-C preserves partial output.

### Output boundary

`new_run()` creates a unique private run directory under the fixed `~/nhl-ally-profiles/` base. There is no arbitrary output-path flag. Symlinked output bases/parents are rejected; output files use exclusive creation to avoid overwriting existing files. Keep this dedicated directory separate from any installation.

`metadata.json` records session provenance, PIDs, requested duration/interval, tick scale and discovery errors. `telemetry.jsonl` contains numeric samples, identities and errors. Analysis produces a separate `summary.json`. Synthetic tests use temporary fake trees, removed after testing. No game files or captures are copied.

### MangoHud CSV analysis

`analyze_csv()` accepts UTF-8/BOM CSVs, optional MangoHud version/system-info preambles, quoted fields and frame headers. Bare `frametime` requires an explicit `--frametime-unit ms/us/ns/s`; `frametime_ms` identifies its unit directly. The supported schema was checked against the public [MangoHud 0.8.4 logger](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/logging.cpp). That producer writes elapsed nanoseconds relative to logging start; the importer intentionally does not infer or merge time origins.

The caller must specify `--source mangohud-application`, `gamescope-mangoapp`, or `synthetic`. By default output is sample statistics and FPS is null. `--per-frame` is an explicit assertion that sampling has been independently verified; the parser cannot prove this from CSV alone.

For a complete valid per-frame stream, FPS is `1000 * count / sum(frame_ms)`. Frame-time p50/p90/p95/p99 use linear interpolation at `(n-1)*p/100`. Minimum, maximum and mean are included. Stutter-threshold summaries count intervals strictly above 16.67/33.33/50/100 ms and report their fraction of valid rows, not fraction of time. These describe pacing; they do not diagnose its cause.

Summary/FPS-only files, unsupported/empty data, duplicate columns and concatenated repeated headers fail clearly. Malformed selected rows, nonpositive times and NaN/infinity are reported with line numbers, excluded from sample distributions and suppress FPS. No reciprocal-FPS fallback or silent unit inference occurs. `--skip-rows`/`--take-rows` select data rows, not elapsed seconds.

## Desktop and Gaming Mode workflows

The [tool runbook](../tools/ally-profiler/README.md) supplies separate procedures. A passive collector can observe either session, but their frame-log measurement points are not interchangeable.

**Desktop:** use a terminal and the existing approved launch path. An application-layer MangoHud pilot is a future separately approved setup; no shortcut, prefix or global environment edits are made by the tool. An external example configuration is documented, not installed. The tool can collect telemetry without MangoHud, in which case FPS remains unavailable.

**Gaming Mode:** use the existing Gamescope session and an already available terminal/access channel. Do not add nested Gamescope or assume desktop layer injection replaces mangoapp. Verify the existing session's mangoapp export support, config delivery, per-frame cadence and application-versus-compositor meaning. If those cannot be established, collect telemetry only. No service, SSH enablement or session changes are performed.

A normal game launch may itself write caches, saves or logs. This harness being passive does not authorize that launch or establish installation isolation. Obtain approval and agree on the concrete test context first.

## Exact usage commands

### Safe preparation now, no game required

```bash
cd "$HOME/Projects/nhl-legacy-recomp" || exit 1
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/ally_profiler.py self-test
```

`dry-run` is an alias for the same synthetic-only tests.

### First Desktop telemetry session, only after gameplay approval

With an approved game already running and warmed up, use a separate desktop terminal:

```bash
cd "$HOME/Projects/nhl-legacy-recomp" || exit 1
ps -eo pid,comm
read -r -p 'Enter the Linux PID of the already-running nhllegacy.exe: ' NHL_PROFILE_PID
python3 tools/ally-profiler/ally_profiler.py collect \
  --session desktop --pid "$NHL_PROFILE_PID" --duration 120 --interval 0.5
```

These commands do not launch the game. The PID must refer to the Windows game process on the Linux host, not Steam/Proton launcher/wineserver. The printed run path contains `metadata.json` and `telemetry.jsonl`. If no approved game is running, stop after self-test. No automatically inferred identity is trusted.

### Import a completed Desktop frame log

```bash
python3 tools/ally-profiler/ally_profiler.py analyze \
  "$HOME/nhl-ally-profiles/mangohud-desktop/REPLACE_WITH_ACTUAL_LOG.csv" \
  --source mangohud-application --frametime-unit ms
```

Only add `--per-frame` after checking the effective logger configuration, row count, elapsed duration and cadence. Sampled logs cannot support a claimed frame distribution. The file path is a placeholder; no actual game log was used here.

For Gaming Mode telemetry, replace `--session desktop` with `--session gaming`. For an independently verified compatible mangoapp CSV use `--source gamescope-mangoapp`; preserve its separate measurement provenance. See the runbook for conditions and limitations.

## Validation performed

Executed Python in-memory `compile()` syntax checks for both Python files, CLI `--help`, `self-test` and its `dry-run` alias. No bytecode/generated artifacts were written into the repository. The final suite contains **16 passing synthetic tests**:

1. Known FPS and interpolated percentile distribution plus threshold fraction.
2. MangoHud version/preamble, UTF-8 BOM, CRLF, quoted metadata and explicit unit conversion.
3. Ambiguous unit rejection.
4. Unverified sampling suppresses FPS.
5. Invalid/malformed/nonfinite/nonpositive rows reported and FPS suppressed.
6. Empty, summary and FPS-only log rejection.
7. Duplicate and concatenated header rejection.
8. Single-frame analysis, row selection and seconds conversion.
9. Missing sensors and mocked permission denial.
10. GPU units, labels, missing labels and active/malformed DPM parsing.
11. No-GPU and multiple-GPU discovery with fake driver links.
12. Process/thread delta rates, names with parentheses, context switches and PID reuse.
13. Malformed/disappearing task data and missing process.
14. Unique output directories, symlink rejection and no overwrite.
15. Collector metadata/JSONL output with mocked process/GPU reads and temporary output.
16. Nonfinite sensor and TID identity-change baseline.

The collector integration test uses a 0.01 s synthetic run and mock discovery/process reads. It does not observe live gameplay or a live process. Tests exercise behavior and numeric expectations, not claims of field accuracy on an executing game.

Final checks include whitespace, Markdown local links, and a staged-path allowlist before commit. No application/SDK source, binaries, generated guest files or assets are included. No game was launched or built; no additional packages or Bazzite settings changed; no playable installation, shortcuts or Proton prefixes were modified.

## Files changed

- `tools/ally-profiler/ally_profiler.py` — collector, analyzer and CLI.
- `tools/ally-profiler/test_ally_profiler.py` — synthetic tests.
- `tools/ally-profiler/README.md` — safety, schemas and separate session workflows.
- `reports/003-ally-profiler-implementation.md` — this implementation record.
- `reports/README.md` — report index entry.

## Limitations and next steps

No real MangoHud/mangoapp output, actual gameplay overhead or Gaming Mode export was tested. The parser targets the documented numeric CSV shape, not arbitrary Gamescope debug traces. It does not prove per-frame sampling, automatically align clocks, inspect shader compilation, time GPU queues, distinguish CPU useful work from spins, or identify the cause of blocking. Missing sensors and permission gaps remain missing. GPU hotplug after discovery is not comprehensive. Linux stat/status reads can race; short-lived threads may be missed. Context-switch counts are not wait durations. Process names may be truncated and manual PID selection still requires care.

Recommended first gameplay test: after explicit approval, use Desktop Mode with fixed current settings and five-minute warm-up, capture a 120-second telemetry pilot and validate an application-layer per-frame logging route separately. Record interruptions and manual simulation progression without screenshots. Repeat three matched runs only once the pilot's timing/logging semantics are understood. Compare paused-menu and gameplay workloads separately. Validate Gaming Mode/mangoapp independently afterward.

Outstanding decisions: approved writable game-test context, exact installed Proton/binary identities, verified frame-log sampling/configuration, output extent/refresh/caps, and whether additional wait instrumentation is needed after observing the baseline. Do not change readback mode or game settings as part of the first baseline. Wait for further instructions before game execution or configuration changes.
