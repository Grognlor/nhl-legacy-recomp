# 017 — Targeted thread wait-state diagnostic

## Executive summary

Implemented a separate, standard-library **read-only `/proc` thread sampler**, `tools/ally-profiler/thread_wait_sampler.py`, with bounded activity discovery, explicit thread confirmation, process/thread identity guards, structured wait-state snapshots and bounded private output. It does not attach, signal, read process memory or change target/system state.

**The tool has not been tested against the live NHL process.** All collection/discovery tests use synthetic proc fixtures and controlled clocks. Their success does not establish real-world compatibility, low overhead, accessible wait symbols or diagnostic accuracy. No NHL/Steam interaction, live capture, instrumentation, executable change, rebuild, MangoHud or system/controller change occurred.

**57 tests pass: 32 existing tests plus 25 new tests.** The next step remains approval of one 60-second passive comparison, using the new sampler at 0.2 s, existing telemetry at 0.5 s, unchanged rear-button recorder, and separate human scene-type notes. No root privileges or new dependency should be needed; actual wait/input access must be checked at that later session without escalation.

## Scope and source context

Starting branch `perf/ally-investigation`, clean HEAD `7f5068294ea4c7c019cc6be23d9f5dd30c74e0e4`; origin `Grognlor/nhl-legacy-recomp`. Reviewed reports [013](013-frame-freeze-and-catchup-investigation.md), [014](014-diagnostic-build-feasibility-and-implementation-plan.md), [015](015-prebuilt-release-performance-diagnostic-plan.md), [016](016-emulated-thread-bottleneck-investigation.md), collector/tests/runbook and relevant runtime findings. Report 016's pinned-source references remain the basis for interpreting thread names, CP waits, GPU waits and guest timing. No application/SDK source modifications.

The observed hot guest thread (~93.89% of one core) was busy both near and away from freezes; the active CP worker (~34.31%) often quieter near freezes. Report 016 corrected the local capture to 12 freeze markers/nine camera changes, 11 freezes in coverage. These findings support examining wait behavior but do not identify a root cause. No new numerical gameplay claims are made.

Pinned ReXGlue `XThread::Create/Execute` (`src/system/xthread.cpp`, 435–479/571–650) names a host thread and calls translated guest functions; the name does not identify an NHL subsystem. `CommandProcessor::WorkerThreadMain` (`src/graphics/command_processor.cpp`, 274–323) may spin/yield/wait on empty work and write back guest ring progress after a batch. `GraphicsSystem::Setup/MarkVblank` (`src/graphics/graphics_system.cpp`, 153–180/328–340) and `FunctionDispatcher::ExecuteInterrupt` (130–160) provide timing/critical-region dependencies. Vulkan CP/presenter may wait on submissions, images or queues. None is identifiable from a generic kernel futex alone; this tool deliberately does not label those causes. Immutable links and detailed ranges are preserved in Report 016.

## Implementation and supported measurements

[thread_wait_sampler.py](../tools/ally-profiler/thread_wait_sampler.py) imports only standard-library modules and existing `ally_profiler` helpers for stat parsing, safe unique output allocation and exclusive metadata writes. There is no new package, launcher, daemon, dependency fetch, subprocess/attach API or target signal path. The CLI exposes `discover` and `collect`; synthetic proc roots, fake clocks and alternate output bases are Python-only test injection, not command-line bypasses.

| Measurement | Implementation / meaning | Limit |
| --- | --- | --- |
| Explicit PID and selected TIDs | Reads only that process's stat/task paths, plus host boot-ID metadata | No child discovery, environments, command lines, stacks or executable inspection |
| CPU counters | Per-thread stat `utime+stime`, start ticks and `SC_CLK_TCK` | Cumulative execution ticks; no instruction samples or useful-work/spin distinction |
| State | Linux stat R/S/D/etc. | R includes runnable, S generic interruptible sleep, D generic uninterruptible sleep; snapshots are not durations |
| Wait channel | Bounded read of `/proc/PID/task/TID/wchan` | Symbol may be generic/misleading; no lock owner, GPU fence identity or call stack |
| Context switches | Voluntary/involuntary cumulative counts from task status | Transitions, not off-CPU/runqueue delay; missing/invalid fields remain null/error |
| Time | Sample monotonic ns + timezone-aware UTC, read-end ns and duration | Non-atomic measurements and observation skew; no game-step or GPU clock calibration |
| Provenance | PID/TID start ticks, boot ID or error, clock implementation/resolution, interval/duration/bounds | Existing marker/CPU logs lack boot ID; cannot absolutely prove shared boot from timestamps alone |

No GPU utilization/completion query, presentation callback, unique-image ID, guest step counter, input latency or physical refresh measurement is introduced. Invalid GPU utilization remains invalid. Similar display-clock progress does not prove normal animation updates.

### Selection safeguards

`discover --pid PID` performs a bounded two-second observation by default, sampling candidates at 0.2 s. It enumerates at most 512 threads and tracks all `XThread*` and `GPU Commands*` candidates. It checks process identity and the candidate identity/name set throughout, refusing churn or decreasing counters instead of silently ranking survivors. It records all candidates, delta ticks, CPU rate estimates and selected suggestions as JSON on stdout; it writes no discovery file.

Within each role, the winner needs positive tick activity and a lead over the runner-up of at least **max(2 ticks, ceil(10% of winner ticks))**. Ties, near-ties, no guest/GPU candidate or zero activity leave the role ambiguous; CLI exits 2. A clear ranking is a heuristic for observed activity, not proof of guest purpose or future activity. Multiple truncated GPU names are tested explicitly. Do not collect after ambiguous discovery.

Collection requires `--pid`, `--process-start`, `--guest TID:START`, `--gpu TID:START`, and **`--confirm-tids`**. Users must review successful discovery and manually supply those identities. The tool never auto-launches capture, chooses the first matching thread, loads shell code from JSON or uses historical TIDs. The boolean confirmation and explicit identities are an operator gate, not an independent verification that the operator ran discovery correctly.

### Identity and lifetime safeguards

Before output allocation, selected roles and PID/TID start ticks must match. Every snapshot checks the process before/after both selected threads and each selected thread before/after its ancillary reads. A vanished PID, zombie/dead state, changed start ticks, selected name change or observed CPU counter regression stops collection; it does not follow a replacement or substitute another same-named thread. Mixed-identity sample data is discarded, and an end record explains the stop. No signals are sent, including on Ctrl-C; only the sampler handles its own interrupt.

Observable start ticks are not an absolute lifetime token: same-tick reuse, re-exec retaining identity and unobservable changes between checks cannot be excluded. Permission denial to required stat data stops rather than escalating. A missing status/wchan with an otherwise valid identity records explicit missing fields, permitting useful state observations to continue. Selected-thread disappearance stops the run rather than leaving incomplete per-thread data silently.

### Wait-channel classification

The wchan object records `raw`, interpreted `value`, `status` and `error`. Non-address strings are `symbol`; hidden `0`, empty/`-` or numeric/address-like strings are `unavailable_or_not_exposed`, with no asserted wait name. Missing data is `unavailable`; `PermissionError` is `restricted`. Oversized/malformed reads are errors. These categories do not claim to distinguish policy hiding from a legitimately unavailable channel on a running thread. No missing value becomes zero; raw ambiguous values remain available locally for review. A final count identifies unavailable observations. **Never retry as root or change kernel restrictions.**

## Bounds, safety and overhead

Default 60 seconds/0.2 s/two selected threads yields about **300 snapshots**. Allowed CLI duration 0.1–600 s, interval 0.1–10 s; additional cap **6,000 samples**. JSONL is capped at **8 MiB**, including reserved end-record space, with **16 KiB maximum record size**. Metadata is a separate bounded small file. Reads cap stat/status at 64 KiB and wchan at 256 bytes. Discovery permits at most 512 tasks and ten requested seconds; overflow stops rather than silently omitting candidates. Memory retains bounded current candidates/snapshots, not a growing recording.

Both metadata and JSONL use exclusive creation within a new private run directory under `~/nhl-ally-profiles/`, reusing the existing canonical HOME/Bazzite safety boundary and symlink/traversal rejection. No arbitrary CLI output path is accepted. Existing files and recordings are never opened for overwrite. Capture files: `metadata.json`, `thread-waits.jsonl`; JSONL contains `sample` objects and a final `end` object with reason, count and unavailable-channel total. End reasons distinguish normal duration, interrupt, target/read failure, sample limit and output limit. CLI reports partial/error stops as nonzero rather than successful full captures.

No periodic terminal output during collection; the path/reason is printed at completion. Data are streamed and flushed each sample. Deadlines use monotonic time and skip catch-up bursts after late reads. Kernel reads, filesystem I/O, scheduling delay or an interrupt during an I/O failure can prevent strict wall-time guarantees; this is a bounded observer, not a real-time deadline mechanism. A hard kill/power loss can leave no final record or a partial tail; offline readers must report incomplete coverage, not invent samples. Disk-full/write failures are reported; no retry/cleanup overwrites earlier files.

Two-thread proc reads at five Hz should be lighter than broad stack tracing, but **actual overhead is unmeasured**. Collection duration is recorded for review and does not establish a gameplay performance penalty. Default output is expected to be well below the hard bound; no empirical file-size or speed claim is made from NHL. Start at defaults, stop on changed responsiveness and do not increase rates to chase sub-frame events. The existing 0.5 s CPU profiler adds its own observer work. New sampler never reads sensors or game assets.

## Timestamp alignment and offline interpretation

Metadata records `time.monotonic_ns`/Linux CLOCK_MONOTONIC, actual clock implementation/resolution, tick frequency, boot ID/error and selected identity. Every sample has read-begin monotonic/UTC and read-end monotonic values. This is compatible with existing CPU telemetry and the marker's `time.monotonic_ns` convention. The marker reads UTC then monotonic; this tool reads monotonic then UTC. Small offset differences can reflect order/acquisition latency rather than different clocks.

1. Compare boot IDs where present; verify monotonic ordering and UTC-minus-monotonic consistency across logs. Existing CPU/marker files lack boot IDs, so retain that limitation and reject contradictory clocks/reboots.
2. Use the **actual overlapping monotonic coverage**, not requested durations, filenames or wall time alone. Exclude markers outside that overlap; marker append files may include earlier/later sessions.
3. Map rear-button events to sampled neighborhoods (initially ±1 s, with 0.5/2 s sensitivity). Retain human reaction delay, 0.2/0.5 s sampling and per-snapshot read spans. Do not treat the press as freeze onset/end or five-Hz snapshots as exact wait durations.
4. Use supplied scene labels and neighboring same-scene references. “Unmarked” is not guaranteed smooth. Derive counter/CPU deltas only across the same PID/TID/start identity and valid time intervals; use actual elapsed times, not nominal rate. Existing profiler remains the primary CPU rate series.
5. Preserve missing/error fields, sample gaps, partial stops and observer costs. No automatic alignment/statistical significance or causal classifier is added by this task.

## Proposed 60-second workflow

The full copy-paste procedure is in the [Task 017 runbook](../tools/ally-profiler/README.md#task-017-targeted-thread-waits-future-approved-gameplay-test). **It is proposed only; do not execute during Task 017.**

Use an already-running, approved Desktop match. First run discovery on a manually verified PID, review unambiguous candidate activity, and enter process/guest/GPU start identities. No game restart, graphics/FPS/power change or MangoHud is involved. If the game is absent, a launch needs separate approval.

Keep three observer terminals foreground: A existing marker recorder; C existing CPU profiler (`--duration 60 --interval 0.5`); B new sampler (`--duration 60 --interval 0.2` plus explicit identities/confirmation). Start C/B close together; clocks handle staggered starts, but compare only overlap. Each collector allocates a distinct safe run directory. Stop only the observer terminals with Ctrl-C if needed; do not signal NHL/Steam. Collectors end automatically, then stop A if started for this test. Do not duplicate or terminate an already-existing marker recorder without the user's direction. Existing CPU collector may run to deadline after PID exit, unlike the new sampler.

The outside-repository `scene-marker.py` was read only, never changed or executed. It currently uses the existing evdev input node, code **710 camera**, **708 freeze**, key-press events only, appending to its existing marker JSONL; no grab call was present. The evdev module is discoverable locally, but input-node correctness/permissions and marker runtime operation were **not** tested. Hardcoded input-node numbering may change: stop and request review if it fails; do not repair settings, install packages or elevate automatically. Marker logging has its existing append/unbounded behavior and therefore needs a manual stop; the new sampler's bounds do not bound that external script.

Scene type is a separate private human note keyed to camera marker ordinal/UTC: `wide`, `bench`, `player-closeup`, `replay`, `intro`, `unknown`, with end/return transitions where known. Prefer a second observer. Solo notes retain uncertainty and focus changes. No new mapping, button behavior, screenshot, video or input grab is required. Never assume markers alternate scenes. Natural close-ups/bench shots are priority; intro only if encountered without restarting/changing gameplay. If no freeze/close-up occurs, report non-reproduction, not permission to repeat automatically.

Expected user effort: two-second discovery plus review/setup, one minute capture and brief notes (~5–10 minutes total). No permission escalation is required in normal operation; unknown/denied channels remain explicit. Further access changes, package installs, intrusive tracing, launches or configuration changes need separate approval. **Live discovery/capture itself remains unapproved by Task 017.**

## How it can narrow competing hypotheses

| Correlated observation | Useful inference | Unresolved boundary |
| --- | --- | --- |
| CP repeatedly sleeping with exposed wait names near typed close-ups/freezes | Establishes sampled host waiting rather than constant CP execution; a driver-related category can motivate focused follow-up | Generic futex cannot distinguish empty-ring waits, SDK locks, Wine waits or GPU completion; no GPU saturation verdict |
| Hot guest remains R with near-one-core CPU while CP sleeps | Supports producer/consumer dependency or independently busy guest work | Useful compute versus spin; actual command production, who waits for whom, and critical-path relevance |
| Hot/CP repeatedly D with shared exposed category | More actionable evidence than Report 016's single simultaneous-D sample | Not exact wait duration, ownership or root cause; may involve another subsystem |
| Low CPU with repeated R samples | Compatible with runnable delays | Not proof of starvation; no enabled runqueue-delay accounting or system-wide trace |
| Motion freezes while sampled CPU/state/wchan patterns remain unchanged | Shows limits of this external observer; presentation/freshness or short internal stalls remain viable | Cannot exonerate simulation or GPU, identify repeated frames, or measure physical display timing |

Report 013's internal lineage diagnostic remains necessary for definitive guest→GPU→mailbox→present identity attribution if external evidence is insufficient. The missing build environment from Report 014 is not addressed or worked around. No speculative codegen, affinity, clock, timing, rendering or readback change is justified by synthetic validation.

## Files changed and validation

- Added `tools/ally-profiler/thread_wait_sampler.py`.
- Added `tools/ally-profiler/test_thread_wait_sampler.py` (25 synthetic tests).
- Updated `tools/ally-profiler/README.md` with safeguards, limits and future three-tool workflow.
- Added this report and updated `reports/README.md`.

Validation command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/ally-profiler -p 'test_*.py'
```

**57 tests pass**, including all 32 existing tests. New tests cover identity validation, wrong PID/TID stat contents, reuse before/during snapshots, candidate churn, repeated GPU names, activity ranking/ambiguity, zero/tied candidates, timestamp formatting, missing/restricted/oversized wait fields, partial/invalid status, disappearing threads, process termination/zombies, CPU counter regression, bounded duration/output/sample count/read sizes/thread enumeration, no catch-up bursts, Ctrl-C cleanup and valid final JSONL. Fake proc files are hashed before/after a read-only run and target signal APIs are guarded in tests. No live NHL fixture is used. Syntax/help, documentation links/shell blocks, whitespace, source diff and staged-file allowlist are checked. The outside marker script and October 22 recordings remain unchanged; diagnostics stay locally excluded/untracked and no private capture/identifier is published.

## Recommended next action and authorization

Review and approve one bounded 60-second Desktop diagnostic using the runbook. It does not require rebuilding/replacing NHL or changing Steam, Proton, Bazzite, InputPlumber, mappings, power or graphics. Confirm that the existing input node/marker route works as-is and that ordinary-user wait channels provide useful data; otherwise stop and report the limitation. Do not install/repair/escalate or reinterpret hidden channels as no wait. Tool development and publication finish here; **no live test or performance fix is started**.
