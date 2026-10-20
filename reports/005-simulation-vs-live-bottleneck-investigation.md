# 005 — Simulation versus live bottleneck investigation

## Objective and executive summary

Investigate the new simulation/live telemetry, identify what `XThread0204` means, audit invalid GPU utilization, and define the next discriminating measurement. Branch verified as `perf/ally-investigation`; starting commit `94f9aa55c901748f12b422a436752c36ec4cd3cd`; working tree initially clean. Read reports [001](001-initial-performance-investigation.md), [002](002-ally-profiling-and-linux-feasibility.md), [003](003-ally-profiler-implementation.md), [004](004-bazzite-home-path-fix.md), the report index and profiler runbook before changes.

**Both local capture directories were accessible and their metadata/JSONL were read directly.** The supplied summary is supported by the files. Process CPU averages are almost identical, and the same Linux thread consumes approximately 95% of one logical core in both. The live capture's GPU clock is lower, but neither CPU time nor clocks measure work completed per frame. Invalid GPU utilization and absent synchronized frame data prevent a bottleneck verdict.

The exact pinned SDK identifies `XThread####` as a default name derived from a Windows host thread ID, not an Xbox CPU number, a guest function address or a game subsystem. Linux TID 7148 carries the name here; the primary `GPU Commands` thread is separately identifiable as TID 7102. Whether TID 7148 is doing useful simulation work, polling, lock contention or other execution remains unknown.

Implemented only a **profiler validity correction**: `gpu_busy_percent` is already interpreted at scale 1; out-of-range values now retain `raw_value` but expose null utilization and an explicit error. No evidence supports dividing by 100. No application/SDK optimization or game/configuration change was made.

Recommended next action: approve a short Desktop MangoHud **application-layer** per-frame logging pilot alongside unchanged passive telemetry, then compare matched simulation/live segments. This reduces ambiguity; it cannot conclusively distinguish every stall without reliable GPU activity or wait attribution.

## Evidence and provenance

Platform supplied by user: ASUS ROG Ally Z2A, Bazzite 44, Proton Experimental, Windows Recomp v0.6.0. Capture conditions supplied by user: 25 W target, 720p, 1× supersampling, VSync off, FSR on, shadows off. These settings are not encoded or independently verified in the profiler metadata. User reports simulation slower than expected and live gameplay noticeably worse.

Both filesets identify `session=desktop`, PID 7070, a 0.5 s requested interval, 120 s duration, `SC_CLK_TCK=100`, and no GPU discovery errors. Each contains 240 valid process records; each initial CPU rate is null by design, leaving **239 CPU-rate intervals**. Process start tick is 17283 in both; TID 7148 start tick is 17797 in both. These identities are consistent across captures; boot/binary identities were not recorded. Simulation/live labels come from the user, not mode detection in telemetry.

| Capture | Local path | UTC sample window |
| --- | --- | --- |
| Simulation | `~/nhl-ally-profiles/20261020T015138Z-pfafx48m/` | 2026-10-20 01:51:38.539576 to 01:53:38.039421 |
| Live | `~/nhl-ally-profiles/20261020T020743Z-69rci8mq/` | 2026-10-20 02:07:43.441679 to 02:09:42.941681 |

The sample span is approximately 119.5 s for each 120 s session, as expected when the first sample starts near zero and the final sample occurs before the deadline. Files were read in place, not modified or copied into Git.

SHA-256 provenance:

- Both `metadata.json`: `8ad702abd5b6acc4e73ca60a22ed1ae8dceea23350fd8595c46769f2f005f8b6`.
- Simulation `telemetry.jsonl`: `891c42dcd021d673e8acc2c5bfea0fc4858ce16cbed8df9ab315fab73064416a`.
- Live `telemetry.jsonl`: `ccbe1e21591cd5027fbaa69bb76939b0df066ae1ab67b2bbc495264304859bb3`.

Only aggregates and provenance are committed. The SDK sources reviewed are public files at immutable commit `bd9b51918faa71f962fa38af6d5f744af9aba2ce`, as pinned in [`scripts/setup_sdk.ps1`](../scripts/setup_sdk.ps1). They were retrieved into `/tmp/nhl-investigation-005` without modifying the repository SDK integration. No diff from local tag v0.6.0 exists in `src/`, `renderer/` or `sdk/`. The installed executable/runtime have not been inspected or proven to match the pin.

## Verified capture results

CPU means below average the 239 valid interval rates, with 100% representing one logical core. Process and thread values overlap and **must not be added**.

| Metric | Simulation | Live |
| --- | ---: | ---: |
| Process records / total | 240 / 240 | 240 / 240 |
| Mean process CPU | 334.01% | 334.95% |
| Mean `XThread0204 (F8`, TID 7148 | 94.91% | 94.86% |
| Mean `GPU Commands (F`, TID 7102 | 32.16% | 29.70% |
| Mean unnamed `nhllegacy.exe`, TID 7090 | 61.84% | 61.67% |
| Mean `XThread01F0 (F8`, TID 7139 | 30.56% | 32.01% |
| Mean `XThread0200 (F8`, TID 7147 | 25.17% | 27.82% |
| Median hwmon `sclk` (`freq1_input`) | 1063 MHz | 697.5 MHz |
| Mean hwmon `sclk` | 854.19 MHz | 706.07 MHz |
| hwmon `sclk` range | 200–1160 MHz | 200–1160 MHz |
| Median `edge` temperature | 65 C | 68 C |
| Temperature range | 62–68 C | 66–71 C |
| Mean `power1_average`, labelled `slowPPT` | 19.3874 W | 19.9378 W |
| Median active DPM sclk state | 1064.5 MHz | 657 MHz |
| Median active DPM mclk state | 687 MHz | 687 MHz |
| Utilization samples outside 0–100 | 228 / 240 | 225 / 240 |

Use hwmon sclk and DPM state as different measurements; they are sequential reads and need not agree. DPM is explicitly an active state, not an instantaneous hardware-clock guarantee. Median and mean differences show that one median does not describe the complete clock distribution. `slowPPT` is not GPU-only power; its mean near 20 W neither proves the 25 W target is ineffective nor reveals separate CPU/GPU allocations.

TID 7148 accumulated 113.42 s CPU time during the simulation sample span and 113.36 s during live. State snapshots were R/S/D = 229/10/1 and 234/6/0, respectively. Voluntary/nonvoluntary context-switch deltas were 88610/37692 and 84725/26865. These counts do not identify spin/yield sites or time spent blocked; snapshots are not duration-weighted state fractions. R does not distinguish currently executing from runnable contention, and D does not identify a specific device wait.

TID 7102 was observed sleeping in 160/240 simulation and 167/240 live snapshots. That is compatible with command starvation, GPU waits or other synchronization; it does not prove any particular reason. It is not compute-saturated across these whole windows, which does not rule out burst-limited submission or a critical serial dependency.

One live sample at elapsed 6.500572 s recorded disappearance of `/proc/7070/task/8922/stat`, consistent with thread churn. All game-process samples remain valid. The simulation has no process/task errors. Median collection wall durations were 9.92 ms and 10.18 ms (maxima 14.98/16.63 ms), approximately 2% of the nominal 0.5 s interval. Those are observer wall durations, not observer CPU percentages or a measured FPS penalty.

There is no synchronized frame stream, draw-count stream, CPU frequency series, queue-wait timing, affinity/runqueue-delay series, or numerical simulation-speed measurement in these files. No FPS or per-frame CPU cost can be calculated from this telemetry alone.

## A. What can be established about XThread0204?

### Thread naming and execution mapping

Pinned SDK references:

- [`src/system/xthread.cpp`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xthread.cpp): `XThread::Create()` around lines 435–480 creates a host thread with guest execution state bound to it. If unnamed, it calls `set_name(fmt::format("XThread{:04X}", thread_->system_id()))`.
- `XThread::set_name()` around line 175 appends the kernel object handle in parentheses. That handle is distinct from the default host-ID suffix.
- [`src/core/threading_win.cpp`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/threading_win.cpp): Win32 thread `system_id()` returns `GetThreadId(handle_)`; creation uses `CreateThread`.
- [`src/kernel/xboxkrnl/xboxkrnl_threading.cpp`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/kernel/xboxkrnl/xboxkrnl_threading.cpp): `ExCreateThread_entry()` creates a guest `XThread`, passing startup/address/context and flags.
- `XThread::Execute()` around lines 571–653 uses the startup trampoline or guest start address to look up a registered native function, sets PPC context arguments, converts the host thread to a fiber, and invokes the function directly. This is statically recompiled execution, not proof of an interpreter/JIT bottleneck.

Thus, **in the pinned Windows SDK's default naming scheme**, `0204` is hexadecimal Windows host thread ID 516. It is not Linux TID 516; the recorded Linux TID is 7148. It is not guest thread ID, Xbox hardware-thread index, a guest address or the name “NHL Sim.” The truncated Linux name includes only the beginning of the appended handle (`(F8`), so the full handle cannot be reconstructed. Linux comm fields have a short length limit: [proc stat documentation](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html).

The label is consistent with a default-named guest execution thread. However, `XHostThread` inherits `XThread::Create()` and overrides `Execute()` for host callbacks, so a generic name alone does not prove which subclass/function TID 7148 executes. The explicitly named primary GPU worker is a different observed TID. The unidentified TID 7090 also consumes substantial CPU and should not be guessed to be a render thread.

**Unknown:** actual start address, game subsystem, call sites, Windows-to-Linux ID mapping beyond the observed name/TID association, and fraction of time in useful guest work versus runtime/driver/polling. No trace, debugger, stack or guest-memory inspection was performed. Future matching runtime logs containing `XThread::Execute ... native=...` and creation addresses could improve mapping, but enabling verbose logs or reading installation logs needs separate scope and has timing overhead.

### Affinity, priority and host scheduling

`XThread::SetActiveCpu()` updates the guest KTHREAD/PCR CPU index in the 0–5 range. With at least six logical processors, it only sets a host one-bit affinity mask when `ignore_thread_affinities` is false. The pinned source defaults **`ignore_thread_affinities=true`** and **`ignore_thread_priorities=true`**. `SetPriority()` conditionally maps guest priorities to host priorities; thread creation also has flag-based priority handling. These defaults are not verified effective settings in the installed DLL.

Consequently guest CPU bookkeeping does not imply fixed host pinning. With affinities enabled, the Windows backend calls `SetThreadAffinityMask`; Proton/Wine then participates in Linux scheduling. With the default ignore setting, the logical guest CPU number alone does not restrict the host scheduler. Exact CPU masks, migrations, priorities and SMT/core placement were not captured. The app's [`rex_pin_pcores_if_hybrid()`](../src/cpu_affinity.cpp) targets Intel hybrid CPU classes and is documented as no-op on AMD; it cannot be assumed to explain this Ally behavior.

### Busy loops and blocking mechanisms verified in source

| Mechanism | Exact SDK function/path | What it establishes; what it does not |
| --- | --- | --- |
| Guest spinlock | `xeKeKfAcquireSpinLock()` in `src/kernel/xboxkrnl/xboxkrnl_threading.cpp`, around 967 | CAS retry loop calls `MaybeYield()`. It can consume CPU while making little progress. No evidence TID 7148 is in this loop. |
| Yield and small delays | `NtYieldExecution_entry()`, `KeDelayExecutionThread_entry()`; `XThread::Delay()` around 1000 | Relative durations convert to integer milliseconds; zero/sub-ms paths yield or request 100 microseconds depending on priority. Actual call frequency is unknown. |
| Windows yield/sleep | `MaybeYield()`, `Sleep()` in `src/core/threading_win.cpp`, around 87–102 | Uses `SwitchToThread` plus barrier; Sleep requests convert microseconds to integer milliseconds. A 100 microsecond request reaches `Sleep(0)`, not a guaranteed 100 microsecond sleep. Proton implementation and runtime effects are unmeasured. |
| Command starvation | [`CommandProcessor::WorkerThreadMain()`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/command_processor.cpp), around 274 | Empty command queue spins/yields, switching to 5 ms event waits after 500 iterations. This belongs to the GPU worker, not an established TID 7148 call site. |
| GPU register/memory wait | Same file, `ExecutePacketType3_WAIT_REG_MEM()`, around 1116 | Unmatched wait can yield with VSync off, or sleep for certain waits with VSync on. CPU cost may include polling. |
| Readback handoff | [`VulkanCommandProcessor::IssueCopy_ReadbackResolvePath()`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/command_processor.cpp), around 4416–4705 | Full mode waits for queue completion, invalidates mapped memory and copies to guest RAM. Delayed modes can also synchronously wait on a missing buffer. Memexport readback functions contain other waits. |

The app's [`OnPreSetup()`](../src/nhllegacy_app.h) still sets full resolve readback with a 3 MB gate from the [title patch](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch). The existing gate already removes large readbacks. Retained readbacks could stall command processing and upstream game threads; current CPU percentages cannot quantify this dependency.

### Frame pacing and guest interrupt cadence

Pinned [`src/graphics/graphics_system.cpp`](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/graphics_system.cpp), `GraphicsSystem::Setup()` around lines 154–175 creates a `GPU VSync` host worker. It uses the configured video refresh interval when `vsync=true`, but a **guest-clock interval of frequency/1000** when false, waking via a 1 ms sleep and issuing catch-up `MarkVblank()` calls. That is a nominal guest-clock cadence, not a measured physical display rate or guarantee of exactly 1000 host callbacks/s.

`MarkVblank()` increments the command-processor counter and dispatches the guest interrupt callback. `DispatchInterruptCallback()` selects guest CPU 2 and invokes the function dispatcher on the current runtime thread. The source explicitly notes a dependency between this callback and command-processor progress. This is a concrete reason to investigate pacing/interrupt workload in addition to render throughput.

The app sets VSync early and applies persisted `vsync` later; reported “off” is not independent proof of the effective SDK value. Do not change it as part of the first baseline. A later approved VSync comparison would change interrupt/wait semantics as well as presentation, so an improvement could not be attributed to display synchronization alone.

[`NhlVkCommandProcessor::IssueSwap()`](../renderer/core/nhl_vk_backend.cpp) counts returned SDK swaps. SDK `IssueSwap()` can skip presentation for async placeholder pipelines and still return. App FPS can therefore diverge from actual presentation during such periods. No captured data establishes compilation stalls or persistent skipped frames here.

## B. Why can live GPU clocks be lower with similar CPU usage?

| Competing explanation | Why compatible with current evidence | Discriminating evidence still needed |
| --- | --- | --- |
| CPU-limited feed or useful-work bottleneck | Near-one-core execution in TID 7148 plus relatively low GPU-worker CPU could starve submissions. | Map hot thread's work, queue starvation and frame cadence; ~95% CPU may be a poll loop rather than useful compute. |
| CPU/GPU power sharing | Identical CPU running time can hide different frequencies, vector instructions, cache misses and energy; APU domains share a budget. | CPU frequency/power-domain and throttle telemetry, matched frame workload. ~20 W slowPPT and 25 W target do not prove a specific allocation or cap. |
| Synchronization or lock stalls | Full readbacks and guest waits can serialize the pipeline while another thread continues spinning. GPU may downclock during gaps. | Wait attribution/timing, readback counts, scheduling delay and synchronized frame intervals. Lower clock may be consequence rather than cause. |
| Different rendering workload | Simulation and live can differ in camera, players, UI, draw counts, effects and CPU-to-GPU dependencies. GPU-heavy/memory-heavy phases need not demand the same clock. | Exact mode definition, matched camera/scene, application frame data and ultimately queue/pass timings. No FPS-based workload normalization exists yet. |
| Host scheduling contention | Similar aggregate CPU hides runnable delay, migration, core sharing, thread mix or external contention. | Allowed CPU lists, last CPU observations and schedstat deltas; no priority/affinity changes. |
| Thermal/power policy/history | Live is later and warmer; a single edge sensor does not describe all limits. | Interleaved repeated tests, stable warm-up, CPU/SoC temperatures and supported throttle status. 68 C alone proves neither overheating nor absence of throttling. |
| Pacing/interrupt coupling | VSync controls guest vblank and wait behavior; high CPU can persist with bad timing. | Synchronized presented-frame intervals and numerical simulation progression. |

The GPU may also be bandwidth- or latency-limited rather than shader-throughput-limited. Equal median DPM mclk is not a bandwidth measurement. **Neither GPU-bound nor CPU-bound is established; lower clock is an observation, not a causal explanation.**

## C. GPU utilization parser audit and narrow correction

[`gpu_sample()`](../tools/ally-profiler/ally_profiler.py) supplies scale **1** for `/sys/class/drm/card1/device/gpu_busy_percent`, and `reading()` multiplies by that scale. The old collector therefore recorded 9966 as 9966%, not 99.66 multiplied by a mistaken factor. Both logs repeatedly contain values up to 10000 at this path; 228 and 225 samples violate the percentage range. The source code and synthetic tests rule out an application-side ×100 conversion in this parser.

The [kernel AMDGPU documentation](https://docs.kernel.org/gpu/amdgpu/thermal.html#busy-percent) specifies percentage semantics. The public [AMDGPU sysfs implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/pm/amdgpu_pm.c), `amdgpu_get_gpu_busy_percent()`, retrieves `AMDGPU_PP_SENSOR_GPU_LOAD` and prints it directly. This is reference upstream code, not a verified copy of Bazzite's running kernel or its firmware path. A driver/firmware/backend unit mismatch is plausible but not proven. No evidence warrants assuming basis-point units and dividing by 100; no such normalization was added.

Minimal correction: utilization retains numeric `raw_value`; values outside inclusive 0–100 expose `value=null` and `error="Out-of-range gpu_busy_percent: expected 0..100 percent"`. Finite in-range values, including real zero and 100, remain unchanged. Missing, denied, malformed and nonfinite reads remain unavailable with their original errors. No clamping, substitution, or change to power/clock/CPU units occurs. Output-path validation and exclusive creation are untouched.

The original captures are preserved. Their utilization should be excluded from bottleneck analysis; do not average only the remaining in-range readings as if that validated this unreliable channel. The fix prevents future misuse and does not recover trustworthy utilization from these files. MangoHud may use related driver data, so it is not automatically an independent utilization reference.

## D. Smallest safe next measurement

**First measure frame pacing while retaining the exact current game configuration.** A single paired pilot can validate the setup; then repeat three interleaved pairs. No passive collection with the present invalid GPU sensor can conclusively classify CPU/GPU/synchronization/pacing on its own. Use staged evidence rather than promise a one-shot diagnosis.

1. **Desktop application-layer CSV:** establish the actual nonpersistent launch-environment route before running. Use external `MANGOHUD_CONFIGFILE`, `MANGOHUD=1`, `log_interval=0`, 120 s logging, explicit toggle key and disabled uploads. Do not change Steam launch options, prefixes or global settings. A running Steam process may not forward new environment variables; stop rather than silently assume injection worked. The exact existing launcher invocation remains an outstanding question.
2. **Pilot:** verify the CSV is application-named, has `frametime` ms and monotonic `elapsed` ns, approximately one row per presentation interval, and the intended 120 s window. [MangoHud 0.8.4 overlay](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/overlay.cpp), `update_hud_info_with_frametime()`, logs on frame updates when `log_interval=0`; [logger source](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/logging.cpp) supplies elapsed nanoseconds. Validate installed behavior; no physical scanout or simulation guarantee follows.
3. **Passive telemetry:** run the existing collector over the whole pilot and note the log-start event with UTC/monotonic time. Manual key timing only gives coarse alignment; do not infer sub-frame synchronization from filenames. Record application HUD state consistently. No frame capture is needed.
4. **Scheduling context:** for the current relevant TIDs, read allowed CPU lists and start/end schedstat counters if permitted. These distinguish recorded runqueue delay from CPU runtime, not GPU-wait reasons. Disabled/unavailable counters must remain unknown, not zero-contention evidence. [Kernel schedstat definitions](https://docs.kernel.org/scheduler/sched-stats.html#proc-pid-schedstat)
5. **Decision:** worse live frame times with normalized simulation timing establishes a presentation/throughput difference; good frame intervals but slow simulation shifts attention to guest pacing/work. Persistent hot-thread CPU does not separate work from spin. High runqueue delay points toward scheduling investigation. GPU attribution still needs a validated load/timing source. Sleeping GPU-worker plus long frames is compatible with both starvation and queue waits; focused source wait instrumentation or symbol-aware sampling would require separate approval if this remains ambiguous.

The [updated runbook](../tools/ally-profiler/README.md#next-simulation-versus-live-comparison-approval-required) includes a reviewed external-config creation snippet using `new_run()` and exclusive creation. It was documented, **not executed**. Neither the config nor a launch environment has been applied in this task. The Gaming Mode/mangoapp path remains a separate later validation; no nested Gamescope or assumed interchangeability.

Profiler commands for the approved, already-running Desktop test:

```bash
cd "$HOME/Projects/nhl-legacy-recomp" || exit 1
ps -eo pid,comm
read -r -p 'Linux PID of the already-running nhllegacy.exe: ' NHL_PROFILE_PID
python3 tools/ally-profiler/ally_profiler.py collect \
  --session desktop --pid "$NHL_PROFILE_PID" --duration 120 --interval 0.5
```

Import the resulting application CSV using its actual external path:

```bash
python3 tools/ally-profiler/ally_profiler.py analyze \
  /ABSOLUTE/EXTERNAL/PATH/nhllegacy_LOG.csv \
  --source mangohud-application --frametime-unit ms
```

Only add `--per-frame` after the pilot validates the stream. Report p50/p90/p95/p99, threshold fractions, frame count, frame-derived FPS and rejected rows. Original telemetry has no frame log to import and cannot be retroactively synchronized.

## E. Reproducible simulation versus live comparison

Define exactly what “simulation” means before the next run: a rendered CPU-controlled match, a simulation menu/mode, or a different scenario can exercise very different work. Record teams/arena/roster, camera, gameplay phase, mode, period length, difficulty, player-control method, and whether crowd/UI/replays are present. Match what can be matched and explicitly record what cannot.

Keep the supplied 25 W/720p/1×/VSync-off/FSR/shadows-off configuration unchanged. Also record actual output size, refresh/VRR/caps, AC/battery state, Proton version and background workload. No binaries/assets/settings are to be accessed or modified under this task; provenance details not already available remain unknown.

Warm up at least five minutes and establish stable thermal conditions. Run one short pilot per mode, then three 120 s simulation/live pairs in alternating order; avoid treating a later, warmer run as an independent controlled comparison. Use the same camera and uninterrupted regulation segment where possible. Predefine interruptions that invalidate a window rather than trimming unfavorable spikes afterward. Preserve numerical raw logs externally and record exclusions.

Measure normalized match-clock progress against an independent stopwatch, respecting period-length acceleration and stoppages. Add a repeatable event/animation duration if feasible. This remains a proxy for simulation updates; it does not identify the engine's actual timestep. No screenshots, asset buffers or shader captures are required.

Compare per-run frame distributions, clock distributions, labelled slowPPT, CPU rate distributions and scheduler deltas with valid-sample counts. Summarize paired differences and variation across runs. Do not combine process and thread rates, assume all 3.35 core-equivalents are critical-path work, sum power channels or substitute invalid GPU load. Lower clocks with equal CPU percentages do not mean equal CPU cycles, power, frame work or simulation progress.

## Changes and validation

Only these files are intended for the commit:

- `tools/ally-profiler/ally_profiler.py` — utilization range validation and raw numeric preservation.
- `tools/ally-profiler/test_ally_profiler.py` — two tests covering valid boundaries, fractional percentages, 101/9966/10000/negative values, malformed/nonfinite and permission failures.
- `tools/ally-profiler/README.md` — invalid-utilization interpretation and explicit Desktop pilot/comparison workflow.
- `reports/005-simulation-vs-live-bottleneck-investigation.md` — this report.
- `reports/README.md` — new index entry.

Complete synthetic suite: **22 tests pass** through `self-test` and `dry-run`, including prior home-symlink protections, exclusive output, CPU identities and CSV/statistics tests. Both Python files pass in-memory syntax compilation. Markdown local links, whitespace and staged-path allowlist are checked before commit. The numeric telemetry summary was recomputed directly using standard-library JSON/statistics and cross-checked with cumulative tick deltas; no real-time profiling was performed. Public pinned SDK and kernel/tool reference sources were read without building or applying patches.

Validation commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/ally_profiler.py self-test
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/ally_profiler.py dry-run
python3 - <<'PY'
from pathlib import Path
for path in Path('tools/ally-profiler').glob('*.py'):
    compile(path.read_text(), str(path), 'exec')
PY
git diff --check
```

No application/SDK source optimization, installation/asset modification, Steam option change, Proton-prefix change, package installation, system setting change, invasive profiler, game launch or game build occurred. Local telemetry and external configuration examples were not staged. The user's existing captures are evidence of earlier runs, not runs performed during this task.

## Outstanding questions and recommendation

- What workload does “simulation” denote, and were camera/scene/controls actually comparable?
- What guest entry/function does Linux TID 7148 execute in this installed runtime? What is TID 7090 doing?
- Are the SDK's default ignored affinity/priority settings and reported VSync state effective in the installed DLL?
- Are lower clocks caused by underfeeding, synchronization gaps, workload/power sharing, thermal policy or another mechanism?
- Which exact driver/firmware path produces the invalid utilization units? Do not repair kernel/firmware speculatively.
- What are the actual frame-time and numerical simulation-speed differences?
- Is there an approved Desktop launcher/environment route for the application MangoHud layer without Steam shortcut/prefix changes?

**Next recommended user action:** define the simulation mode and approve only the Desktop frame-log pilot/environment plan, then collect one paired simulation/live pilot with unchanged graphics/power settings and passive telemetry. Do not change readback mode, VSync, affinity, clocks or packages yet. Await further instructions after publishing this report.
