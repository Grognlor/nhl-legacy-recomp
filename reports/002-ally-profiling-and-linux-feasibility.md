# 002 — Ally profiling and native Linux feasibility

## Objective and executive summary

Continue [report 001](001-initial-performance-investigation.md) by designing profiling of the existing Proton build and evaluating a native Linux starting point. Repository: `Grognlor/nhl-legacy-recomp`; branch: `perf/ally-investigation`; starting commit: `9ddfff18728c18a7081871911c56cca5402108eb`. Investigation date: 2026-10-19. Checkout: `/var/home/cody/Projects/nhl-legacy-recomp`.

**Profile the current Proton executable first. Defer the NHL Linux port until measurements identify the critical path.** MangoHud/mangoapp, Gamescope, Vulkan tools, sensors, and readable AMD telemetry are already present. Deep CPU/scheduler tracing tools are mostly missing. Existing application logging and readback overrides permit useful experiments without rebuilding, but neither aggregate GPU load nor the built-in FPS display identifies a bottleneck by itself.

New evidence strengthens the Linux feasibility assessment: the **exact pinned ReXGlue SDK** has Linux build workflows, POSIX core implementations, GTK windowing, a POSIX application entry point, and Vulkan enabled by default on Linux. This is a credible starting point, not proof that NHL compiles or plays correctly. Application build coupling, Windows APIs, diagnostics, media decoding, and generated-code requirements remain substantial obstacles.

The pinned SDK also confirms synchronous resolve-readback waits and async compilation behavior that can suppress actual presentation while the app counts swap calls. These are mechanisms to investigate, not measurements of the reported Ally slowdown. No gameplay, build, installation, or source modification was performed.

## Evidence levels and observed system

- **Verified locally:** repository source/patches, command and package inventory, OS identity, permission settings, and selected read-only sysfs metadata.
- **Verified public pinned source:** selected SDK files fetched at commit `bd9b51918faa71f962fa38af6d5f744af9aba2ce` into `/tmp/nhl-sdk-investigation-002`; no SDK checkout was added or modified.
- **Documented tool capability:** upstream documentation, subject to installed-version, driver, and session limitations.
- **Historical:** earlier developer benchmark results in `docs/cpu-perf-optimization-plan.md`; not reproduced here.
- **Unmeasured:** gameplay bottleneck, installed binary provenance/settings, simulation speed, effective frame pacing, and profiler overhead.

User observations remain approximately 20 FPS/60 ms in one test, earlier 40–60 FPS, high paused-menu FPS, 720p/1×, VSync off, FSR on, and a 25 W target. The FPS/frame-time pair is approximate: 20 FPS corresponds to 50 ms, and 60 ms to about 16.7 FPS. Preserve the original observations rather than force agreement.

Local OS identifies as Bazzite 44, image `bazzite-deck-44.20260921`, version `44.20260921.0`. DMI product is `ROG Xbox Ally RC73YA_RC73YA`; DRM `card1` uses `amdgpu`, vendor/device `1002:163f`. The Z2A identification is user-supplied; no hardware SKU inference is needed. Sysfs nodes were inspected to establish availability, not to measure gameplay.

## A. Existing Proton profiling strategy

### Available tools and limits

| Facility | Local verification | Useful measurement | Limits |
| --- | --- | --- | --- |
| MangoHud | `/usr/bin/mangohud`; package owner `terra-mangohud-0.8.4-2.fc44`, x86_64 and i686; layer manifests present | Application frame cadence and hardware telemetry/logging | Sampling and presentation point must be checked; does not directly attribute CPU waits or simulation timing. |
| Gamescope / mangoapp | `/usr/bin/gamescope`, `/usr/bin/mangoapp`; `terra-gamescope-3.16.28^3-1.fc44` | Compositor/application pacing context | A nested compositor changes the experiment. Use the existing session, with one overlay. |
| Vulkan tools | `vulkaninfo`, `vkcube`; `vulkan-tools-1.4.341.0-1.fc44` | Device, driver, extension and layer inventory | Does not profile gameplay. Neither Vulkan program was executed. |
| Sensors / turbostat | Commands present; `lm_sensors-3.6.0-24.fc44`, `kernel-tools-7.2.5-200.fc44` | Thermal/clocks/power where supported | Presence does not guarantee useful AMD fields or permission; no privileged probe performed. |
| `/proc`, `top`, `ps`, Python | Commands/interfaces present | Per-thread CPU-time deltas, states, context switches; analysis | CPU-time deltas distinguish running from non-running time, not the reason for every wait; single state snapshots are weak evidence. |
| AMD sysfs/hwmon | `card1/device/gpu_busy_percent`, `pp_dpm_sclk`, `pp_dpm_mclk`; `hwmon7` | Utilization and exposed clock/power/temperature readings | Shared APU power domains and sampling semantics matter. Read-only telemetry cannot name a GPU pass. |
| GDB | `/usr/bin/gdb`; `gdb-17.2-2.fc44` | Potential future thread/stack investigation | Attaching perturbs timing; stripped PE symbols/unwinding complicate attribution. Do not dump process memory under the asset constraint. |
| perf | No command in checked PATH; package absent | Future user-space sampled hotspots and counter statistics; scheduler tracing with suitable permissions | Currently unavailable. Do not install or alter kernel settings in this task. |
| RenderDoc, radeontop, amdgpu_top, pidstat/sysstat, trace-cmd, bpftrace, strace | Corresponding checked commands/packages absent | Potential future graphics or scheduler/syscall analysis | Not available in inspected host context; containers/Flatpak runtimes were not exhaustively inventoried. |
| Perfetto tools | `perfetto`, `trace_processor_shell` absent from PATH | Potential future timeline analysis | Requires a producer/capture setup, not just a viewer. |
| Development environment | `distrobox`, `podman` present; Clang/clang-20, CMake, Ninja, PowerShell absent from checked PATH | Possible future isolated toolchain | No containers created, packages installed, or build readiness established. |

`rpm -q mangohud gamescope` initially reported those package names absent; `rpm -qf` established their actual **terra-prefixed** owners. Executable/layer presence is verified; package-name guesses are insufficient.

Current settings: `perf_event_paranoid=2`, `kptr_restrict=0`, `ptrace_scope=0`. With a future perf binary, user-space per-process events may be possible, while kernel/system-wide/scheduler tracing can require additional privileges. Containerization does not bypass host permissions. No settings were changed. [Kernel perf security documentation](https://docs.kernel.org/admin-guide/perf-security.html)

The implicit-layer directory contains MangoHud, Gamescope WSI, vkBasalt, OBS capture, low-latency, Mesa anti-lag and device-selection manifests. Presence does not prove activation. `/usr/share/vulkan/explicit_layer.d` was empty; no local validation layer was established.

AMDGPU `hwmon7` exposes `temp1_input` labelled `edge`, `freq1_input` labelled `sclk`, and `power1_average`/`power1_input` with `power1_label=slowPPT`, plus power caps. These labels must accompany results. Do not add APU package and GPU readings together as independent power, or equate battery discharge with silicon power. Kernel documentation describes AMDGPU monitoring interfaces, but exact APU sensor semantics require care: [AMDGPU documentation](https://docs.kernel.org/gpu/amdgpu/driver-misc.html).

### What distinguishes the candidate bottlenecks?

| Question | Best evidence | Insufficient evidence |
| --- | --- | --- |
| CPU computation? | Per-thread CPU-time deltas plus future user-space samples in guest code, command processing, or compiler/driver code | Total CPU percentage averaged over all cores |
| CPU blocked or descheduled? | Wall time versus thread CPU time, repeated states/wait channels; future scheduler events distinguish sleeping from runnable delay | Low CPU utilization alone |
| GPU workload? | Device telemetry correlated with frames, followed by supported GPU timestamps/queue timelines | A single utilization percentage; CPU starvation can leave GPU idle |
| GPU synchronization stalls? | Wait-site attribution plus readback-mode A/B and eventual wait-duration instrumentation | A CPU sleep or futex alone; it may be audio, input, or scheduling |
| Shader compilation? | Warm-up recurrence, SDK async warnings, pipeline-thread activity, sampled compiler stacks | First-run stutter alone; asset I/O can also be cold |
| Frame pacing? | Application frame intervals and compositor cadence, refresh/cap provenance, percentile distributions | One-second average FPS |
| Simulation timing? | Independent wall-clock observation of uninterrupted simulation with fixed game settings | FPS, GPU utilization, or raw match-clock seconds without accounting for accelerated period rules |

On-CPU samples include spinning/yield loops; high CPU consumption is not automatically useful computation. PE symbols/PDB availability may limit Linux-side attribution to module and offset. A future sample-only profile should avoid stack-memory capture options unless separately reviewed against the asset restriction; scheduler traces and counter-only telemetry do not need game buffers.

### Existing application and pinned-SDK facilities

Local references below resolve to repository files. SDK references resolve to immutable public files at the pinned commit.

| Facility | Reference | Interpretation |
| --- | --- | --- |
| `[nhl-vk-fps]` and overlay | [`NhlVkCommandProcessor::IssueSwap`](../renderer/core/nhl_vk_backend.cpp); [`NhlVkPerfSnapshot`](../renderer/core/nhl_vk_backend.h) | Approximately 1 Hz wall-clock swap-call rate, frame mean, draw counts. Not GPU duration or simulation speed. |
| Readback modes and size gate | [`OnPreSetup`](../src/nhllegacy_app.h); [canonical patch](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch) | Defaults full readback with 3,000,000-byte gate. `NHL_VK_READBACK_MODE=full/fast/some/none` overrides mode; `NHL_VK_READBACK_MAX_LEN=0` disables the size gate, increasing readbacks. |
| Resolve inventory | Same patch, `NHL_VK_RB_STATS=1` | Destination maximum sizes and classified destination counts, periodically after 4000 resolves. These are not time measurements or exact per-frame kept/skipped operation counts. |
| Draw inventory | `IssueDraw`, `NHL_VK_DRAWLOG` | Adds texture scanning/inventory work. Use a separate diagnostic pass, not baseline timing. |
| App log verbosity | `OnPreSetup`, `NHL_LOG_LEVEL` | Debug/trace can add substantial overhead. Keep timing runs at normal verbosity. |
| Other environment controls | `OnPreSetup` | `NHL_VK_SS`, `NHL_VK_SHADOW_BLUR`, `NHL_VK_SHADOW_FILTER`, backend and VSync gates. Presence-tested variables must be unset to disable; `=0` is not universally off. |
| Persistence | [`nhl_settings.h`](../renderer/core/nhl_settings.h) | INI can override early VSync choice; output size and internal 1× scale are separate. FSR is present-time processing. |
| SDK scopes and registry | SDK [root CMake](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/CMakeLists.txt), [core CMake](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/CMakeLists.txt) | Tracy/profiling and perf-counter compile definitions are gated out in Release. App [SDK build script](../scripts/_ffx_sdk_configure.bat) turns Tracy/counters off. An environment variable cannot restore compiled-out instrumentation. |
| Historical CP probes | [`docs/cpu-perf-optimization-plan.md`](../docs/cpu-perf-optimization-plan.md) | `NHL_VK_CP_PROFILE`, descriptor stats and optimization experiments are historical; not present in canonical title patch searched here. Do not promise them in shipped binaries. |
| Capture/replay | `PollHotkeyCapture`, `NHL_HOTKEY_CAPTURE`; [`BenchmarkReplay`](../tools/replay/src/xtr_player.cpp) | Captures can contain copyrighted buffers; excluded. Replay skips guest waits and simulation, so cannot validate gameplay pacing. |

**Now verified in full pinned SDK source:** [Vulkan command processor](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/command_processor.cpp), `IssueCopy_ReadbackResolvePath()` around lines 4416–4705 resolves GPU data, records transfer/host barriers, waits with `AwaitAllQueueOperationsCompletion()` for full mode, invalidates mapped memory, and copies to guest RAM. Fast mode selects the alternate readback buffer; missing alternate storage falls back to a synchronous wait. Some mode copies only on cache miss. These modes are not equivalent correctness-preserving replacements. The local title patch inserts the size gate before this work. A stale-buffer interval depends on resolve reuse and is not guaranteed to be exactly one display frame.

`IssueDraw_MemexportReadbackFullPath()` and fast-path fallback also call queue-completion waits. Resolve instrumentation alone must not assume all GPU-related blocking has been covered.

**New frame-count caveat:** SDK `IssueSwap()` around lines 2305–2320 can return after `EndSubmission(true)` without presentation when `async_shader_compilation`, `vulkan_async_skip_incomplete_frames`, and placeholder-pipeline use are all true. The app subclass still counts that returned call. Both SDK controls default true in the inspected source. Consequently app FPS can overcount actual presented frames during incomplete-pipeline periods. This is a verified mechanism, not evidence that it causes the user's paused-menu or sustained gameplay readings.

[SDK Vulkan pipeline cache](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/pipeline_cache.cpp) includes `InitializeShaderStorage()`, `EnsureShadersTranslated()`, `EnsurePipelineCreated()`, `CreationThread()`, and `StorageWriteThread()`. `vulkan_pipeline_creation_threads=-1` chooses an automatic worker count; workers are named `Vulkan Pipelines`. Persistent shader/pipeline storage exists. Availability of these cvars does not establish a tested launch-argument syntax or effective values in the installed runtime.

[SDK base command processor](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/command_processor.cpp), `WorkerThreadMain()` spins/yields when command input is empty, then uses 5 ms event waits after more than 500 loop iterations. The `WAIT_REG_MEM` handler yields when VSync is off and may sleep when it is on. VSync therefore affects more than display presentation in this SDK. Do not infer simulation cadence solely from present-mode experiments.

Proton logging (`PROTON_LOG`, optional external log directory) can establish compatibility context, but verbose Wine logs perturb timing and may include paths. Use a separate short provenance pass and keep logs local; actual installed Experimental version and logging behavior remain unchecked. [Valve runtime configuration](https://github.com/ValveSoftware/Proton#runtime-config-options)

### Repeatable gameplay benchmark procedure (not executed)

This procedure requires future gameplay authorization. Launching normally can write saves, shader caches, logs and settings. To preserve the playable installation, first agree on a separate writable test environment and output location; do not duplicate or access assets under current authorization. Environment-only experiments are proposals, not permission to run now.

1. **Provenance:** record exact executable/runtime hashes after permission, Proton build, kernel/Mesa/Vulkan device, session type, active layers, display refresh/VRR, caps, output extent, internal scale, FSR variant, and effective VSync. Record AC/battery state, power target, and sensor labels. Keep 25 W fixed; do not change Bazzite policy.
2. **Workload:** fix teams, arena, camera, difficulty, period length and control method. Use the same regulation gameplay segment with no menus/replays. Record interruptions and discard interrupted timing windows using a predefined rule. Live play is not deterministic; compare matched workloads and draw counts, not supposedly identical frames.
3. **Warm-up:** play the same workload for at least five minutes or until thermal/clock behavior is stable. Treat first-visit compilation as a separate experiment. Preserve caches; do not delete or copy them.
4. **Capture window:** three 120-second gameplay runs per condition. Use interleaved A/B/A/B ordering when comparing conditions to limit temperature/order bias. Add one sustained 10-minute baseline pass if practical to expose throttling; do not mix it into short-run summaries.
5. **Frames:** first verify overlay/logging measures the target app. In desktop mode use the application Vulkan layer; in Gamescope use its supported mangoapp route rather than adding nested Gamescope or duplicate overlays. Check installed CSV semantics with a short pilot. Where supported, record each frame, not a 100 ms average. Keep UI/HUD state consistent.
6. **Telemetry:** collect GPU busy, clock state/clock readings, temperature, labelled power and memory pressure at approximately 250–500 ms intervals; collect CPU per-core and game-thread CPU-time deltas at about 1 s. Timestamp all streams with a common monotonic clock and mark run start/end. Distinguish game process, Wine service threads, and compositor.
7. **Simulation:** use an independent stopwatch for a fixed uninterrupted sequence. Match-clock progression must be normalized for period-length settings and exclude stoppages; it is a proxy, not a direct tick counter. Add a repeatable animation/event duration if possible. Record only numerical observations under the no-asset policy; direct simulation-update instrumentation remains future work.
8. **Analysis:** report frame count, elapsed time, mean FPS (`frames / elapsed`), frame-time p50/p90/p95/p99/p99.9, maximum, and fraction above 16.67/33.33/50 ms. Keep loading/menus separate. Report median across runs plus range; retain per-run values. Do not call inverse p99 frame time the same statistic as a tool's “1% low” without checking its definition.
9. **Interpretation:** correlate spikes with CPU time/waits, GPU activity, clocks/power, and async warnings. Repeat one pass with reduced overlay/telemetry to estimate measurement overhead. Never interpret absent/unsupported power fields as zero.

MangoHud supports local logging and configurable telemetry. The installed example `/usr/share/doc/mangohud/MangoHud.conf.example` documents `log_interval=0`, `log_duration`, `output_folder`, and `toggle_logging`; validate actual output before percentile analysis. Put output/config outside the installation, with uploads disabled. Gamescope integration uses mangoapp according to upstream documentation; sensor/log support can differ by session. [MangoHud documentation](https://github.com/flightlessmango/MangoHud)

### Highest-value experiments without rebuilding

| Order | Experiment | Expected discriminating evidence / limits |
| --- | --- | --- |
| 1 | Baseline external frame/telemetry log plus existing `[nhl-vk-fps]` | Establish gameplay versus paused-menu workload, swap/present divergence, sustained clocks and pacing. |
| 2 | Separate short `NHL_VK_RB_STATS=1` diagnostic pass | Verify active readback gate and retained destination sizes; does not measure wait cost. |
| 3 | Default full versus `NHL_VK_READBACK_MODE=fast`, interleaved | Improvement with comparable workload suggests readback synchronization sensitivity. Check equipment and transitions numerically/visually without storing asset captures. It does not prove pure GPU or CPU limits. |
| 4 | Full with existing 3 MB gate versus `NHL_VK_READBACK_MAX_LEN=0` | Controlled negative control for gate benefit, potentially much slower. Do not lower the threshold blindly. |
| 5 | Matched warm repeated scene versus first-visit behavior | Correlate compilation warnings/worker activity with stutter or skipped presentation. No cache deletion. |
| 6 | Presentation-effect / shadow-blur A/B only if an isolated configuration can be supplied | Separates optional GPU work; changing window resolution alone does not reduce the 720p internal guest workload. No edits to installed INI. |
| 7 | Same baseline on an already available stable Proton build | Tests compatibility-version sensitivity; isolate prefix effects and avoid modifying the production prefix. |

Some readback knobs are read once and cached: restart the isolated test process between conditions. Confirm the installed runtime contains the patch. `none`, draw-skip switches, and non-FSI render-target paths are correctness-changing diagnostics, not optimization recommendations. Config-file-only controls should wait if no verified override route preserves the installation.

## B. Native Linux build feasibility

### Exact pinned SDK: realistic foundation

The SDK root CMake at the pinned SHA explicitly disables D3D12 off Windows, enables Vulkan by default on Linux, defines `REX_PLATFORM_LINUX`, requires Clang 18+, enables PIC, uses the large code model on x86-64, and configures relative shared-library RPATHs. The repository's Linux preset chooses Clang 20; that is an app preset choice rather than the SDK's minimum.

Verified SDK components:

- [Core CMake](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/CMakeLists.txt): POSIX clock, threading, mapped memory, exception/SEH, fibers, environment and filesystem implementations; pthread/rt/dl dependencies.
- [UI CMake](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/ui/CMakeLists.txt): `surface_gnulinux.cpp`, `window_gtk.cpp`, `windowed_app_context_gtk.cpp`; GTK3 and x11-xcb via pkg-config. This does not prove native Wayland behavior; XWayland/session testing is needed.
- [Graphics CMake](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/CMakeLists.txt): separately selected SPIR-V/Vulkan and D3D12/DXBC sources.
- [Target helpers](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/cmake/rexglue_helpers.cmake): `windowed_app_main_posix.cpp`, app setup, GTK dependency, large-executable flags and `$ORIGIN` RPATH.
- [Linux AMD64 workflow](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/.github/workflows/build-linux-amd64.yaml): delegates tagged Linux builds to a shared platform workflow. Workflow existence is verified; successful historical runs and full dependency matrix were not checked.

This updates report 001's lack of complete SDK-source access. No configure/build/test succeeded or was attempted here.

### Major application blockers and possible solutions

| Blocker / reference | Why Linux fails or needs work | Proposed solution, not implemented |
| --- | --- | --- |
| [`CMakeLists.txt`](../CMakeLists.txt): unconditional `include(generated/rexglue.cmake)` | File absent before compiler/dependency discovery; normal app configuration depends on guest codegen. | Separate an asset-free smoke target from the generated-game build; later use an authorized pre-existing generated-code environment. |
| Unconditional plume, D3D12/DXGI/DXGUID and shader build | Legacy high-cut code/dependencies are pulled in even for canonical Vulkan. | Gate reference renderer sources and shader generation behind explicit options/platform support. Do not rewrite working Vulkan internals first. |
| `snappy*.lib` paths derived from SDK package | Windows naming/layout assumed. | Link an exported CMake target or platform-correct library after confirming SDK export names. |
| [`src/nhllegacy_app.h`](../src/nhllegacy_app.h), [`nhl_graphics_system.h`](../renderer/core/nhl_graphics_system.h) | D3D12 headers/fallback are included even for a Vulkan-only Linux runtime; app also imports Windows APIs. | Isolate Windows fallback at compile time, select SDK Vulkan on Linux, add platform helpers. |
| [`nhl_command_processor.cpp`](../renderer/core/nhl_command_processor.cpp) | D3D compiler/COM types, SEH `__try/__except`, Win32 calls; compiled unconditionally. | Exclude legacy D3D12 backend from initial Linux target. |
| [`nhl_vk_backend.cpp`](../renderer/core/nhl_vk_backend.cpp), `GetAsyncKeyState` | Windows import in otherwise portable Vulkan wrapper. | Replace/guard optional F9 capture input with SDK input or platform input; leave tracing disabled initially. |
| App `_putenv_s`, `TerminateProcess` imports | CRT/process APIs unavailable on Linux. | SDK environment/process abstractions or scoped POSIX implementations; preserve intentional fast-exit semantics. |
| [`src/diag_hooks.cpp`](../src/diag_hooks.cpp), animation/dump/scan headers | `VirtualQuery`, Windows exceptions/page protection and Windows types leak through app includes. Runtime-disabled code still has to compile. | Isolate optional diagnostics at compile time; port necessary memory-query logic through SDK facilities. Do not blindly remove guest compatibility hooks. |
| [`src/cpu_affinity.cpp`](../src/cpu_affinity.cpp) | Windows headers/API despite AMD runtime no-op. | Compile a platform-specific implementation/no-op, preserving Windows behavior. |
| [`src/vp6_bridge.cpp`](../src/vp6_bridge.cpp) | HANDLE pipes, `CreateProcessA`, `ReadFile`, `CloseHandle`, `ffmpeg.exe` launch. | Later POSIX subprocess/pipe layer and native ffmpeg discovery. Optional stub only for an empty smoke target; movie correctness remains a game milestone. |
| [`src/loose_tree_device.cpp`](../src/loose_tree_device.cpp) and trace/dump includes | Windows header and diagnostic dependencies; filesystem integration also matters on case-sensitive Linux. | Separate diagnostics from VFS and audit path/case behavior; reuse standard filesystem portions. |
| [`scripts/setup_sdk.ps1`](../scripts/setup_sdk.ps1), `.bat` drivers | PowerShell/cmd, vcvars, Windows Vulkan SDK discovery and import-library staging. | Linux toolchain/presets and dependency setup in an isolated environment after approval. |
| FidelityFX SDK patch and DLL workflow | Patched import path expects `.dll`/`.lib`; documented FFX build uses Visual Studio generator/toolchain. | Disable optional FFX for first native smoke test. Audit upstream Linux FFX path separately; do not treat Windows prebuilt DLLs as native libraries. |
| Rust RX2 override | Optional private sibling `.lib` and Windows system libraries | Leave optional feature disabled initially; not a blocker to basic target. |
| Packager/replay tooling | Windows-only target guards/entry points; replay/image handling also built into app | Keep installer and trace tooling out of initial target; no asset-extraction work. |
| Generated guest code and runtime ABI | Generated sources absent and game-derived; Linux compiler/exception/linker behavior untested | Cannot reach a full game build under current no-asset constraint. Validate ABI/codegen with synthetic code before any separately authorized game work. |

The existing [`gpu/smoke/CMakeLists.txt`](../gpu/smoke/CMakeLists.txt) is a plume smoke test, not proof of SDK-native Vulkan viability. It introduces the legacy RHI dependency and should not be used as the only Linux milestone.

### Components likely reusable

**Verified platform-selection support:** SDK Vulkan command processor, render-target/texture caches, SPIR-V translation, deferred command buffers, Vulkan presenter/device/provider and memory allocator are selected independently of D3D12. Start with these at the same pin and title correctness fixes. The readback stall mechanism would remain in a native executable unless changed.

**App code likely reusable at algorithm level:** `IssueDraw` compatibility handling, performance snapshot/mutex logic, settings helpers, overlay logic, standard-library portions of VFS/injection registry, and input integration through SDK abstractions. The Vulkan wrapper is not reusable byte-for-byte because of the hotkey import. Linux UI/input and VFS integration still require verification.

**Patch portions likely portable:** shader correctness fixes, readback mode/size-gate changes, shadow texture operations, and Vulkan physical-device selection use portable C++/Vulkan. Windows FFX import/install hunks require separation. No patch application or compilation was attempted, so portability remains source-based, not build-proven.

### Smallest asset-free milestone

Proposed future milestone: an independent minimal native SDK consumer that configures and compiles without `generated/`, links a Linux SDK runtime, and opens an empty Vulkan window with bilinear presentation and no guest executable. Disable FFX, packager, replay/capture and title diagnostics; do not feed it any game data.

Sequence: first configure/build the pinned SDK with native Vulkan in an approved isolated development environment; then configure a tiny consumer through public target helpers; then compile/link and verify native ELF/shared-library resolution; finally open an empty window after execution approval. This does **not** prove guest memory mapping, shader correctness, gameplay, audio, input, or performance parity. The current task authorizes none of these builds/runs.

No reliable elapsed-time estimate can be derived without a configure log. Relative engineering estimate: SDK/empty-window spike is small-to-medium and bounded; extracting a Vulkan-only NHL target is medium-to-large; full gameplay correctness is large, plausibly multi-week work with high uncertainty. This is planning judgment, not a delivery commitment. Highest risks are generated-code/ABI integration, memory/exception semantics, hidden Windows coupling, media/VFS correctness, and display/input behavior.

## Comparison and prioritized roadmap

| Approach | Benefit | Cost / risk | Recommendation |
| --- | --- | --- | --- |
| Existing Proton build profiling | Reproduces actual issue with installed tools and no rebuild | Attribution limited by missing profilers/symbols | Start here when gameplay testing is authorized. |
| Windows rebuild, test through Proton | Matches documented build/SDK/FFX workflow; can add focused wait probes | Windows toolchain and authorized generated code needed; SDK/app ABI must match | Preferred first implementation route if external profiling leaves ambiguity. |
| Linux-hosted Windows cross-build | Could centralize development | Untested toolchain, CRT/import libraries, FFX and script adaptation | Not the shortest diagnostic route. |
| Native Linux port | Removes Windows compatibility boundary and enables native tooling | Major independent correctness/build work; no demonstrated FPS gain | Defer NHL port. Consider only a bounded asset-free smoke spike after bottleneck evidence. |

Priorities:

1. **P0 — Measurement readiness:** agree on a writable test context that preserves the playable installation, select app versus compositor logging, and validate frame-log precision. No package/system changes required for this first step.
2. **P1 — External baseline:** execute the matched procedure and inspect retained readback inventory; correlate CPU running time, GPU activity, clocks and timing.
3. **P2 — Environment-only A/B:** test full/fast and gate negative control, with correctness checks and identical warm conditions. Keep results numerical and local.
4. **P3 — Focused instrumentation if needed:** retain report 001's proposal: opt-in aggregated queue-wait, readback/copy and base-swap timings. Extend counters to distinguish actual presentation suppression and other readback wait paths. Disabled by default, no per-draw logging, no rendering changes.
5. **P4 — Optimize measured cause:** synchronization work if waits dominate; guest/submission work if CPU compute dominates; shaders/optional passes if GPU dominates; pacing/timer work if simulation diverges. Compare with baseline and preserve correctness.
6. **P5 — Native feasibility spike:** only if its value remains justified. Separate empty-window success from a full game port and require evidence before any FPS claim.

### Recommended next Codex task

Prepare a standalone **telemetry-only benchmark harness and runbook** outside the installation, using existing MangoHud/mangoapp integration plus read-only `/proc`/sysfs sampling. It should validate sensor labels, flag unavailable fields, use monotonic timestamps, compute frame-time percentiles from verified per-frame records, and produce report 003. Validate parsing with synthetic numeric data first; no game access, launch, capture or instrumentation implied. Ask separately for the concrete gameplay test environment and runtime authorization before collecting baseline runs.

If the user instead approves a source instrumentation step, first obtain the matching SDK and Windows generated-code build environment; do not begin native NHL porting merely to obtain profiling data.

## Files changed and validation performed

Only intended tracked changes:

- `reports/002-ally-profiling-and-linux-feasibility.md` — this report.
- `reports/README.md` — report index entry.

Read report 001 and the report index first. Inspected CMake, presets, app/renderer sources, SDK patches, build scripts, and existing performance notes. Queried commands/package ownership, OS/DMI/DRM metadata, sysfs telemetry-node availability, layer manifests and current profiling permission settings. Retrieved selected **public SDK code only** at the immutable pin into `/tmp`; initial sandbox DNS failure required an approved network read. Checked report whitespace, local relative links, staged-file allowlist, and repository status before commit. No application/SDK source, binaries, generated guest files or assets were modified or staged.

No game execution, build/configure, profiler attachment, GPU frame capture, package installation, system configuration change, playable-installation access, or copyrighted-asset access/copy/extraction/upload occurred. No gameplay performance improvement is claimed. Tool presence does not establish successful operation inside Steam's runtime or Flatpak; no historical CI success was independently verified.

## Outstanding questions

- Which exact Proton Experimental build, game/runtime binaries and effective settings are active?
- Is Steam running in desktop, Gamescope game mode, or Flatpak, and which layers are actually enabled?
- Can an isolated writable test context preserve the installation without violating asset constraints?
- Does the frame logger yield true app per-frame intervals or sampled/compositor intervals in that session?
- Are retained resolve waits, memexport waits, command starvation, shader placeholders, or presentation limits on the critical path?
- Are CPU/GPU clocks and labelled power stable across matched gameplay runs?
- Does normalized simulation progression slow independently of presentation rate?
- Are PE symbols and a matching Windows/SDK build environment available?
- Would native Linux remove a measured compatibility overhead large enough to justify porting?

Await further instructions before implementation or gameplay testing. Publish only this report and index to `origin/perf/ally-investigation`; do not merge to master or push upstream.
