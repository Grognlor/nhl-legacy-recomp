# 001 — Initial performance investigation

## Objective and scope

Investigate NHL Legacy Edition Recomp v0.6.0 performance on an ASUS ROG Ally Z2A running Bazzite Linux 44 through Proton Experimental before attempting optimization. Map rendering, translation, frame scheduling, synchronization, shader compilation, CPU submission, game timing, configuration, and build practicality. Identify useful experiments and a first implementation task without assuming a GPU bottleneck.

This report preserves the completed source investigation. It does not add runtime findings.

Repository: `Grognlor/nhl-legacy-recomp`. Working branch: `perf/ally-investigation`. The investigated checkout was `/var/home/cody/Projects/nhl-legacy-recomp` (the task described `/home/cody/Projects/nhl-legacy-recomp`). Investigated HEAD: `0ebb3f8` (`chore: normalize Windows script line endings`). Local v0.6.0 tag: `0852183` (`fix(build): restore CRLF line endings on scripts/*.bat + enforce via .gitattributes`). The diff from that tag to investigated HEAD contains only two scripts, so the rendering code discussed here matches that tag.

## System and observed gameplay behavior

The following observations were supplied by the user, not independently measured:

- ASUS ROG Ally Z2A, Bazzite Linux 44, Proton Experimental.
- Gameplay is sluggish; one test showed approximately 20 FPS and 60 ms frame times.
- Earlier gameplay readings fluctuated around 40–60 FPS.
- Paused menus can show high FPS despite slow gameplay.
- Reported rendering resolution: 1280×720; supersampling: 1×; VSync disabled; FSR enabled.
- Power target: 25 W.
- GPU utilization and frame pacing may contribute, but the bottleneck is unconfirmed.

At a common sampling interval, 20 FPS corresponds to 50 ms/frame, while 60 ms/frame corresponds to approximately 16.7 FPS. The supplied values may come from different sampling windows. Neither value should be silently treated as a precise synchronized measurement.

## Evidence classification and investigation boundaries

1. **Verified repository behavior:** executable application code and SDK patch code inspected in this checkout.
2. **Historical evidence:** checked-in reports and comments describing measurements on other hardware. These justify hypotheses but do not establish Ally behavior.
3. **Unverified behavior:** the installed executable/runtime identities, effective settings, exact Proton build, driver/device selection, utilization, waits, simulation rate, and thermal/power behavior.

The full SDK source and generated guest code were absent. Attempts to retrieve the pinned SDK command-processor source through web browsing failed. SDK internals outside available patch context therefore remain incompletely verified.

The investigation did not modify files, build or run the game, access or copy copyrighted assets or ISOs, inspect the playable installation, commit, or push. Subsequent creation of this report and its index is documentation-only work explicitly requested by the user.

## Rendering architecture and translation path

| Stage | Source and function | Verified finding |
| --- | --- | --- |
| Recompiled application | [`src/main.cpp`](../src/main.cpp), `REX_DEFINE_APP` | Enters the app through ReXGlue using generated native guest code. Generated implementation files are unavailable in this checkout. |
| Guest graphics interface | [`gpu/hooks/d3d9_resources.cpp`](../gpu/hooks/d3d9_resources.cpp), `REX_HOOK_RAW(sub_827F1C88)` | Hooks guest Present, increments a counter, calls gated diagnostic helpers, then forwards to the original function. D3D9 terminology here describes the guest interface. |
| Backend selection | [`src/nhllegacy_app.h`](../src/nhllegacy_app.h), `NhllegacyApp::OnPreSetup` | Vulkan-enabled builds default to `NhlVkGraphicsSystem` and the `fsi` render-target path. |
| CPU draw submission | [`renderer/core/nhl_vk_backend.cpp`](../renderer/core/nhl_vk_backend.cpp), `NhlVkCommandProcessor::IssueDraw` | Counts draws, applies alpha-to-coverage compatibility handling, and delegates to the SDK Vulkan backend. Detailed texture inventory is gated off normally. |
| Graphics-system construction | Same file, `NhlVkGraphicsSystem::CreateCommandProcessor` | Installs the app's Vulkan command-processor subclass. |
| Render targets | `OnPreSetup`; [`sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch`](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch) | Selects the interlock-based EDRAM path. Comments identify other Vulkan path values as producing black/missing gameplay rendering. |
| Presentation and statistics | `NhlVkCommandProcessor::IssueSwap`, `PublishVkPerf`, `ReadVkPerf` | Delegates swap/presentation to the SDK and publishes wall-clock swap statistics for the overlay. |

Expected normal route, subject to runtime backend verification:

```text
Recompiled guest code
  → Xenos command processing
  → SDK Vulkan backend (FSI / EDRAM)
  → Proton Vulkan bridge
  → host Vulkan driver
  → compositor / display
```

There is no source evidence that normal Vulkan gameplay passes through DXVK or vkd3d-proton. The D3D12 fallback is a different route and would normally involve vkd3d-proton under Proton. Proton is Wine-based Windows compatibility software and includes these translation components: [Valve Proton repository](https://github.com/ValveSoftware/Proton).

`NHL_VK_BACKEND_OFF` suppresses automatic Vulkan selection; an explicitly present `NHL_VK_BACKEND` still selects the Vulkan branch. Presence-tested environment variables should not be assumed disabled by setting their value to `0`.

The custom D3D12/plume renderer and local SPIR-V translator sources are primarily historical/reference paths. Their inclusion in the build does not establish that normal gameplay executes them. Relevant reference code includes [`renderer/core/nhl_command_processor.cpp`](../renderer/core/nhl_command_processor.cpp) and `gpu/hooks/`. See also [`DEV-README.md`](../DEV-README.md) and [`docs/current-status.md`](../docs/current-status.md).

## Synchronization and frame scheduling

### Resolve readback: highest-priority source-backed lead

`NhllegacyApp::OnPreSetup` explicitly sets:

- `readback_resolve=full`
- `vulkan_readback_resolve=true`
- `NHL_VK_READBACK_MAX_LEN=3000000`, unless already overridden

The canonical SDK patch modifies `VulkanCommandProcessor::IssueCopy_ReadbackResolvePath()` in SDK `src/graphics/vulkan/command_processor.cpp`. The added code compares `written_length` against the threshold and returns before CPU readback for larger resolves. Smaller resolves retain the underlying readback path.

Patch comments identify `AwaitAllQueueOperationsCompletion()` as a full GPU drain in that underlying path, followed by copying current data back to guest memory. The complete underlying function was not available for inspection. The rationale is correctness: guest CPU consumers require current runtime-composited equipment textures, while larger framebuffer resolves can remain GPU-resident.

**The investigated release already contains this size-based readback optimization.** Recommending the same gate as a new change would overlook the current implementation. Remaining retained readbacks may still create expensive CPU–GPU serialization, but their Ally cost is unknown.

The patch also modifies SDK `CommandProcessor::GetReadbackResolveMode()` in `src/graphics/command_processor.cpp`, adding the cached `NHL_VK_READBACK_MODE` override. Mode behavior must be evaluated with the actual runtime; comments describe `fast`/`some` as delayed or double-buffered alternatives.

### Historical performance evidence

[`docs/cpu-perf-optimization-plan.md`](../docs/cpu-perf-optimization-plan.md) reports, on another machine and workload:

- A command-processor thread at approximately 59% of one core, with substantial blocked time rather than compute saturation.
- Replay medians of roughly 3850 ms for full readback, 2310 ms for fast, 1680 ms for some, and 1320 ms for disabled readback in the described benchmark. These are benchmark durations, not individual gameplay frame times.
- Little benefit from descriptor/sampler and other per-draw micro-optimizations.
- A later size gate that improved performance while retaining equipment correctness in the documented checks.

These are historical reports, not reproduced results. Earlier conclusions in that document that per-draw cost justified multithreaded recording were subsequently revised when blocking was identified. The document's chronology matters.

### What current FPS instrumentation measures

`NhlVkCommandProcessor::IssueSwap()` samples `steady_clock` after calling the base SDK swap, counts swaps, and publishes approximately one-second averages. `frame_ms` is elapsed wall time divided by swap count.

It is not GPU execution duration, a frame-time percentile, or a simulation-update measurement. The overlay reads that snapshot through app wiring and displays it in [`renderer/core/nhl_overlay.cpp`](../renderer/core/nhl_overlay.cpp).

Consequences:

- High paused-menu FPS does not establish gameplay throughput.
- Average FPS hides individual pacing spikes.
- Swap cadence cannot independently establish game-clock or simulation speed.
- Exact queue depth, present mode, fence/semaphore behavior, and SDK frame scheduling still need full SDK inspection and runtime measurement.

## Game timing and potential bottlenecks

`OnPreSetup` contains a historical comment that an uncapped frontend timeline ran approximately 5–6× slowly near 125 FPS, motivating console-like VSync pacing. This records an earlier timing concern; it does not prove the mechanism behind current gameplay sluggishness.

The generated simulation loop and SDK timer/interrupt implementation are unavailable. Fixed versus variable timestep, simulation catch-up, guest waits, and interrupt/presentation coupling remain unresolved. [`src/kernel_stubs.cpp`](../src/kernel_stubs.cpp) supplies camera stubs, not an explanation of gameplay timing.

| Candidate | Supporting evidence | What remains unknown |
| --- | --- | --- |
| CPU submission | Draw processing delegates to a stateful SDK command processor; historical investigations considered its cost. | Actual thread CPU saturation, draw counts, and cost distribution on Ally. |
| Guest simulation CPU | Native recompiled gameplay runs alongside rendering. | Hot functions, thread scheduling, simulation rate, and guest wait behavior. |
| GPU rendering | FSI/EDRAM processing, texture operations, presentation effects, and optional shadow blits consume GPU work. | GPU execution duration, occupancy, bandwidth pressure, clocks, and critical passes. |
| CPU–GPU synchronization | Full readback remains enabled for retained resolves; patch comments identify queue drains. | Frequency and wall-time contribution after the existing 3 MB gate. |
| Shader/pipeline creation | Runtime translation and cache versioning are present. | Cache hits, compilation threading, pipeline creation duration, and correlation with hitches. |
| Presentation/timing | Swap-only FPS reporting and historical uncapped frontend concern. | External limits, compositor effects, queue pacing, and simulation-to-wall-clock relationship. |
| Power/thermal behavior | User reports a 25 W target. | Sustained package power, CPU/GPU allocation, clocks, temperatures, and throttling. |

## Shader compilation and configuration

The SDK patch changes `SpirvShaderTranslator::ProcessTextureFetchInstruction()` in SDK `src/graphics/pipeline/shader/spirv_translator_fetch.cpp` and bumps translator cache version to 14 in `include/rex/graphics/pipeline/shader/spirv_translator.h`. This establishes runtime shader translation/cache involvement, not a measured shader bottleneck. The local high-cut translator should not be substituted for analysis of the canonical SDK implementation.

Settings persistence is implemented in [`renderer/core/nhl_settings.h`](../renderer/core/nhl_settings.h), including `LoadSettings()`, `LoadVsync()`, `LoadSupersampling()`, and `SaveSetting()`.

| Configuration | Verified source behavior and implication |
| --- | --- |
| Supersampling | Integer draw-resolution scale is applied in `OnPreSetup`; 1× corresponds to the guest 1280×720 baseline. |
| Window/output resolution | App defaults are 1920×1080. Reported 720p output needs verification separately from internal resolution. |
| FSR | Configured as a present-time effect. Enabling it does not itself lower internal guest resolution in application code. Exact selected effect and output extent matter. |
| VSync | Enabled early unless bypassed, then persisted `vsync` is applied later. `NHL_VK_NO_VSYNC` alone can therefore be overridden by the INI. |
| Shadow filtering | `shadow_filter_linear` changes supported depth texture sampling. |
| Shadow softness | Patched SDK `VulkanTextureCache::SoftenDepthShadowLevel0()` adds downsample/upsample blits and barriers per pass on texture upload; zero disables this extra work. |
| CPU affinity | `rex_pin_pcores_if_hybrid()` in [`src/cpu_affinity.cpp`](../src/cpu_affinity.cpp) targets Intel hybrid systems and is documented as a no-op on AMD. |
| Audio queue | Defaults to 16 frames to tolerate stalls. This can reduce underruns without fixing their cause. |
| Color grade | [`BOOTSTRAP.md`](../BOOTSTRAP.md) says rebuilt runtimes lack the SDK pass; [`src/present_grade_compat.cpp`](../src/present_grade_compat.cpp) supplies compatibility cvars. Installed binary behavior remains unverified. |

Some historical documentation describes supersampling as nearly free or gameplay as conclusively CPU-bound. Neither conclusion should be generalized to this handheld.

## Prioritized profiling experiments

All experiments below are proposals. None were performed. Use matched gameplay scenes, camera, power conditions, warm-up, and effective settings. Measure sustained behavior and frame-time percentiles alongside averages.

| Priority | Experiment | Decision enabled |
| --- | --- | --- |
| P0 | Record EXE/runtime identity, Proton build, selected Vulkan device/driver, effective settings, output extent, refresh rate, and external frame caps. | Establish whether the running configuration matches this investigation. |
| P1 | Correlate frame times with per-thread CPU activity and waits, GPU activity/clocks, actual power, and thermal behavior. | Distinguish simulation work, submission, GPU execution, synchronization, and throttling. |
| P1 | Measure retained/skipped resolve counts and bytes, queue-completion wait time, and readback copy time. | Test whether remaining small readbacks dominate. Existing `NHL_VK_RB_STATS` records destination sizes, not stall duration. |
| P2 | Compare `full` with `fast`/`some` in isolated, matched gameplay tests. | Determine synchronization sensitivity. Validate helmets, jerseys, goalie equipment, replays, and transitions live. |
| P2 | Compare FSR with bilinear at identical internal/output extents; separately compare shadow softness zero. | Isolate presentation and optional texture-processing costs. |
| P2 | Compare cold-start with repeated warm gameplay while tracking shader translation/pipeline creation events. Preserve existing caches. | Distinguish compilation hitches from sustained low throughput. |
| P3 | Compare simulation/game-clock progression with wall time; separately compare stable Proton and Experimental after establishing a baseline. | Test timing divergence and compatibility regressions. |

Disabled readback is not a proposed fix: equipment rendering can break. Lowering the 3 MB gate requires evidence about guest CPU consumers; byte size is a heuristic, not proof of dependency.

### Replay limitations and asset boundary

`BenchmarkReplay()` in [`tools/replay/src/xtr_player.cpp`](../tools/replay/src/xtr_player.cpp) times `DriveStream()` on the command-processor worker, reading the trace once and discarding warm-up iterations. `DriveStream()` explicitly skips `WAIT_REG_MEM`; normal guest simulation is absent. There is no explicit GPU completion wait at the benchmark timing boundary.

Replay is useful for controlled backend comparisons, not an end-to-end gameplay benchmark. GPU traces may contain game data. Creating or handling them requires separate authorization under the current asset constraint; this investigation did neither.

## Build environment limitations

[`BOOTSTRAP.md`](../BOOTSTRAP.md) and [`scripts/setup_sdk.ps1`](../scripts/setup_sdk.ps1) pin ReXGlue commit `bd9b51918faa71f962fa38af6d5f744af9aba2ce` plus title patches. The documented workflow uses Windows VS Build Tools, Clang, Ninja, CMake, the Vulkan SDK, and a prebuilt FidelityFX DLL/import library.

| Workflow | Practical assessment |
| --- | --- |
| Bazzite profiling of existing Windows binaries | Best environment for reproducing this reported issue. Tool availability and profiling permissions remain unchecked. |
| Native Linux build | Substantial porting task. Linux presets exist, but [`CMakeLists.txt`](../CMakeLists.txt) unconditionally links D3D12/DXGI libraries and Windows `.lib` dependencies and includes Windows-specific sources using SEH/imports. |
| Linux-hosted Windows cross-build | Possible engineering project, not a demonstrated repository workflow. Requires compatible Windows SDK/CRT, ReXGlue, FidelityFX artifacts, and adapted scripts. MinGW cannot be assumed interchangeable. |
| Windows build followed by Bazzite testing | Lowest-risk implementation route because it matches the documented build toolchain while retaining the relevant Proton test environment. |

Bazzite documents Distrobox for development tooling, but a container does not resolve the project's Windows dependency and ABI requirements: [Bazzite Distrobox documentation](https://docs.bazzite.gg/Installing_and_Managing_Software/Distrobox/).

[`scripts/_build_vk_opt.bat`](../scripts/_build_vk_opt.bat), [`scripts/_build_vk_pgo.bat`](../scripts/_build_vk_pgo.bat), and [`scripts/_ffx_sdk_configure.bat`](../scripts/_ffx_sdk_configure.bat) describe optimized x86-64-v3/ThinLTO configurations; PGO is an additional stage. Shipping runtime configuration disables profiling instrumentation. Some script comments retain older descriptions, so effective flags and binary provenance need verification.

[`release/package.ps1`](../release/package.ps1) can package prebuilt binaries. A release label alone does not establish the flags used to produce them.

A clean build requires generated code produced from the copyrighted executable. That step is outside current authorization. An existing authorized generated-code build environment would avoid repeating it during this investigation.

## Optimization recommendations

1. Establish binary/configuration provenance and measure the critical path before changing behavior.
2. Prioritize retained readback synchronization if measurements show queue waits dominate. Consider dependency-aware or safely delayed readback only with correctness evidence.
3. If CPU compute dominates, identify guest versus command-processor work before revisiting draw submission caches, draw-count reduction, or parallel recording.
4. If GPU work dominates, isolate FSI/render-target work, optional shadow processing, and presentation effects before changing shader or rendering algorithms.
5. If hitches correlate with compilation, investigate shader/pipeline caching and creation scheduling in the pinned SDK.
6. Treat simulation timing as a separate measurement axis. High displayed FPS is not a substitute for correct game speed.

Multithreaded command recording and broad renderer rewrites are premature. Historical data specifically warns that optimizing CPU compute can miss blocked time.

## Proposed first instrumentation task

Add opt-in aggregated timing instrumentation without changing rendering behavior:

- SDK `VulkanCommandProcessor::IssueCopy_ReadbackResolvePath()` in `src/graphics/vulkan/command_processor.cpp`, represented by the canonical SDK patch in this repository.
- App `NhlVkCommandProcessor::IssueSwap()` in `renderer/core/nhl_vk_backend.cpp`.

Record retained/skipped resolve counts and bytes, queue-wait duration, readback/copy duration, base-swap duration, and frame-interval percentiles. Keep instrumentation disabled by default and avoid per-draw logging. Full SDK source inspection is needed before placing precise wait/copy probes.

The resulting evidence should determine whether the next change belongs in readback selection, submission, GPU workload, or timing. This instrumentation is proposed, not implemented or approved by the documentation request.

## Files changed and validation performed

Documentation persistence changes only:

- `reports/001-initial-performance-investigation.md` — this report.
- `reports/README.md` — running report index and future report requirements.

Investigation validation consisted of read-only source, patch, build-script, documentation, Git status, branch, tag, and diff inspection. The initial working tree was clean. No runtime measurements, tests, builds, trace captures, asset access, or playable-installation changes were performed. The report records evidence rather than asserting a validated performance fix.

## Outstanding questions and next steps

- Does the installed v0.6.0 executable/runtime pair match the investigated tag and SDK patches?
- Which Vulkan device, driver, FSI path, internal scale, output extent, FSR variant, and VSync setting are actually active?
- Are Gamescope/compositor/Steam limits affecting presentation?
- Does the slowdown persist after warm-up and under stable clocks/power/temperature?
- Which thread is running versus blocked, and for how long?
- How many readbacks remain after the 3 MB gate, and what is their critical-path wait time?
- Are shader/pipeline events correlated with spikes or sustained low throughput?
- Does simulation/game-clock progression match wall time during slow gameplay?
- Is a compatible Windows build environment with already-generated guest code available?

Next: await user instructions. The user has authorized saving and publishing these documentation files only. Do not modify application/SDK source, build or run the game, perform instrumentation, or access game assets under that authorization. Future substantial tasks should receive a new numbered report and an index update.
