# 016 — Emulated-thread bottleneck investigation

## Executive summary

**A hot guest-execution thread is verified; a CPU bottleneck causing the freezes is not.** Linux TID **9381**, named `XThread0204 (F8` in the recording, averages **93.89% of one logical core**, versus **95.82% at the nearest samples to 11 in-capture freeze markers**. The active `GPU Commands` TID **9340** averages **34.31% overall**, **28.00% at those nearest samples**. Wider ±1-second windows preserve the quieter-command-worker pattern, but individual events and local comparisons are mixed. This supports investigating a serialized producer/consumer or synchronization dependency, not immediately optimizing the busy thread.

**The marker file contradicts the supplied count breakdown:** it contains **12 `FREEZE_RIGHT` and nine `CAMERA_CHANGE_LEFT` records**, not 11/10. The last freeze is outside coverage, leaving **11 aligned freezes and nine camera transitions**. Clock alignment is strong; scene identity is not: a camera-change press does not identify bench versus player close-up versus wide-angle, or mark how long a shot lasts.

The best next prebuilt-release diagnostic is a **short, marker-correlated, targeted thread wait-channel/state sample alongside existing CPU telemetry**, without MangoHud, attach, settings changes or rebuild. It may separate command-worker sleeping/waiting from runnable execution during a freeze. It cannot identify the hot guest function, distinguish useful execution from spinning, or prove GPU completion/image freshness. Those remain explicit limits. No further gameplay measurement is performed in this task.

## Scope, evidence inventory and validation

Branch `perf/ally-investigation`; starting HEAD `e4b3ce1075703239d1a3a14bc38283a39e0ac9f9`; origin `Grognlor/nhl-legacy-recomp`. Initially the only untracked item was local `diagnostics/`; tracked files were clean. Reviewed reports [005](005-simulation-vs-live-bottleneck-investigation.md), [007](007-cpu-codegen-optimization-audit.md), [011](011-correlated-frametime-telemetry.md), [012](012-simulation-timing-and-synchronization.md), [013](013-frame-freeze-and-catchup-investigation.md), [014](014-diagnostic-build-feasibility-and-implementation-plan.md), [015](015-prebuilt-release-performance-diagnostic-plan.md), index, collector and relevant title/runtime sources. No game/Steam/process attach or live game sampling occurred.

Evidence was read only from the three supplied local files under `diagnostics/capture-016/`: the named recording's `metadata.json` (382 bytes), `telemetry.jsonl` (3,393,063 bytes), and `scene-markers.jsonl` (2,154 bytes). All lines parse as JSON; 240 samples and 21 markers. The raw files remain local, unmodified and untracked. A repository-local `/diagnostics/` rule was added to `.git/info/exclude`; tracked `.gitignore` is unchanged. No diagnostic capture, analysis scratch file or private path is published.

| Validation | Result |
| --- | --- |
| Metadata | Desktop; requested PID 9309, duration 120 s, interval 0.5 s, tick frequency 100 Hz; no discovery errors |
| First / last sample UTC | **2026-10-22 16:25:22.195987 / 16:27:21.695929 UTC** |
| Observed sample span | **119.499939801 s**; first sample near requested elapsed zero, last at elapsed 119.500081623 s |
| Actual gaps | **0.499404277–0.500931349 s**; 240 regularly spaced samples, no missing scheduled samples evident |
| End boundary | Requested deadline approximately 16:27:22.196 UTC; no explicit shutdown timestamp. Last observed sample is the conservative alignment boundary. |
| Process coverage | 240/240 valid records; stable start tick 116929; no process/task-read errors |
| Thread coverage | 56–58 threads per sample; **64 distinct TIDs**, no observed start-tick reuse; short-lived threads can be missed |
| CPU rates | First sample null by design; 239 interval rates for persistent threads. Recomputed from tick deltas and recorded elapsed time, matching recorded rates within 1e-9 percentage points. |
| Observer work duration | Mean **10.246 ms**, median **9.852 ms**, maximum **18.380 ms** per sample; not a measured game slowdown or profiler CPU percentage |

The 100 Hz tick granularity yields roughly two percentage points per tick in a 0.5-second interval. CPU rates refer to the interval ending at a sample; state is an instantaneous, later non-atomic read. UTC, `monotonic_ns`, elapsed time and per-thread reads are not taken at one exact instant. The rate calculation uses elapsed time; replacing it with the separately read monotonic timestamp introduces tiny discrepancies and is unnecessary.

### Marker clocks and coverage

Telemetry and markers each have strictly increasing monotonic and UTC timestamps. Across both streams, the spread of `UTC_epoch_seconds − monotonic_ns / 1e9` is **less than 0.121 ms**, supporting a common host clock/time convention without a filename-based offset. Use `(marker.monotonic_ns − first_sample.monotonic_ns)/1e9` as capture-relative time. This is strong consistency evidence, not a recorded boot-ID or logger-provenance guarantee.

The final freeze is at **t=136.788030 s**, **17.288090 s after the last sample** and about 16.788 s beyond the requested deadline. Exclude it from every CPU/sensor/window comparison. Its existence is a user symptom marker, not evidence of telemetry behavior after capture. All nine camera markers are inside. The file stores event names, UTC and monotonic time, **not raw key codes**: the code-710 camera/code-708 freeze mapping is supplied by the user, not independently verifiable from these three files. No controller/InputPlumber state was inspected or changed.

Button presses have human reaction delay, possible repeated reporting of a persistent symptom, and no freeze-end duration. No scene labels identify an introduction, a bench shot, a player close-up, a replay, or a smooth reference interval. In particular **“unmarked” is not verified normal gameplay**. Rear-button tagging avoids a required focus switch, but overhead and exact event-observer implementation are not recorded here.

## Exact recorded thread identities and utilization

All numbers below are percent of **one logical core**; never add process and thread totals. Names are the exact truncated Linux comm values, not complete runtime names. TIDs are historical Linux IDs and **must not be reused as current process selectors**. `0204` is not a Linux TID, Xbox CPU index, guest function address or established NHL subsystem.

| Linux TID | Recorded comm | Mean CPU | Maximum CPU | Sampled states R/S/D (240 observations) |
| --- | --- | ---: | ---: | --- |
| 9381 | `XThread0204 (F8` | 93.89% | 100.00% | 227/12/1 |
| 9329 | `nhllegacy.exe` | 61.87% | 66.00% | 25/215/0 |
| 9340 | `GPU Commands (F` | 34.31% | 68.01% | 99/140/1 |
| 9380 | `XThread0200 (F8` | 23.71% | 34.00% | 89/151/0 |
| 9372 | `XThread01F0 (F8` | 21.09% | 56.00% | 68/172/0 |
| 9376 | `XThread01F4 (F8` | 15.38% | 36.00% | 58/182/0 |
| 9378 | `XThread01F8 (F8` | 15.33% | 32.00% | 58/182/0 |
| 9379 | `XThread01FC (F8` | 15.30% | 34.00% | 51/189/0 |
| 9325 | `rex::thread::Ti` | 11.72% | 20.00% | 45/195/0 |
| 9341 | `GPU VSync (F800` | 1.95% | 4.00% | 26/213/1 |
| 9309 | `nhllegacy.exe` | 7.05% | 14.00% | 74/166/0 |

Whole-process mean CPU is **319.46%**, separate from the main Linux thread TID 9309's **7.05%**. TID 9381 accumulated **112.20 CPU seconds** over 119.50 wall seconds; the active CP candidate TID 9340 accumulated **41.00 CPU seconds**. The hot thread is at least 90% in **216/239** intervals; its range is **62.00–100.00%**. This is sustained high occupancy, not literal continuous execution: waits/preemption/yields occur, and tick-level averages hide short stalls.

There is also a separately named `Main XThread (F`, TID **9362**, with no tick increase during this capture. Calling TID 9381 “the main game/simulation thread” is unsupported. Seven TIDs initially share the truncated `GPU Commands (F` name: **9340, 9348, 9349, 9350, 9351, 9353, 9369**. TID 9340 is the active worker candidate, selected by activity and matching source role, not by name alone. One initially present `Vulkan Pipeline` TID **9352** has **zero tick increase** throughout; this does not exclude synchronous driver/pipeline work on another thread.

## Timestamp-aligned freeze analysis

Primary event windows include all valid interval-rate samples whose **ending timestamp lies within ±1 s** of a freeze press; each event has four samples, 44 distinct samples total. This avoids overreliance on one quantized sample. The CPU intervals extend approximately another 0.5 s before their ending timestamps, and reaction latency is unknown. These are event neighborhoods, not measured freeze durations. Sensor values are means of the same selected samples, not synchronized GPU events.

Nearest-sample selection reproduces the supplied **95.8% hot / 28.0% CP** figures: **95.817% / 27.999%**, maximum marker-to-nearest-sample distance 0.231 s. The broader-window result is **95.364% / 27.682%**. Neither statistic proves causality.

| Freeze | Relative seconds | Process CPU | Hot 9381 CPU | CP 9340 CPU | sclk MHz | edge °C | slowPPT average W | Seconds since previous camera |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| F1 | 18.870 | 302.5% | 95.0% | 26.5% | 1160 | 68.75 | 18.244 | No prior marker |
| F2 | 32.133 | 257.0% | 97.0% | 27.0% | 1160 | 67.50 | 16.780 | 2.095 |
| F3 | 35.886 | 275.0% | 95.5% | 40.0% | 1160 | 66.25 | 17.866 | 0.502 |
| F4 | 39.164 | 261.0% | 95.0% | 29.5% | 1044 | 67.00 | 19.338 | 3.781 |
| F5 | 44.348 | 263.5% | 96.5% | 29.0% | 920 | 66.75 | 19.242 | 4.101 |
| F6 | 47.769 | 309.0% | 94.5% | 20.0% | 738 | 68.50 | 19.914 | 7.523 |
| F7 | 52.562 | 306.5% | 97.0% | 20.0% | 630 | 66.75 | 19.968 | 1.218 |
| F8 | 59.110 | 303.0% | 94.5% | 25.5% | 898 | 66.75 | 18.845 | 2.586 |
| F9 | 62.513 | 304.0% | 96.5% | 29.5% | 1135 | 66.50 | 17.851 | 2.245 |
| F10 | 81.571 | 347.5% | 95.0% | 30.0% | 915 | 67.50 | 20.031 | 8.577 |
| F11 | 92.160 | 335.0% | 92.5% | 27.5% | 715 | 67.25 | 20.360 | 2.117 |

### Aggregate comparison and robustness

| Group | Samples | Process CPU | Hot 9381 CPU | CP 9340 CPU | Guest 9372 CPU | Guest 9380 CPU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All valid intervals | 239 | 319.46% | 93.89% | 34.31% | 21.09% | 23.71% |
| ±1 s freeze neighborhoods | 44 | 296.73% | 95.36% | 27.68% | 13.59% | 23.27% |
| Remaining unmarked samples | 195 | 324.58% | 93.56% | 35.81% | 22.78% | 23.81% |
| Unmarked after first 10 s excluded | 175 | 328.71% | 94.63% | 33.01% | 23.70% | 24.74% |

The hot-minus-unmarked difference shrinks from **1.80 to 0.74 percentage points** when excluding the distinctive first ten seconds, during which hot occupancy is lower and CP work/clock/temperature higher. Every freeze occurs after that early interval. After excluding the first 20 s, the hot comparison is **95.40% versus 94.90%**. **The apparent hot-thread increase is weak and baseline-dependent**, whereas quieter CP/9372 work remains descriptive across these cuts. This directly cautions against attributing freezes to the hot thread merely approaching 100%.

Window sensitivity (union of event neighborhoods; overlaps counted once):

| Half-width | Freeze-neighborhood samples | Hot CPU / unmarked | CP CPU / unmarked |
| --- | ---: | --- | --- |
| 0.5 s | 22 | 95.18 / 93.76% | 27.73 / 34.98% |
| 1 s | 44 | 95.36 / 93.56% | 27.68 / 35.81% |
| 2 s | 84 | 95.38 / 93.09% | 28.50 / 37.46% |

This is one autocorrelated recording with subjective labels and changing scenes, not independent trials or a significance test. Local pre-event comparison is also mixed: CP means in `[t−3,t−1)` versus `[t−1,t+1]` fall at **7/11** events, but rise at four. F3 has **40% CP**, above the whole-run 34.31%; F6/F7 are near **20%**. A lower CP rate is therefore not a necessary freeze signature, and may precede/follow the reported event rather than cause it.

### States and context switches

Within ±1 s neighborhoods, hot states are **40 R / 3 S / 1 D**, CP **15 R / 28 S / 1 D**. Outside, hot is **187 R / 8 S**, CP **83 R / 112 S**. R includes executing **or runnable**, S does not name a lock, D does not identify the device. These are snapshot counts, not time fractions in each state. At **t≈47.000 s**, hot, CP, VSync and another guest thread are all observed D, about **0.769 s before F6**. That shared observation deserves a wait-channel follow-up but is a single sample, not a measured 0.5-second wait or established GPU stall.

Context-switch rates use adjacent cumulative-counter differences divided by recorded interval duration:

| Thread / group | Voluntary switches/s | Involuntary switches/s |
| --- | ---: | ---: |
| Hot: all / freeze neighborhoods / unmarked | 816.74 / 417.19 / 906.90 | 277.52 / 211.05 / 292.52 |
| CP: all / freeze neighborhoods / unmarked | 1155.52 / 723.14 / 1253.08 | 199.09 / 167.37 / 206.25 |

No general rise in preemption-count rate accompanies freezes. Lower switch counts can reflect fewer cycles through a wait/yield loop, longer waits, different work or other changes; they do not measure runnable delay or identify synchronization owners. All-run hot maxima are **3746 voluntary/s**, **1042 involuntary/s**; individual anomalies exist, but no consistent causal spike is established. High CPU plus frequent switches is compatible with useful execution and with repeated polling/yielding. Neither can be distinguished here.

## Camera-transition analysis

Each camera marker is compared with two-second pre/post windows by sample-ending timestamp, four samples per side. These are transitions of **unknown camera type**, not complete scene segments. Results:

| Camera | Relative seconds | CP CPU pre → post | Hot CPU pre → post |
| --- | ---: | --- | --- |
| C1 | 30.038 | 34.5 → 29.0% | 95.5 → 97.0% |
| C2 | 35.383 | 32.0 → 39.5% | 96.5 → 95.5% |
| C3 | 40.247 | 29.5 → 25.5% | 95.0 → 97.0% |
| C4 | 51.344 | 21.5 → 20.5% | 95.0 → 97.0% |
| C5 | 56.523 | 23.5 → 27.5% | 94.5 → 94.5% |
| C6 | 60.268 | 25.5 → 29.0% | 94.5 → 96.5% |
| C7 | 72.995 | 37.5 → 49.0% | 95.0 → 94.0% |
| C8 | 90.043 | 26.0 → 27.5% | 95.0 → 92.0% |
| C9 | 100.647 | 28.5 → 35.0% | 96.5 → 96.0% |

Pooled pre/post process CPU is **304.72/304.89%**, hot **95.28/95.50%**, CP **28.72/31.39%**. CP increases at six transitions and decreases at three. No uniform guest-CPU surge or command-worker stall follows all camera changes. Six freezes occur within three seconds of a preceding camera marker; eight within five seconds. Other freezes are 7.52/8.58 seconds later or have no preceding marker. Without scene types, duration and complete reporting, this is temporal proximity, not proof that close-ups caused them.

Bench/player close-ups remain the highest-priority **user-reported** problem. This capture cannot independently label their workload or compare them with verified wide-angle intervals. Do not equate every camera marker with a close-up or assume alternating camera states. Introduction coverage is also unknown.

## GPU, power and thermal observations

All 240 samples provide valid numeric hwmon temperature, sclk and the two labelled slowPPT power readings. GPU utilization is invalid as a source: **221/240 values are rejected out of range**, including 9999–10000; the remaining 19 nominally in-range values do not validate it and are also excluded from GPU-load conclusions. No scaling/clamping/substitution is applied.

| Sensor | All 240 samples: mean / median / range | ±1 s freezes / unmarked means (valid CPU-aligned samples) |
| --- | --- | --- |
| hwmon sclk | **983.85 / 1160 / 200–1800 MHz** | **952.27 / 987.53 MHz** |
| edge temperature | **68.7958 / 68 / 64–81 °C** | **67.23 / 69.10 °C** |
| slowPPT `power1_average` | **19.2003 / 19.7955 / 16.100–21.428 W** | **18.949 / 19.253 W** |
| slowPPT `power1_input` | **19.8250 / 19.8675 / 9.877–30.063 W** | **19.942 / 19.767 W** |

Thus the preliminary **68.8 °C** mean is confirmed. The two slowPPT channels are different readings of a labelled power domain, **not separate CPU/GPU budgets or GPU-only power**, and must not be added. Active DPM-state values are separately labelled, not instantaneous clock measurements. Nominal 25 W settings are not independently verified by this metadata.

Freeze neighborhoods span both high and low clocks (e.g. F1/F2/F3 at 1160 MHz mean; F7 at 630 MHz). There is no common clock collapse or thermal/power extreme across all freezes. The first ten seconds are hotter (**77.9 °C mean**) and faster-clocked (**1614.1 MHz mean**) than the later freeze neighborhoods; this is a baseline confound, not proof of thermal throttling. After removing those ten seconds, unmarked sclk is **915.92 MHz**, below the freeze-neighborhood **952.27 MHz**: even the sign of the aggregate clock difference reverses. CPU clocks, throttle reason counters, valid GPU busy time and GPU completion latency are absent. Do not rank overheating, power sharing or GPU saturation as diagnosed causes.

## Source-level findings and CPU/GPU synchronization

Public runtime sources were freshly retrieved for read-only review at SDK pin **`bd9b51918faa71f962fa38af6d5f744af9aba2ce`**, not built or installed; old temporary research caches were absent. [SDK setup](../scripts/setup_sdk.ps1), lines 12–24, pins it and selects the title patch. Source behavior below is verified for that revision/checked-in application, **not proven effective behavior of the downloaded binary**. Producer build settings/codegen remain unknown (reports 007/008/014).

| Source and function, line ranges | Confirmed mechanism | Interpretation for this capture |
| --- | --- | --- |
| [xthread.cpp][thread], `XThread::Create`, **435–479**; `set_name`, **175–182**; [threading_win.cpp][win], `Win32Thread::system_id`, **375–376** | Host thread binds its guest state and calls `Execute`; default name formats host `system_id()` in hex, Win32 `GetThreadId`. Runtime appends an object-handle suffix. | `0204` corresponds to Windows host naming, not Linux TID 9381 or emulated Xbox thread/CPU number. Full handle and guest entry are not recoverable from truncated comm. |
| [xthread.cpp][thread], `Execute`, **571–650** | Selects startup trampoline/start address and passes guest args through PPC context to registered ahead-of-time translated function; host fiber/runtime state participates. | A host thread executing guest functions, not evidence of interpreter/JIT overhead. No entry-address log, generated code or stack identifies this NHL subsystem. |
| Same, defaults **40–44**, `SetPriority` **837–858**, `SetActiveCpu` **880–903** | Ignore guest priorities/affinities default true; guest CPU metadata updates do not necessarily host-pin. Creation flags can separately set a host priority (**473–475**). | Do not assume a guest-to-core pin, a six-thread fixed scheduler or unchanged priority. Installed overrides/masks/priority and Wine scheduling are unmeasured. |
| Same, `Delay`, **1000–1038**; [Win32][win], `MaybeYield/Sleep`, **87–101** | Relative guest waits truncate to ms; zero timeout can yield; Win32 `MaybeYield` invokes `SwitchToThread` and a memory barrier. | Busy/yield behavior is possible; high occupancy does not locate it in TID 9381 or prove its inefficiency. |
| [command_processor.cpp][cp], `Initialize` **139–146**, `WorkerThreadMain` **274–323**, `UpdateWritePointer` **404–407** | Named `GPU Commands` host thread drains queued callbacks/PM4 batches. Empty ring spins/yields; after >500 loops waits up to 5 ms. Guest-visible read pointer written after executing batch. | Quiet CP may mean no commands, CPU synchronization or GPU waits; 34% mean is not submission latency or 66% idle headroom. Blocking a batch can delay guest-visible progress. |
| Same, `ExecutePacketType3_WAIT_REG_MEM`, **1116–1190** | Polls guest/register condition, yields when unmatched with VSync off rather than necessarily sleeping. | Additional CPU can be polling rather than useful rendering; no packet counters in this recording. |
| [graphics_system.cpp][graphics], `Setup` **153–180**, `MarkVblank` **328–340**; [function_dispatcher.cpp][dispatch], `ExecuteInterrupt` **130–160** | GPU VSync host worker uses guest clock; VSync-off nominal interval is 1 ms, with catch-up calls and ~1 ms sleeps. Interrupt executes under global critical region. Source notes CP dependency on interrupt work. | Timer/lock/CP coupling is real in source. VSync TID 9341 mean 1.95% and switch activity do not measure callback count, lock duration or true interrupts/s. No setting changes justified. |
| [clock.cpp][clock], `UpdateGuestClock` **66–89**, `QueryGuestTickCount/SystemTime/Uptime` **158–175** | Guest time advances from host ticks with scaling, not from present count. | Match clock can keep advancing while animation-bearing work is delayed; actual NHL animation/physics timestep and catch-up policy remain unidentified. |
| [Vulkan command processor][vk], `IssueSwap` **2285–2437/2920–2943**, fence checks **4979–5050**, `BeginSubmission/EndSubmission` **5127–5196/5265–5494** | Frame-slot reuse, submit, queue and completion waits can block CP; multiple submissions per frame. | A low CPU CP may be waiting on GPU/resources or guest work. No submission/fence evidence chooses one here. |
| [Vulkan presenter][present], `PaintAndPresentImpl` **1497–1541/2196–2210** | Waits for paint resources, acquires swapchain image with unlimited timeout, presents under queue acquisition. | Presentation can create backpressure; `vkQueuePresentKHR` return is not physical display timing. Current capture has no present stream. |
| [nhllegacy_app.h](../src/nhllegacy_app.h), **196–219**; [title patch](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch), **357–425** | Equipment/player maps use runtime EDRAM composites; full resolve readback is selected and large reads are size-gated. Retained full reads can drain GPU before CPU copy. | A concrete recurring synchronization candidate, but comments about prior performance are historical claims, not measurements here. No readback counts, scene attribution or installed gate verification. Do not disable readback. |
| [nhl_vk_backend.cpp](../renderer/core/nhl_vk_backend.cpp), `IssueSwap`, **230–277** | Calls SDK swap, then updates swap/draw statistics and approximately one-second log/HUD. | Existing source offers coarse CP-progress evidence if already logged, not simulation or distinct image IDs. No existing game log was accessed. |

Presenter mailbox reuse/replacement and UI repaint possibilities from Report 013 remain relevant: many presentations can expose unchanged guest output. No supplied record tracks mailbox generations or pixels. Source permits coupling between guest generation, CP, GPU and presentation, but **which stage is limiting is not measured**. A camera change may alter animation/camera CPU work, draws/states, equipment composites, residency/uploads or pipelines; none is mapped to these marker events. Do not assume close-ups increase polygons or that shader compilation causes them.

## Competing hypotheses, ranked by diagnostic value

Confidence below is confidence in **causal attribution**, distinct from confidence in the observed pattern.

| Rank / candidate | Support | Contrary/missing evidence | Confidence; confirming/rejecting measurement |
| --- | --- | --- | --- |
| 1. Serialized guest/CP dependency or synchronization/backpressure | Hot thread stays near one core while CP/9372 often quiet around freezes; source has guest ring/interrupt/fence dependencies and retained readbacks. | CP increases at some events; no ring occupancy, wait identity or completion times. Serial useful work, polling and downstream waiting all fit. | **Moderate as a broad family; low for any specific lock/stage.** Target wait-state observations first; internal progress/wait or nonintrusive execution profiles would later narrow attribution. |
| 2. Guest execution saturation (useful work or polling) | 112.2 CPU seconds/119.5 s on one guest thread, mostly R; higher occupancy at many freeze markers. | High during unmarked intervals too; difference nearly vanishes with early-phase controls. Guest function/usefulness unknown. Other workers may gate it. | **Low–moderate contributor, low sole-cause confidence.** Matching CPU instruction/stack samples or a producer entry/hotspot map, acquired only with approval, needed to distinguish compute from spin; no affinity/codegen change justified. |
| 3. GPU rendering/completion or synchronous readback | Concrete blocking source paths; lower CP CPU compatible with waits; severe close-ups and FSR user observations motivate it. | Invalid utilization, no GPU completion or timed readbacks; low/high clocks both occur at freezes. | **Low–moderate plausibility, not diagnosed.** Repeated driver/fence wait channels would justify a targeted completion/readback investigation, not prove GPU saturation. |
| 4. Presentation/freshness/frame pacing | Old recording has long/short present bursts; mailbox can reuse output, and current freeze/catch-up fits delayed visibility. | No current frame-time/image-identity stream; old footage-free recording cannot be scene-aligned to this session. | **Low causal confidence, still viable.** CPU waits alone cannot reject; needs non-Mango existing producer/presentation evidence or later internal lineage from producer. |
| 5. Host scheduling starvation | R can be runnable; Linux/Wine scheduling and priority could delay progress. | High hot on-CPU occupancy; no general rise in involuntary switch rate; no run-queue delay, CPU frequency, affinity or system load recorded. Current `sched_schedstats` read remains **0**. | **Low, weak positive support.** Enabled-and-validated runnable-delay trace would distinguish it, but changing accounting/installing tools/privileged tracing is not authorized or proposed now. |
| 6. CP CPU submission saturation | CP may burst on draw/pipeline/resource work; camera transitions sometimes increase it. | Whole mean 34.31%, peak 68.01%, freeze mean lower; CPU utilization alone misses short serial bursts. | **Low for sustained CP computation saturation.** CP execution-site sampling and submission intervals needed; current capture cannot reject burst bottlenecks. |
| 7. Simulation time-scaling fault / camera-specific workload | Freeze/catch-up reported; guest timing and animation can be decoupled, camera changes alter work. | No actual step function, step counter, scene identity/duration or controlled clock comparison. No uniform hot-CPU camera surge. | **Unknown/low for a global clock fault; scene workload remains plausible.** Need independently identified simulation/animation progress and typed scenes. Do not infer healthy simulation from the match clock or FPS. |

These are overlapping candidates, not mutually exclusive probabilities. Current most defensible explanation is **intermittent progress/freshness loss somewhere in a coupled pipeline**, with a consistently busy guest thread as a possible contributor rather than an identified root cause. Neither temperature nor an invalid GPU percentage supports choosing CPU-only optimization or a GPU-only fix.

## Recommended next diagnostic — targeted wait-state comparison

**One approved 60-second passive thread-state/wait-channel run, with the existing collector and unchanged rear-button markers**, prioritizing naturally occurring bench/player close-ups versus wide-angle play. Add human notes assigning camera events to `wide`, `bench`, `player-closeup`, `replay` or `unknown`; no controller remap or new button action. This adds a missing measurement (wait category), rather than repeating CPU averages alone. If the already available marker logger cannot continue unchanged, stop and request its documented procedure; do not invent or reconfigure it.

No rebuild, restart, MangoHud, debugger, ptrace, package, root privilege or settings change is required **in principle**. `ps` availability and scheduler policy were rechecked, not game-process access. Wait-channel visibility for the current game is unverified. If permission is denied or all channels stay unknown, **stop rather than elevate**. The next capability would require a separate approved profiling plan. Installed `perf`/`pidstat` were not found on PATH; no intrusive stack sampling is proposed as an immediate command.

### Minimal procedure (design only; not executed)

1. Only use an already-running, separately approved match. Reconfirm the current Linux PID by `ps` name; never reuse recorded 9309. If no game is running, stop; launch needs approval.
2. Use `ps -L -p "$NHL_PROFILE_PID" -o tid=,comm=,stat=,wchan:32=` once to identify current thread names and test access. Multiple GPU Commands names exist. Use the existing profiler's interval deltas to select the current hot guest TID and active CP candidate; never infer them from this report's historical TIDs. No exposed useful channel means no assured diagnostic benefit.
3. Start existing `ally_profiler.py collect --session desktop --pid "$NHL_PROFILE_PID" --duration 60 --interval 0.5`. It creates its own unique private output directory outside the playable installation. Preserve its output protections.
4. In a second terminal, perform a bounded **five-Hz** `ps -L` state/wchan loop, retaining only the two explicitly identified TIDs in its output; add host monotonic/UTC timestamps. This external sampler is **not implemented by this task**. Before execution, review its PID/start-tick validation, exclusive private file creation, deadline/exit handling and measured collection overhead. Do not substitute a persistent service, global trace, attachment, process stack read or system setting change. Current collector lacks wchan fields, so simply rerunning it will not add this evidence.
5. Retain the established rear-button marker mechanism unchanged; make scene-type notes keyed to camera-event order/time. Prefer an observer, and mark any focus interruption. No camera/settings changes to manufacture a scene. Capture natural close-ups; intro optional, never restart a match for it.
6. End at 60 s or immediately if observation worsens performance, PID changes/exits, permissions fail or output isolation fails. Stop collectors only; leave NHL/Steam running. Ctrl-C preserves existing profiler partial output. No runtime configuration needs rollback. Do not automatically repeat if no close-up occurs.
7. Offline compare ±1 s marker neighborhoods, 0.2 s state/wchan sequences, CPU deltas and typed scene durations against neighboring unmarked same-scene intervals. Report unknown channels and reaction latency; do not count snapshot hits as wait duration. Keep raw outputs local.

**Interpretation:** sustained CP sleeping with a named driver/fence-related wait would shift attention toward the GPU/driver path; a generic futex would establish only a broad host wait, not which SDK lock. Persistent R plus CPU execution points toward computation/polling but cannot distinguish them. A busy hot thread and repeatedly sleeping CP are consistent with both command starvation and downstream synchronization, so futex-only results remain ambiguous. Concurrent sampled D in multiple threads with a shared exposed category would make the isolated F6 observation more actionable. If motion freezes while these categories remain unchanged, this test has reached its limit: do not declare presentation or simulation healthy.

Sampling five times/s can miss sub-200 ms stalls and changes the observer workload; expected overhead is modest but **not measured**. Filtered output should be bounded (~300 timestamps/two-thread snapshots plus ~120 telemetry samples). No hard maximum byte guarantee is claimed without a reviewed collector. A safely implemented, bounded external reader is a prerequisite to step 4, not permission to patch the game or an artifact delivered here. Budget about **5–10 minutes preparation plus one minute capture**, after separate approval. No installed file is touched. If exact software hotspot attribution becomes essential, seek authorization for a tool/permission feasibility review or request sanitized producer diagnostics; do not silently switch to gdb/perf or rebuild.

## Confirmed findings, unresolved questions and validation

**Confirmed measurements:** preliminary overall hot/CP/temperature means and nearest-freeze CPU figures; correct 12/9 marker breakdown with one freeze excluded; stable same-host clock alignment; sustained hot-thread occupancy; lower aggregate CP/9372 activity around reported freezes; no general switch-rate surge or common power/clock/thermal collapse. Baseline-phase sensitivity makes the hot-thread event increment weak.

**Unresolved:** actual guest function/entry and useful work versus polling; CPU starvation versus waits; exact lock/driver dependency; GPU completion/load; CP progress and mailbox freshness; animation/input steps; physical display delivery; scene identity; installed SDK/codegen flags. Human freeze presses are not per-frame timestamps or durations. Similar displayed clock rates from a different session do not establish animation health here. No old MangoHud stream is synchronized to this capture.

All analysis was offline; evidence files were hashed before/after to verify preservation, parsed/schema-checked, clock/counter identities checked, CPU independently recomputed and window sensitivity/local controls examined. The scratch analysis is outside the repository; only sanitized aggregate tables are published. Existing **32 synthetic profiler/analyzer tests pass**. Local Markdown links/source references, shell syntax where applicable, whitespace and final staged allowlist were checked. Only this report and the running report index are committed. `diagnostics/` is locally excluded, no diagnostic files are tracked or staged, and no source/tool/runtime changes occurred. Public SDK reads do not establish binary provenance.

**Next user action:** approve the bounded external wait-channel sampler preparation and one 60-second typed-scene comparison, or supply matching already-existing sanitized producer thread/swap logs. No performance fix is authorized by these findings. Stop after publishing Report 016.

[thread]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xthread.cpp
[win]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/threading_win.cpp
[cp]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/command_processor.cpp
[graphics]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/graphics_system.cpp
[dispatch]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/function_dispatcher.cpp
[clock]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/clock.cpp
[vk]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/command_processor.cpp
[present]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/ui/vulkan/vulkan_presenter.cpp
