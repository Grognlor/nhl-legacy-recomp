# 019 — Automated timed live profiler

## Executive summary

Implemented [live_profiler.py](../tools/ally-profiler/live_profiler.py), a single-command, standard-library coordinator that discovers an already-running NHL process, ranks guest/GPU Commands candidates by bounded CPU observations, captures CPU/GPU telemetry and selected thread waits over one shared timer, verifies actual sample overlap, and automatically creates a local Markdown diagnostic report.

**Default capture duration is 120 seconds; 300 seconds is supported.** Discovery precedes the timer. Optional terminal scene labels and two safe rear-button sources are available. Every run uses a new private output directory; no game launch, debugger, target signal, configuration change, controller mapping change, package installation or performance fix is implemented.

**96 tests pass: 68 existing and 28 new tests.** Validation uses synthetic proc/input/clock fixtures and read-only regression against the existing Task 017 recordings. **The new coordinator has not been run against NHL or a live input device during development.** Synthetic validation and successful historical analysis do not establish live compatibility, accessible metrics, low overhead or root-cause accuracy. No new gameplay measurement/result is claimed.

## Scope and prior evidence

Branch `perf/ally-investigation`; starting HEAD `00fb9fd10fe24ff03cf19a55b591e3867b285d70`; origin `Grognlor/nhl-legacy-recomp`. Initial tracked tree clean; the pre-existing untracked bytecode directory was preserved and excluded from staging. Read reports [016](016-emulated-thread-bottleneck-investigation.md), [017](017-targeted-thread-wait-state-diagnostic.md), [018](018-ally-wait-state-capture-analysis.md), profiler README, collectors, offline analyzer and tests before implementation.

Report 018 established frequent sampled DRM synchronization waits on the active command worker and persistent ~95%-of-one-core guest activity. It did not establish GPU saturation or the causal wait site. Its wait and CPU recordings had no temporal overlap. This tool addresses the workflow failure by coordinating measurements and explicitly verifying measured overlap; it does not resolve causality through automation alone.

The existing outside-repository marker script was inspected read-only: it still names `/dev/input/event17`, maps 710 to camera change and 708 to freeze, and logs key presses. It was neither changed nor executed. The local Linux input header was inspected for the native `input_event` layout. No actual device read, proc discovery of NHL, sysfs sampling, launch or live capture occurred.

## Architecture and implementation

### Discovery and identity

`find_process` reads bounded numeric proc stat metadata, accepting exactly one readable non-dead process named `nhllegacy.exe` or `nhllegacy` (case-insensitive). It does not inspect command lines, environments, executables, prefixes, Steam settings or assets. Zero/multiple matches stop; inaccessible/unparseable entries are counted rather than inspected with greater privileges. Name-based discovery cannot prove binary identity or identify unreadable processes.

The existing `thread_wait_sampler.discover` performs approximately two seconds of CPU tick observations across named candidates. Every candidate identity/name must remain stable. Each selected role must have positive activity and a clear lead over its runner-up (at least max(two ticks, 10% of leader ticks rounded up)); ties/zero/near-ties/churn stop. Multiple truncated GPU names are handled by activity, not enumeration order. Discovery limits remain 512 threads; process scan has a 65,536 numeric-entry cap. The process set is checked again before recording.

Task 019 authorizes automatic unambiguous selection in this new single-command interface. The standalone Task 017 collector still requires its original manual identity confirmation; its behavior is not bypassed or modified. Selection is printed and retained in local metadata. No historical PID/TID is used. Activity ranking is a heuristic, not an NHL function/subsystem map.

Before and after CPU/wait samples, guards verify process start ticks and selected TID/start/name/role. Task snapshots also check selected identities around ancillary reads. Observed target exit/reuse/rename/counter regression stops both streams, never follows replacements. Same-tick reuse or re-exec retaining observable identity remains outside proc-based guarantees. No target signal path exists.

### Concurrent collection and timer

One scheduling loop interleaves two independently due streams throughout **one shared monotonic deadline**:

- CPU/process/all-thread counters and discovered AMD telemetry every **0.5 s**, reusing `ProcSampler` and `gpu_sample`.
- Selected guest/GPU thread state/wchan/counters every **0.2 s**, reusing `Proc.snapshot`.
- Optional terminal/marker polling between due reads, normally at most ~0.1 s apart absent delays.

This is concurrent observation over the same session, **not parallel or atomic sampling**. Sequential reads can delay one another. Every record has actual UTC/host monotonic timestamps and a collection span/cost. Late reads advance their next deadline without catch-up bursts. Timer/read deadline overshoot is possible under scheduling/I/O delays; this is not a real-time service.

Duration accepts finite **1–600 seconds**, default **120**. A two-second discovery phase and setup are additional. A custom 300-second session is tested with a controlled clock, not by sleeping or profiling NHL. No background subprocesses or long-running service are created.

The only existing-collector modification is optional `ProcSampler(..., thread_limit=None)`: the coordinator passes 512 to bound task enumeration; default standalone behavior remains unchanged. Overflow is explicit instead of silently selecting a partial list. Existing tests pass.

### Rear-button integration without remapping

Default mode tails only newly appended records in the existing dedicated-home marker log. It does not start/stop the outside recorder, overwrite its file, read earlier append content or assume a recorder is active merely because the file exists. Missing, malformed, replaced, symlinked or truncated logs are reported. File reads and buffers are bounded. No arbitrary marker-log CLI path is accepted.

Optional `--marker-device /dev/input/eventN` makes a session self-contained: it opens that explicit node **read-only/nonblocking**, with no grab, ioctl, package dependency, input write or mapping change. The native 64-bit Linux event layout is checked. Only EV_KEY press values for **710 camera /708 freeze** are retained; releases, repeats, unrelated keys and axes are discarded without raw input logging. Device mode ignores the external log, so it does not double-import an existing recorder's copies. That external process is left untouched.

Node identity, permissions and actual rear-button behavior are **unverified** here; current script configuration is not proof the node remains correct. Missing/denied/unsupported/disconnected inputs degrade marker coverage, never trigger elevation or device guessing. Explicit input reading drains bounded batches (up to 1,024 events per poll); SYN_DROPPED or excessive residual backlog disables that optional source as unreliable. Only its own descriptor is closed.

Direct-node events receive UTC/monotonic timestamps when processed, like the prior script; kernel event timestamps are not reinterpreted under an assumed clock. Polling adds up to roughly 0.1 s plus scheduling/read/reaction delay. Backlog checks prevent silently treating arbitrarily stale input as immediate, but do not make markers frame-accurate.

### Scene labels

`--scenes` enables nonblocking, optional terminal lines (letter + Enter): `w` wide, `b` bench, `p` player close-up, `o` other, `u` unknown, plus `r` replay and `i` intro. `f`/`c` optionally add freeze/camera events; avoid reporting the same occurrence twice. `q` stops the profiler only. EOF disables the interface; non-TTY input records that scenes are unavailable. No scene input is required to finish a timed session.

Labels persist until changed, default unknown. Camera events never imply an alternating scene. Same-session labels carry into a slightly later-starting stream; intervals crossing a label transition are excluded from scene means. Scene typing/focus can perturb gameplay, so a second observer is preferable and uncertainty remains explicit. No screenshot/video, controller remap or forced camera change is needed.

## Raw output, bounds and recovery

All data go under one newly allocated private directory in `~/nhl-ally-profiles/`. Existing HOME canonicalization supports Bazzite's normal home alias; dedicated output symlinks/traversal remain rejected. Files are created exclusively and earlier evidence is never overwritten. No arbitrary output-directory option exists.

| Output | Purpose |
| --- | --- |
| `session.json` | Initial identity/discovery/timer/clock/bounds/marker-source metadata, saved before recording; initial stop reason incomplete |
| `completion.json` | Final stop reason/error, end stamp and marker status; separate file, no overwrite of initial metadata |
| `telemetry/metadata.json`, `telemetry/telemetry.jsonl` | Existing-format CPU/GPU measurements and explicit missing/error fields |
| `wait/metadata.json`, `wait/thread-waits.jsonl` | Selected thread snapshots plus final end record |
| `markers.jsonl`, `scenes.jsonl` | Only this coordinator's imported/observed numeric event records |
| `analysis.json`, `report.md` | Automatically generated offline aggregates and diagnostic Markdown |

CPU JSONL cap **32 MiB**, wait JSONL **8 MiB**, markers/scenes **1 MiB each**. Per-record caps are CPU 256 KiB, waits/events 16 KiB, with reserved end-record space. Proc read/discovery bounds remain in the existing sampler. Input/event buffers and batch reads are bounded. During recording, memory holds current observations/candidates rather than all history; post-run analysis loads capped files and has greater transient memory requirements. Large output/read/identity errors preserve partial evidence and stop numeric capture or disable the affected optional marker source.

Normal expiration, Ctrl-C or `q` closes only the profiler's own descriptors, writes completion/footer where possible, then analyzes partial data. Process/selected-thread loss stops both streams. Missing GPU sensors, hidden waits and unavailable status counters are not zero-filled. No error causes fallback to privileged access. Missing/truncated JSONL is noted; malformed tails are skipped with limits. Raw errors are available for review. Disk-full, I/O failure during finalization or power loss may prevent report persistence; initial metadata supports later offline recovery if it was written. No guarantee can make storage succeed on a full disk.

## Offline analysis and automatically generated report

`analyze_data`/`finish_report` operate on existing file contents, with no proc, device, target or sensor access. `--analyze RUN_DIRECTORY` reads initial/completion metadata and prints Markdown without overwriting any old report.

The report includes:

- Measured first/last sample coverage and sample-window intersection, with UTC/monotonic consistency validation. Non-overlap is zero; missing/incompatible clocks are **unverified**, not a fabricated zero.
- A coverage gate requiring compatible clocks, valid final wait count/footer, **≥80% requested-duration overlap**, **≥80% nominal sample counts** and **≥80% valid adjacent identity intervals**. This is an overall gate; localized sample gaps still matter.
- Selected thread CPU means/ranges, process CPU, R/S/D/etc. snapshot counts, switch rates, exposed wait symbols and explicit unavailable counts; no instruction-level attribution.
- Per-stream ±1 s freeze neighborhoods, unmarked comparisons, each event's CPU values, wait-category hits and available sensor comparisons. Unmarked does not mean normal; presses have no freeze-duration field.
- Human-labelled scene CPU/wait/sensor comparisons, excluding transition-crossing intervals; unknown scenes are not inferred from thread patterns.
- Valid sensor mean/range/count/missing summaries. Multiple discovered GPUs are kept distinct. All readings from the known-invalid utilization source are excluded. DPM is not an instantaneous-clock guarantee; slowPPT is not GPU-only and channels are not added.
- Explicit observations versus competing hypotheses and limitations. There is **no FPS/frame-time**, unique-output, simulation/animation step, input latency, GPU-completion or physical-refresh measurement. DRM/futex names are not specific caller/ownership evidence, snapshot hit fractions are not wait durations, and near-one-core CPU can include polling.

Marker filtering uses actual per-stream UTC/monotonic coverage, not filenames; older sessions/boots are excluded before uptime checks. Scene clocks must also agree. The existing explicit 50 ms offset guard is a compatibility sanity threshold, not event precision. Unknown input/clock cases disable affected correlations and record limitations. Streams can be compared jointly only over validated actual overlap; the historical separate recordings remain separate in regression tests.

## Expected overhead and compatibility limits

Default numeric sampling remains 2 Hz full telemetry plus 5 Hz two-thread waits. Guards and marker/terminal polling add work. Discovery adds short process/task scans before the timer. Direct-device drains are bounded and unrecognized input is discarded. There are no stacks, captures, debuggers, busy polling, new GPU queries or API injection.

**Actual gameplay overhead is unmeasured.** Record read costs and sampling gaps; those spans omit some discovery/guard/input/report work and are not an FPS penalty measurement. The interleaved scheduler can delay wait sampling behind a slow CPU/sensor read. Post-capture reporting consumes CPU/memory but occurs after the requested recording. Stop if observation worsens play. Hardware/driver/process-name/device-layout/permissions may differ from fixtures; successful tests do not validate live behavior or causal conclusions.

## Usage and first approved recording

Full options/workflow are in the [updated README](../tools/ally-profiler/README.md#task-019-one-command-timed-profiler). **No live recording is run or authorized by this development task.** Once the user approves, launch NHL normally themselves, leave preferred settings unchanged, then run from the repository:

```bash
python3 -B tools/ally-profiler/live_profiler.py \
  --duration 120 --marker-device /dev/input/event17 --scenes
```

The node matches the currently inspected existing recorder configuration, but must still work under ordinary permissions at the approved session; do not substitute another device, escalate or repair settings automatically. Numeric capture continues with a clear marker limitation if access fails. For existing-log mode instead, omit `--marker-device` and keep the already-approved external recorder running. That mode is also a single profiler command, but does not start the independent recorder. No approval is inferred from elapsed time or successful tests.

For five minutes, use `--duration 300`. Scene labels are optional; an observer should mark naturally occurring wide/bench/player/replay scenes and return to wide/unknown explicitly. Auto-stop closes the profiler; no game/Steam/recorder termination is needed. For early stop use Ctrl-C in the profiler terminal or `q` + Enter. Review `report.md` and its measured overlap/data-quality limits before sharing sanitized aggregates. Never commit raw run directories.

Offline reanalysis, with no live access:

```bash
python3 -B tools/ally-profiler/live_profiler.py \
  --analyze "$HOME/nhl-ally-profiles/REPLACE_WITH_ACTUAL_COORDINATOR_RUN"
```

## Validation and changed files

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/ally-profiler -p 'test_*.py'
```

**96 tests pass**, including all 68 existing tests and 28 new tests. Coverage includes automatic zero/multiple/dead process rejection; changing process sets; ambiguous same-named thread activity; common timer/overlap/counts (a 50 ms synthetic read delay reduces measured overlap from 2.50 to 2.45 s); actual custom 300-second control-clock operation and default 120 CLI; no catch-up scheduling; bounded enumeration/output and unique/exclusive/symlink-safe output; process exit/TID reuse; Ctrl-C/q/EOF; optional scene transitions and terminal markers; marker-tail append/filter/missing/symlink/truncation behavior; permission/source failures; explicit read-only device flags; existing rear-button press/repeat/release semantics; input overflow/backlog; invalid duration; partial/corrupt/missing metrics; inconsistent clocks versus verified non-overlap; sparse samples/missing footer gates; report generation and read-only reanalysis.

The optional local-recording regression reads existing Task 017 files only (skipped when private data are absent in a fresh clone), preserving their bytes and reproducing ~95.67% guest activity, seven versus four in-window freezes and **zero overlap**. It does not profile a process. October 22/Task 017 evidence and the outside recorder remain untouched. Syntax/help, local Markdown links/shell blocks, source diff, raw-file hashes and staged allowlist are checked. No raw diagnostics, private system identifiers, bytecode, assets, binaries or generated game files are committed.

Files changed:

- Added `tools/ally-profiler/live_profiler.py`.
- Added `tools/ally-profiler/test_live_profiler.py`.
- Added optional bounded enumeration to `tools/ally-profiler/ally_profiler.py`; other collector behavior unchanged.
- Updated `tools/ally-profiler/README.md` and `reports/README.md`.
- Added this report.

## Recommended next action

Review and approve one default-duration concurrent run of the coordinator on the already-running release, with explicit scene types and existing rear-button semantics. Verify ordinary-user device/metric availability and actual overlap in the generated report. If identification is ambiguous, markers are inaccessible, or symptoms are not reproduced, preserve the result and report the limitation; do not change runtime settings or guess another target. No implementation of performance fixes or further profiling starts after publication of Task 019.
