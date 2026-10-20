# 012 — Simulation timing, frame pacing and thread synchronization

## Executive summary

The target is consistently responsive hockey, not maximum FPS. Source review identifies **real routes for presentation delays to block command processing and potentially guest progress**, without establishing NHL's simulation timestep or the cause of the current slowdown.

The strongest new limiter lead is specific: **the SDK holds a Vulkan queue mutex while calling `vkQueuePresentKHR`; MangoHud sleeps inside its intercepted present call**. Presentation prefers the graphics/compute queue. When that queue is shared with rendering, a limiter sleep can hold up command submissions even when presentation runs on the UI thread. Direct command-worker presentation adds another blocking route. These are confirmed source mechanisms; their contribution in the installed executable is unmeasured. A 60 FPS external cap is not a verified simulation-rate fix and should remain disabled.

The SDK guest clock advances from host time, independently of presentation. Guest **progress**, however, can depend on command completion, locks, interrupts and waits. The pinned VSync-off vblank worker requests nominal 1 ms guest-clock callbacks, not 60 Hz. No checked-in NHL simulation loop proves whether gameplay uses fixed steps, variable deltas, catch-up, clamping or frame-count progression. High presentation FPS can therefore coexist with slow simulation or stale visible output, but that coexistence has not yet been quantitatively demonstrated for current play.

Arena introductions and close-ups are now the primary stress cases. Their content-specific cost is plausible in resource uploads, draw/pixel work and retained synchronous readbacks, but no source-to-scene attribution or intro trace exists. Do not default to shader compilation: the prior warm gameplay capture's named compilation workers were idle, though it did not measure introductions.

**Next experiment:** one uncapped progress-versus-presentation observation covering introduction and active play, keeping the preferred settings, measuring game-clock and visible-motion progression against wall time alongside frame intervals and passive telemetry. No rebuild or experimental timing change is necessary. The old ten-second slideshows are no longer the reproduction target.

## Scope, provenance and evidence categories

Verified repository `Grognlor/nhl-legacy-recomp`, origin URL, branch `perf/ally-investigation`, initially clean, starting HEAD `43e2ab95600dbb96fc2c8d073fb372861a649cba`. Reviewed reports [005](005-simulation-vs-live-bottleneck-investigation.md), [006](006-sonic-unleashed-architecture-comparison.md), [007](007-cpu-codegen-optimization-audit.md), [009](009-mangohud-frametime-profiling-plan.md), [011](011-correlated-frametime-telemetry.md), index, collector/importer and offline analysis. Earlier report 008's missing producer artifacts remain relevant.

- **Confirmed source (S):** current tracked application/patch source and public ReXGlue pin `bd9b51918faa71f962fa38af6d5f744af9aba2ce`, plus tracked title/scanner patches. Public MangoHud **v0.8.4** source corresponds to the previously verified installed version label, not independently verified distribution patch contents.
- **Measured (M):** report 011's existing uncapped rendered AI-match capture/aggregates, not the new cap test.
- **User observation (U):** new introduction/close-up, FSR and cap comparisons, not instrumented A/B measurements.
- **Hypothesis (H):** causal links from those mechanisms to gameplay/input responsiveness. Installed codegen/runtime provenance remains unverified; source support does not prove a path executed in the user's run.

No new raw recording, installed executable, asset, prefix, Steam shortcut/configuration, shader cache or memory was inspected. Public SDK sources were fetched to `/tmp` only. No game/Steam start/stop, build, runtime modification or optimization was performed. Only this report and index change.

## Incorporating the new gameplay evidence

| User observation | Implication for investigation | Limit / competing explanation |
| --- | --- | --- |
| Sustained slideshow episodes have stopped occurring | Retire report 011's old episode-reproduction recommendation as the immediate priority. Study persistent choppiness, slowdown and input timing. | Old recordings remain valid historical evidence, not a current symptom definition. |
| Arena introductions are consistently worst; close-ups also bad | Include intro entry/camera transitions in the next observation, not just a warmed broad gameplay view. | No event timings, work counters or trace map those scenes to specific costs. |
| FSR Ultra Performance helped modestly | Presentation/render-related work or its dependencies may matter. | Does not identify GPU saturation or prove original guest draws used fewer pixels; see the FSR distinction below. |
| `fps_limit=60` plus MangoHud launch environment made the game broadly slower | Investigate present-path blocking and guest completion dependencies first. | Exact cap config, limiter method, overlay/logging work, other config fields and scene/warm-up conditions were not inspected or controlled. |
| Removing MangoHud launch options immediately improved play, to “almost playable” | Strong user-observed intervention/reversal supports a launch-environment or limiter interaction. | It removed injection/config selection as well as the cap. It does not isolate `fps_limit` alone or prove a MangoHud defect. |

Preserve current preference: **uncapped, VSync off, FSR Ultra Performance, approximately 720p, 1× supersampling, shadows off and nominal ~25 W**. The latter resolution/power assumptions are historical and not freshly verified. No setting is altered or recommended for immediate alteration here.

## Simulation and presentation architecture

### Clock time is not completed simulation work

[S] ReXGlue `src/core/clock.cpp`, `UpdateGuestClock`, lines **66–89**, derives guest ticks from host tick deltas and a frequency/scaling ratio; guest scalar initializes to **1.0** at **27–29**. `QueryGuestTickCount`, `QueryGuestSystemTime`, `QueryGuestUptimeMillis`, **158–175**, expose guest tick/system time. A present count does not advance that clock. `include/rex/chrono/clock.h` declares these interfaces. [R-clock], [R-clock-h]

[S] Codegen `src/codegen/builders/system.cpp`, `build_mftb`/`build_mftbu`, **266–277**, emits `REX_QUERY_TIMEBASE`; the generated helper maps to `Clock::QueryGuestTickCount` as verified in report 007. Kernel `KeQueryPerformanceFrequency_entry`, `KeDelayExecutionThread_entry`, `NtYieldExecution_entry`, `KeQuerySystemTime_entry`, `src/kernel/xboxkrnl/xboxkrnl_threading.cpp`, **371–402**, use the runtime clock/delay/yield interfaces. [R-system], [R-kernel]

[S] `XTimer::SetTimer`, `src/system/xtimer.cpp`, **40–86**, scales due time/period and uses host timers, queuing an APC for a guest callback when supplied. `XThread::Delay`, **1000–1038**, converts relative guest 100 ns units to integer milliseconds and either sleeps or yields. Windows `threading_win.cpp`, `MaybeYield`/`Sleep`, **87–102**, uses `SwitchToThread`/barrier and integer-millisecond `Sleep`; a requested 100 microseconds becomes `Sleep(0)`. These operations need not mean useful simulation work. [R-timer], [R-thread], [R-win]

**Unknown:** NHL's actual physics/animation/game-clock timestep, frame catch-up policy, timer usage frequency and input consumption cadence. The generated game implementation is absent, and the tracked native application does not supply an identifiable replacement simulation-step loop. This inspection cannot label NHL as fixed- or variable-step. No assumption of one guest update per swap, or of a particular required present rate, is justified. Report 007's unknown effective codegen flags do not change that limitation.

[H] A blocked guest loop can execute fewer updates per wall second even though host-derived guest time keeps advancing. Whether NHL catches up, clamps delta, waits for a fence or slows animation is game-code dependent. Conversely a game clock based on wall time may advance normally while animation/control updates lag. Measuring only FPS **or only the match clock** is insufficient for that case.

### Guest vblank and interrupt cadence

[S] `GraphicsSystem::Setup`, `src/graphics/graphics_system.cpp`, **153–180**, starts an `XHostThread` named `GPU VSync`. It derives a video-refresh interval, but when `vsync=false` selects `guest_tick_frequency / 1000`, runs catch-up `MarkVblank()` calls and sleeps ~1 ms. This is nominal guest-clock cadence, not guaranteed measured host wake frequency. [R-graphics]

[S] `MarkVblank`, **328–340**, increments the command-processor counter and dispatches the interrupt. `DispatchInterruptCallback`, **306–326**, calls `FunctionDispatcher::ExecuteInterrupt`; that function, `src/system/function_dispatcher.cpp`, **130–160**, acquires the global critical region while executing interrupt work. The `MarkVblank` source explicitly records a historical dependency: the command processor can wait for code that needs to run in the interrupt. That comment is evidence of intended synchronization concerns, not proof of the present bug. [R-graphics], [R-dispatch]

The key distinction: **VSync off and a host 60 FPS limiter leave different timing controls in effect**. Nothing in the inspected MangoHud code changes ReXGlue's guest-time scalar or vblank selector. [H] Blocking presentation can nevertheless delay threads/queues needed by guest progress while the vblank timer continues to request callbacks. Excess interrupt/lock contention or catch-up may add load; actual callback counts/lock durations are unknown. Changing VSync now would change several semantics at once and is not proposed.

### Command stream to host painting

[S] `VdSwap_entry`, `src/kernel/xboxkrnl/xboxkrnl_video.cpp`, **428–510**, writes a swap packet into the guest command buffer. This hook itself does not impose a 60 Hz simulation step. `CommandProcessor::ExecutePacketType3_XE_SWAP`, **1067–1102**, executes `IssueSwap` on the command worker and increments its counter afterward. [R-video], [R-cp]

[S] NHL `NhlVkCommandProcessor::IssueSwap`, `renderer/core/nhl_vk_backend.cpp`, **230–272**, forwards to SDK swap and then counts/times swaps. It is a command/swap metric, not a simulation-update counter. SDK Vulkan `IssueSwap`, **2285–2437**, resolves the swap texture and calls `Presenter::RefreshGuestOutput`. [N-vk], [R-vk]

[S] `Presenter::RefreshGuestOutput`, **553–650**, uses a three-image mailbox and can replace a pending image instead of queueing every guest image. It either requests a UI paint or directly calls `PaintAndPresent` from the guest-output thread. `GetDesiredPaintModeFromUIThread`, **1310–1333**, chooses UI painting for UI drawers, implicit VSync or disabled non-UI presentation; otherwise immediate guest-output-thread painting. `PaintFromUIThread`, **422–518**, may repaint because of UI/forced requests, not a new game update; its `WaitForUITickFromUIThread`, **1583–1610**, has a Windows DXGI-tick wait path. Under Proton these are Windows application paths, not the SDK's native Linux branch. [R-presenter]

[S] NHL `OnCreateDialogs`, `src/nhllegacy_app.h`, **520–529**, keeps a dialog registered with the ImGui drawer for controller polling even while hidden. This does not by itself prove how many host paints occur or the effective presenter mode, but makes the UI route important to investigate. [N-app]

**Consequences:** host paints, guest swaps, simulation updates, distinct visible images and physical display refresh are different events. Host painting can reuse the latest mailbox image; output can drop pending guest frames. Thus high logged present FPS is not a simulation-rate guarantee. Report 011's 17% sub-5 ms frames and mean 74.3 FPS are compatible with mixed present cadence, but do not prove duplicate frames or identify multiple swapchains.

## External 60 FPS limiter regression: concrete blocking paths

[S] MangoHud `src/vulkan.cpp`, `overlay_QueuePresentKHR`, **1686–1764**, calls the limiter before or after the downstream present; `src/fps_limiter.h`, `calc_sleep`/`do_sleep`/`limit`, **13–68**, computes a target interval and sleeps on the calling thread. Installed docs identify `late` as default, but the full test config/method was not inspected. Both methods operate within the SDK's outer API-call scope. MangoHud does not implement NHL's simulation timestep. [M-vulkan], [M-limit]

[S] SDK `VulkanPresenter::PaintAndPresentImpl`, **2196–2210**, obtains `VulkanDevice::Queue::Acquisition` before `vkQueuePresentKHR`. That acquisition owns a `std::unique_lock<std::recursive_mutex>` until the scope ends (`include/rex/ui/vulkan/device.h`, **244–262**). **The outer queue mutex therefore remains held during any injected limiter sleep**, including late sleep after downstream present. [R-present], [R-device]

[S] The presenter prefers the graphics/compute queue family when it supports presentation (**1121–1148**), and uses queue index zero. Vulkan command submission `EndSubmission`, **5438–5454**, obtains that graphics/compute queue/index too. `RefreshGuestOutputImpl`, **1013–1071**, also submits to it. [R-present], [R-vk]

[H] If the installed runtime uses the same queue, sleeping in present can keep the command worker from submitting new GPU work. This is a **conditional code-established resource-sharing mechanism**, not a measured lock-duration attribution on the Ally. If presentation uses another queue family, this shared-mutex branch is weaker; direct command-thread presentation, bounded image/fence resources and UI ownership transitions remain potential couplings.

[S] Additional bounded-resource waits: `PaintAndPresentImpl`, **1497–1541**, awaits reuse of in-flight paint submissions and acquires the next swapchain image with infinite timeout; `RefreshGuestOutputImpl`, **1028–1034**, waits before replacing a resized image. Vulkan `BeginSubmission`, **5127–5153**, checks/waits for a frame-slot submission before opening another frame. Guest command-worker `WorkerThreadMain`, **274–323**, updates guest-visible read-pointer writeback after processing command batches, not before. A blocking swap prevents that worker from advancing through later packets. [R-present], [R-vk], [R-cp]

[H] Guest ring-space waits, GPU-completion-dependent CPU work, event dependencies and input consumers may consequently make less progress. The exact guest dependency chain in NHL is unknown. Finite image/fence resources can add latency even with VSync off, and a cap can lengthen a producer/consumer cycle without changing any clock scalar. The cap's reported value near 60 measures host pacing, not guaranteed 60 distinct hockey updates per second.

**Strongest explanation to investigate:** limiter-induced present-thread/queue backpressure interacting with guest dependencies. **Alternatives not excluded:** extra overlay/log I/O, changed fields in the separate config, startup state, thermal/power sharing, UI repaint scheduling, differing scenes and launch variability. Uncapped MangoHud was usable for report 011, which weakens a universal “MangoHud always causes severe slowdown” explanation; it does not isolate the cap in the new test. Removing all launch options is not a controlled cap-only reversal. No numerical simulation slowdown factor or MangoHud defect is established.

## Introductions, close-ups and FSR: workload findings and limits

### Scene-specific mechanisms available in source

[S] `VulkanTextureCache::RequestTextures`, **549–555**, and `LoadTextureDataFromResidentMemoryImpl`, **1212–1740**, can create/prepare texture resources and record conversion/copy/barrier work. First-use resources can add CPU submission and GPU work. These functions are renderer-level; no verified arena-intro/camera label selects them. [R-texture]

[S] Pipeline `EnsureShadersTranslated`, **1013–1046**, `ConfigurePipeline`, **1048 onward**, `EnsurePipelineCreated`, **3009–3495** (`vkCreateGraphicsPipelines` at 3483), and `CreationThread`, **3520–3561**, provide shader/pipeline creation paths. Cached or unchanged scenes need not compile; new states may. Report 011's four named pipeline workers had zero CPU ticks over warmed gameplay, but that is not intro evidence and does not exclude synchronous driver work. [R-pipeline]

[S] NHL `OnPreSetup`, **200–219**, requests full resolve readback and a default **3,000,000-byte gate**. Tracked SDK title patch `IssueCopy_ReadbackResolvePath` hunk, **357–425 in the patch**, skips larger CPU downloads while retaining smaller equipment composites. Pinned stock Vulkan readback path, **4658–4705**, drains queue completion for full mode, invalidates mapped memory and copies back into guest RAM. The patch inserts its gate ahead of that path; stock SDK line numbers differ after applying it. [N-app], [N-patch], [R-vk]

[H] Close-up assets, larger on-screen characters/crowd/effects, changes in textures or render targets, more draw/state changes, animation/scene CPU work and compositing dependencies can make a camera sequence demanding. Some of these could cause simulation slowdown through dependencies as well as visual stutter/input latency. **None is mapped to specific NHL scene entry points or demonstrated cost in current recordings.** More screen coverage is a graphics hypothesis; a close-up might also reduce visible geometry, so it does not universally mean more draws. Persistent difficulty every entry does not establish recurring shader compilation; recurring render/synchronization work is an equally necessary candidate.

The repository's `NHL_REPLAY_XTR` tooling replays captured GPU command streams; it is not NHL's in-game replay feature or proof of the latter's timing. Animation test/harness code likewise is not a proven simulation-loop replacement. No proprietary generated code, asset, resource dump or shader capture was read to try to fill this gap.

### What Ultra Performance may actually reduce

[S] NHL startup sets native draw-resolution scales to one (`src/nhllegacy_app.h`, **271–277**) and has integer supersampling overrides (**307–333**). FidelityFX is separately selected as a **present-time effect**, **335–349**. SDK presenter `QueryTemporalFsrRenderResolutionFromQualityMode`, **190–237**, uses a fallback ratio of 3.0 for Ultra Performance. `Presenter::GetGuestOutputPaintFlow`, particularly **1057–1117**, can insert a bilinear intermediate downscale of the already rendered frontbuffer before FSR2/FSR3. [N-app], [R-presenter]

Therefore an SDK FSR quality change need not reduce original NHL geometry, guest shading, emulated EDRAM work, equipment readbacks or draw submission. It can change later upscaler/intermediate work and shared GPU availability. Spatial FSR, temporal FSR compatibility and any other external scaling route must not be conflated. The tracked NHL overlay lists effect types and sharpness but no Ultra Performance quality selector in that block (`renderer/core/nhl_overlay.cpp`, **275–310**); which UI/path and exact FSR variant the user selected remains unverified. [N-overlay]

[U/H] The modest improvement is consistent with some rendering/presentation-related contribution, but not proof of GPU-bound execution or of lower guest internal resolution. If genuine internal scene resolution were reduced, pixel work/bandwidth could fall while CPU draw/guest synchronization and fixed-size readbacks remain; changed queue latency could indirectly help simulation. Shared APU power redistribution is possible, not measured. No change to the preferred quality mode/resolution is proposed.

## Persistent hot thread and synchronization

[M] Report 011: TID 11838 `XThread020C (F8` averages **94.99% of one logical core**, while TID 11836 `XThread0204` averages **18.27%**. During approximately aligned poorer 17–22 s, process CPU is ~267% versus ~342% in smoother 40–50 s; GPU command worker ~27% versus ~37%, hot thread remains ~95%. Its nonvoluntary switch rate is lower, not higher, in that bad region. There is no simple whole-process overload or generalized preemption-spike signature. Invalid GPU utilization and uncertain ~one-second alignment still prevent causal assignment.

[S] `XThread::Create`, **329–479**, creates a host thread and sets default `XThread{:04X}` from its host system ID at **470**. `Execute`, **571–650**, selects either `xapi_thread_startup` with start-address/context arguments or the guest start address, then resolves a generated function pointer and runs it. Noisy creation/execution logs can contain native ID and guest addresses, but no such matching log is in the approved recordings. **The current hot thread's entry point/subsystem and call stack cannot be identified from its name, TID, CPU or context-switch counters.** [R-thread]

[S] `ignore_thread_priorities`/`ignore_thread_affinities` default true (**40–44**); `SetPriority`/`SetActiveCpu`, **~830–908**, conditionally apply host mappings. Guest CPU indices are not host pinning proof. Installed effective flags/masks/priorities were not measured; no affinity or priority tuning is justified. The Intel-hybrid helper discussed in report 005 is not an Ally scheduling explanation.

[S] Busy/blocking possibilities: CAS/yield spinlock `xeKeKfAcquireSpinLock`, **967–980**, global critical region around interrupts, integer-truncated guest sleeps above, empty command queue spinning then 5 ms waits (`WorkerThreadMain`, **274–309**), and unmatched `WAIT_REG_MEM` yielding with VSync off (**1116–1190**). Useful CPU computation, polling or contention can all yield a busy thread. None is its observed location. Guest semaphores/events/APCs can reduce other workers' CPU when progress is gated elsewhere. [R-kernel], [R-dispatch], [R-cp]

[M/H] A persistently hot thread plus less-active peers fits a serialized dependency or a work phase, but not uniquely. It could also be mostly unrelated polling. No hook/address or instruction site is identified, so “optimize the 95% thread” is not an implementation task yet. Register-localization risks/provenance from report 007 remain unresolved and are not a first response to this symptom.

## Ranked candidates: evidence, symptoms and smallest confirmation

Ordering reflects diagnostic value and available source/observations, not a proven probability or estimated gains. Every row remains a causal hypothesis.

| Rank / candidate (source references above) | Supporting evidence / counterevidence | Possible effects and relation to intro/cap | Smallest discriminating confirmation, future approval required |
| --- | --- | --- | --- |
| 1. Present-thread/shared-queue backpressure | S: mutex encloses limiter sleep; frame/image waits. U: cap regression/removal improvement. Unknown: actual queue/mode, cap-only isolation. | Presentation stutter/input latency; simulation slowdown if guest depends on queue/worker progress. Intro work can exacerbate contention. | First quantify uncapped game progress versus presents. If needed later, instrument time spent in outer present/queue acquisition and guest swaps; no cap re-test without separate approval. |
| 2. Guest pacing/interrupt/synchronization mismatch | S: independent guest clock, VSync-off 1 ms interrupt cadence, global lock and guest waits. M: one hot thread, quieter peers. Unknown: NHL timestep/actual callback/lock costs. | Can affect simulation/progress and input cadence independent of host FPS; limiter can expose an existing dependency. No scene-specific proof. | Current progress-versus-presentation experiment; later callback/guest-step or lock timing only if a step site is safely identified. Do not change timing. |
| 3. Retained readbacks/resource submission and CPU/GPU handoff | S: full drains remain below gate; texture work. M/U: workload-sensitive tails and close-ups/intro difficulty. No counts/wait attribution. | Queue stalls can propagate to simulation/input and rendering; less benefit from present-only scaling. | Same scene/progress observation first; subsequent narrow aggregated readback wait/count instrumentation, no stale-read mode or threshold change. |
| 4. Scene-dependent guest computation/animation/resource work | U: intro/close-ups consistently worst. M: hot thread persists; source does not identify its game function. | Slower game/animation/input consumption while presenter repeats outputs; cap can worsen shared-resource availability. | Record motion and match-clock rates in continuous play; identify thread entry/stack only in a later separately approved diagnostic. |
| 5. GPU pixel/bandwidth/present-upscaler work or APU sharing | U: Ultra Performance modest benefit. S: postprocess/copy/queue work. M: no demonstrated sustained clock/power collapse, invalid load. | Presentation and downstream completion latency; intro coverage/resources may differ. | Progress audit plus existing labelled clock/power; actual GPU timestamps or a controlled true-internal-resolution comparison would be later work, not yet an FPS-cap test. |
| 6. First-use shader/pipeline compilation or loading | S: creation/upload paths exist. U: intro and earlier warm-launch improvement. M: warm named pipeline workers idle. No intro data, no I/O measurements. | Scene-transition stalls/latency; not automatically a steady simulation-rate cause. | Include first intro and note first-use versus continuing playback in the next observational run; later correlate existing creation logs/counters if authorized. No cache clearing. |

No dominant GPU-only, useful-CPU-only, thermal or shader-compilation bottleneck is established. Current evidence most strongly prioritizes **progress/handoff/pacing attribution**, not a throughput tweak.

## Single recommended next experiment: uncapped progress-versus-presentation audit

**One future approved session**, current preferred settings unchanged, with application-layer MangoHud **logging only, no `fps_limit`** and passive 0.5 s telemetry. Start at arena introduction and continue into at least two uninterrupted ~20-second active-play observation intervals (one relatively responsive, one choppy if available). Do not wait for obsolete slideshow episodes. Include close-ups naturally; do not change cameras/settings to manufacture a new configuration.

This requires explicit approval for the launch and temporary uncapped logging environment, because current preferred launch has no MangoHud options. Inspect the proposed logging-only config before use and preserve existing Steam/Proton selection; no persistent launch-option change is part of the experiment. If no authorized nonpersistent launch route is ready, resolve that first. Do not read or reuse the previous cap config by assumption. No experiment, config creation or launch command was run here.

Measure and record:

1. **Wall time:** numeric monotonic/UTC markers bracketing logging start and scene changes, using report 009's clock procedure. Prefer a second observer so the player need not alt-tab; otherwise label focus interruptions and exclude them. Manual reaction uncertainty is sufficient for broad multi-second slowdown, not frame-level latency.
2. **Simulation/game progress:** record displayed match-clock readings at the start/end of continuous-play intervals and the period-length rule. Compute game-clock delta per wall second and compare with a responsive interval under the same rules. Do not assume one game-clock second equals one real second. Only use an absolute expected ratio when the rule is independently established; otherwise report relative rates. Exclude whistles, pauses and replays from match-clock-rate calculations because the clock intentionally stops.
3. **Visible motion and responsiveness:** alongside the clock, note whether skating/animation cadence and normal attempted actions slow or become inconsistent. A simple repeatable ordinary skating traversal with the same player/direction during active play can provide a coarse wall-time check if practical; do not change gameplay settings to do so. This is qualitative/manual unless a repeatable motion metric is established; it does not measure milliseconds of input latency. A normally advancing wall-derived match clock would not exclude delayed simulation/motion.
4. **Arena intro:** record wall-time checkpoints between recognizable camera/announcement milestones and note visible motion stalls. There is no running match clock here; intro duration alone cannot establish simulation slowdown without a known normal reference. Compare frame intervals, worker CPU and visible progress across those checkpoints. Do not assume NHL cinematics are simulated at the gameplay timestep.
5. **Presentation and passive data:** retain raw per-frame intervals/elapsed and process/thread/labelled clock/temp/power, with shared session/event notes. Validate cadence as in report 011. Report slow-frame clusters and progress rates for the same coarse windows, not global average FPS. Discard unreliable utilization rather than scaling it.

Expected distinguishing results:

| Result | Diagnostic implication / remaining limit |
| --- | --- |
| Game-clock or repeatable motion progress falls while present cadence remains high | Supports decoupled/repeated presentation or progress-path delay; guest tick/useful-step attribution becomes the next source/instrumentation task. Does not by itself prove the host clock is slow. |
| Presents and game/motion progress fall together | Supports a coupled bottleneck, but cannot separate GPU work, readback, CPU scene work and queue waits without per-stage timing. |
| Match clock stays normal, motion/input becomes choppy | Moves update granularity, repeated frames, input sampling/presentation latency ahead of simple clock scaling. Requires care because clock may be wall-time based. |
| Intro alone has first-use spikes; later play is responsive | Strengthens initialization/upload/creation investigation; does not prove shaders. |
| Poor response occurs without either observable rate dropping | Prioritize latency/frame-distribution/input-consumption measurement; neither mean FPS nor a 20-second clock slope resolves that. |

No instrumentation/rebuild is necessary for this first separation. Logger overhead is nonzero (frame writes/overlay and sensor polling); report 011 collector work averages ~10.5 ms per 0.5 s sample, which is not a measured game slowdown factor. Adding uncapped MangoHud is itself a nuisance variable relative to preferred no-injection play. If it materially changes behavior, abort diagnostic interpretation and record that fact instead of treating the run as representative. No screenshots, videos, memory dumps, shader captures, cache clearing or invasive profiler are needed.

Rollback: logging timer/toggle stops CSV; Ctrl-C stops only telemetry. These actions do not unload the Vulkan layer. A later approved normal game/client exit and ordinary uncapped launch restores the preferred route; no termination is automated and no Steam/prefix/system setting is changed. Retain external logs/notes. **Do not re-enable the 60 FPS cap** as part of this experiment.

## Remaining unknowns and implementation gate

Unknown: NHL's step function/delta policy; guest-clock/game-clock relationship; actual guest update and vblank callback counts; queue-family identity and presenter thread/mode; present versus unique visible-frame counts; hot thread entry/call stack; costs of retained readbacks, resource uploads, pipeline creation and per-stage GPU work; exact FSR path/config; cap config fields/overlay/logging differences; current output/caps/power details; cold-versus-warm conditions. Earlier installed/generated configuration remains unknown.

The code confirms **conditional progress coupling**, not a proven 60-present/second simulation contract. Do not alter clock scalars, vblank cadence, locking, readback policy, codegen flags or renderer behavior until a progress/latency metric and a responsible path are established. Report 011's old recommendation to reproduce a severe slideshow is superseded by the current persistent-responsiveness problem and this experiment.

## Files changed and validation

Changed only this report and `reports/README.md`. Read public pinned source and tracked patches with function/line cross-checks; validated local links/reference labels and source paths against the pinned tree, plus successful retrieval of the cited public implementation files. An initially guessed timer filename and MangoHud `.cpp` limiter path were absent; authoritative tree paths (`xtimer.cpp`, `fps_limiter.h`) replaced them, and no claim relies on failed URLs. No source/test changes or new raw analysis were needed.

Existing complete offline synthetic suite: **32 tests pass**. Documentation whitespace, final staged-file allowlist and repository status checked before commit. No raw recordings or public source caches are staged. No gameplay test, real simulation rate or change in responsiveness was measured in Task 012. Commit/push only to origin's investigation branch; master/upstream untouched. Stop after publication.

## Source references

Line ranges above refer to raw files at these exact revisions; tracked patch additions shift SDK line numbers after application.


[R-clock]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/clock.cpp

[R-clock-h]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/chrono/clock.h

[R-system]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/system.cpp

[R-kernel]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/kernel/xboxkrnl/xboxkrnl_threading.cpp

[R-timer]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xtimer.cpp

[R-thread]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xthread.cpp

[R-win]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/threading_win.cpp

[R-graphics]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/graphics_system.cpp

[R-dispatch]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/function_dispatcher.cpp

[R-video]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/kernel/xboxkrnl/xboxkrnl_video.cpp

[R-cp]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/command_processor.cpp

[R-vk]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/command_processor.cpp

[R-presenter]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/ui/presenter.cpp

[R-present]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/ui/vulkan/vulkan_presenter.cpp

[R-device]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/ui/vulkan/device.h

[R-texture]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/texture_cache.cpp

[R-pipeline]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/pipeline_cache.cpp

[N-app]: https://github.com/Grognlor/nhl-legacy-recomp/blob/43e2ab95600dbb96fc2c8d073fb372861a649cba/src/nhllegacy_app.h

[N-vk]: https://github.com/Grognlor/nhl-legacy-recomp/blob/43e2ab95600dbb96fc2c8d073fb372861a649cba/renderer/core/nhl_vk_backend.cpp

[N-patch]: https://github.com/Grognlor/nhl-legacy-recomp/blob/43e2ab95600dbb96fc2c8d073fb372861a649cba/sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch

[N-overlay]: https://github.com/Grognlor/nhl-legacy-recomp/blob/43e2ab95600dbb96fc2c8d073fb372861a649cba/renderer/core/nhl_overlay.cpp

[M-vulkan]: https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/vulkan.cpp

[M-limit]: https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/fps_limiter.h
