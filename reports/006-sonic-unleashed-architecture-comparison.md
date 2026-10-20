# 006 — Unleashed Recompiled architecture comparison

## Objective, scope and outcome

Compare the public Unleashed Recompiled/XenonRecomp stack against NHL Legacy's actual ReXGlue integration, identifying performance techniques that could transfer to the ASUS ROG Ally Z2A on Bazzite 44. This is research and documentation only.

Verified `origin=https://github.com/Grognlor/nhl-legacy-recomp.git`, branch `perf/ally-investigation`, starting commit `3a978763bb0f78a9843779a596a201d460b6a818`, and a clean working tree. Read reports [001](001-initial-performance-investigation.md), [002](002-ally-profiling-and-linux-feasibility.md), [003](003-ally-profiler-implementation.md), [004](004-bazzite-home-path-fix.md), [005](005-simulation-vs-live-bottleneck-investigation.md) and the [index](README.md), then inspected application/build/configuration code and pinned SDK sources. `master` and `upstream` are outside this task.

**Main findings:**

- Sonic does **not** use ReXGlue as its runtime. It combines XenonRecomp-generated CPU code, a custom kernel/thread/memory layer, XenosRecomp shader conversion, and a game-level renderer over plume. Shared ancestry/techniques do not make the runtimes interchangeable.
- ReXGlue already implements XenonRecomp-style register localization, direct calls, fast table-based indirect calls and asynchronous Vulkan pipeline creation. Replacing the recompilation pipeline is unnecessary to investigate those techniques.
- Sonic explicitly enables register-localization options. NHL's checked-in manifest/includes do not; the pinned SDK defaults them false. The effective settings of the shipped executable are **unverified because NHL's generated code is absent**. Auditing provenance is the first CPU-codegen opportunity, not an assertion that the installed game is unoptimized.
- Sonic's major graphics distinction is its higher interception level and knowledge of engine resources/assets. Loading-aware pipeline preparation and copy elimination are patterns to adapt; its addresses, layouts, shaders and renderer cannot be dropped into NHL.
- ReXGlue's pinned VSync flag couples guest-vblank cadence, some command waits and presentation configuration. Sonic instead explicitly hooks game update/presentation and patches particular timestep-sensitive routines. This makes measured timing separation worth investigating, without proving a current vblank bug or licensing Sonic's timestep constants as an NHL fix.
- Native Linux support offers platform-boundary lessons, not evidence of NHL FPS gains. Keep the established Windows build/Proton test route while measuring the actual problem.

No percentage improvement is estimated. All suggested performance benefits are conditional on identifying the corresponding cost in NHL.

## Corrected workload context and evidence limits

The earlier “simulation” capture was a **fully rendered CPU-versus-CPU hockey match**, with both teams AI-controlled. The “live” capture was also rendered gameplay, with the user controlling players. It was not a quick-simulation menu versus a rendered game. This clarification supersedes report 005's outstanding ambiguity; it does not change its verified numeric results.

Report 005 verified approximately 334.01% versus 334.95% process CPU, 94.91% versus 94.86% on Linux TID 7148 (`XThread0204`), and median hwmon sclk of 1063 versus 697.5 MHz. Process/thread CPU overlap; 100% means one logical core. GPU utilization was invalid in most samples; slowPPT is not GPU-only power. No synchronized frame-time data or numerical simulation-speed series exists.

Both matches rendering on screen rules out the simplistic explanation that only one workload rendered anything. It does **not** establish identical draw counts, camera, game state, control/input paths, CPU work, power sharing or frame pacing. The player-control difference deserves a matched follow-up; it does not prove an input-thread bottleneck. These data were not remeasured during this task.

Evidence labels used below:

- **Verified source:** code/configuration read at the exact revisions listed below.
- **Documented:** project prose, distinguished from behavior checked in code.
- **Hypothesis:** potential effect in NHL requiring measurement.
- **Unknown:** installed binary behavior, absent generated output, unmeasured workload/cost.

## Repository and revision ledger

These are the exact public repositories/revisions used. GitHub commit metadata/file trees and successful raw-source retrievals established the pins. No assets, executable dumps, generated game implementations or shader-cache binaries were fetched. In particular, Sonic's `private/`, generated `ppc/`, resource submodule and game asset archives were not fetched.

| Project | Repository | Revision and role |
| --- | --- | --- |
| NHL fork | https://github.com/Grognlor/nhl-legacy-recomp | `3a978763bb0f78a9843779a596a201d460b6a818`, local investigation baseline |
| ReXGlue SDK | https://github.com/rexglue/rexglue-sdk | `bd9b51918faa71f962fa38af6d5f744af9aba2ce`, NHL pin plus local title patches |
| Unleashed Recompiled | https://github.com/hedge-dev/UnleashedRecomp | `cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c`, resolved project HEAD during research |
| XenonRecomp used by Sonic | https://github.com/hedge-dev/XenonRecomp | `c5bfd90d87f2ed0db8cff5c19ea3aff0e161e527`, **actual Sonic submodule pin**, used for code comparison |
| XenonRecomp upstream HEAD | Same repository | `ddd128bcca99fe8bfbb99bea583c972351fa6ace`, recorded for provenance; not substituted for Sonic's pin or audited as a separate optimization version |
| XenosRecomp | https://github.com/hedge-dev/XenosRecomp | `990d03b28a27b50277ee5d8d942e1c5f873869d1`, Sonic pin and resolved upstream HEAD |
| plume | https://github.com/renderbag/plume | `11926860e878e68626ea99ec88562ce2b8badc4f`, Sonic's renderer abstraction pin |
| SDL | https://github.com/libsdl-org/SDL | `1edaad17218d67b567c149badce9ef0fc67f65fa`, Sonic submodule pin; consumed by build, not independently source-audited here |
| SWA engine API descriptions | https://github.com/hedge-dev/SWA | `f299dd8cf272a0110c91e54e2b6e308a2d897966`, Sonic API submodule pin; engine-type usage inspected in renderer, API implementation not fetched |

Submodule URLs are in [U-modules]; exact gitlink SHAs are in the project tree at the recorded Unleashed revision. This comparison is not an assessment of every current fork or later SDK release.

## Architecture map

| Layer | Unleashed Recompiled | NHL Legacy |
| --- | --- | --- |
| CPU translation | XenonRecomp → C++ PPC functions; configured in `UnleashedRecompLib/config/SWA.toml` [U-config], [X-gen] | ReXGlue codegen → generated C++ functions; manifest plus scanner corrections [N-manifest], [R-manifest] |
| Function ABI | `void(PPCContext&, uint8_t* base)`, register unions, guest address space [X-context] | Same broad context/base approach, ReXGlue helpers and hooks [R-context], [R-init] |
| Runtime | Project-specific `GuestThread`, `Memory`, kernel hooks [U-thread], [U-memory], [U-kernel] | Xenia-derived ReXGlue threads, kernel, memory, dispatcher, device/runtime machinery [R-thread], [R-dispatch] |
| Graphics interception | Hooks `CreateTexture`, `DrawIndexedPrimitive`, `StretchRect`, etc. into host resource objects and render commands [U-video] | Guest code emits Xenos command stream; `NhlVkCommandProcessor` delegates to SDK Vulkan/FSI [N-vk], [N-app] |
| Shaders | Build-time XenosRecomp conversion/cache; runtime pipeline construction [U-lib], [Y-gen], [U-video] | Runtime Xenos analysis/SPIR-V translation and persistent shader/pipeline-description storage [R-pipeline] |
| Submission | Render-command queue/worker, plume command lists/fences/semaphores [U-video], [P-vulkan] | SDK command processor, deferred recording, shared memory and EDRAM/resolve handling [R-cp], [R-vk] |
| Linux | Native OS sources, std::thread path, mmap, SDL/plume Vulkan, explicit build presets [U-thread], [U-memory], [U-build], [U-presets] | SDK has POSIX/GTK/Vulkan support, but NHL target still unconditionally includes Windows dependencies [R-root], [R-ui], [N-cmake] |

NHL also links plume for historical high-cut/D3D12 experiments. That does not make plume its active canonical Vulkan renderer: `OnPreSetup()` selects the SDK Vulkan subclass and `IssueDraw()` forwards to SDK Vulkan. Updating/replacing the legacy plume dependency alone is not a supported FSI optimization.

## A. CPU recompilation

### Register handling and code generation

Sonic's [U-config] sets `skip_lr`, `skip_msr`, `ctr_as_local`, `xer_as_local`, `reserved_as_local`, `cr_as_local`, `non_argument_as_local` and `non_volatile_as_local` true. [X-gen], `Recompiler::Recompile(...)`, tracks local register use and emits local `PPCRegister`/vector/condition variables instead of context-member accesses. With nonvolatile locals enabled, recognized save/restore helper calls can be omitted. The host compiler can keep more state in registers, eliminate redundant context writes and remove ABI save/restore traffic.

The **same option family is already in ReXGlue**:

- [R-config-h], `RecompilerConfig`, defaults those booleans false.
- [R-config-cpp], `ApplyToml()`/`MergeBool()`, parses and merges explicit options; absent keys preserve defaults.
- [R-manifest], `LoadBinaryConfig()`, starts from `RecompilerConfig{}` and loads the binary table/includes.
- [R-builder], `BuilderContext::r/f/v/cr/ctr/xer/reserved`, selects locals versus context fields using those options. `emit_function_call()` elides recognized save/restore helpers under nonvolatile-local mode.
- [R-init] exports effective config macros into generated headers; [R-writer] serializes the options used for generation.

[N-manifest] and its `nhllegacy_functions.toml` include contain no explicit localization/skip options. **Source inference:** regenerating from only these checked-in inputs at this pin does not explicitly enable them. **Unknown:** actual shipped-generation flags, older generator behavior, command-line overrides and generated headers. There is no tracked/generated NHL output to inspect, and no executable was read. An optimized host `-O3` build does not by itself prove register-localization options were used at code generation.

Transferable action: audit an authorized existing generated header/build manifest first; if missing flags are confirmed and hot CPU work merits it, test one conservative flag group at a time in ReXGlue. No pipeline replacement is required. Do not copy Sonic's full options block and assume safety: non-ABI helper behavior, hooks observing context state, callbacks, setjmp/longjmp and guest register conventions matter.

### Calls and dispatch

Both code generators emit direct C++ calls for resolved branches and local branches/gotos/switches where possible. [R-builder] and `src/codegen/builders/control_flow.cpp` do not route every ordinary game call through a runtime map.

Sonic's `PPC_LOOKUP_FUNC` [X-context] indexes a function table placed after the guest image using the original code offset; `Memory::FindFunction()` [U-memory-h] uses it directly.

ReXGlue **already has a corresponding fast table**. [R-indirect], `REX_LOOKUP_FUNC`/`REX_CALL_INDIRECT_FUNC`, bounds-checks a caller-module target and reads its function pointer directly. Out-of-range/unregistered cases fall back to `ResolveIndirectFunction()`, whose `FunctionDispatcher::GetFunction()` [R-dispatch] takes a recursive mutex and searches a map. Startup, interrupts and some host calls use dispatcher paths as well.

Therefore “replace all dispatch with Sonic's table” is redundant and would discard module/thunk safety. A realistic later improvement is to measure fallback frequency and reason, and optimize only if it is hot. No evidence currently places TID 7148 in indirect dispatch. Do not label a locked function lookup as the cost of every recompiled call.

### Memory access and instruction semantics

[X-context] uses volatile guest loads/stores with endian swaps; [R-init] does the same but also has physical-host-offset handling and MMIO helpers. [R-memory-builder] emits load/store and atomic-reservation operations through those helpers. Both model a 32-bit guest address space over a native base and use SIMD intrinsics/context representations, rather than translating an instruction dynamically every frame.

Sonic's direct memory translation is not a license to remove ReXGlue's MMIO/page/coherency behavior. CPU rereads of NHL equipment textures, guest shared-memory writes and runtime fault/watch behavior can depend on it. Removing volatile, byte swaps, barriers or physical aliases without proving the accessed ranges/semantics is high risk. No generic memory-access rewrite is recommended from this comparison.

### Code size, exceptions and compiler optimization

Both projects use weak/overridable guest-function wrappers and native implementation functions. Localization can reduce executable code/data traffic, but source-line count or number of `.cpp` files is not a runtime metric. Sonic's [U-lib] lists generated chunks 0–260; NHL documentation describes a different chunk count and large generated output, which is absent here. This is not an apples-to-apples code-size/performance comparison.

[X-doc] describes no general guest exception implementation and assumes ABI behavior for its aggressive options. It documents native setjmp/longjmp redirection; [X-gen] implements those call special cases. ReXGlue [R-builder] uses its own guest-address-keyed setjmp/longjmp helpers and context save/restore, with optional exception-wrapper generation represented in [R-config-h], [R-sources]. NHL explicitly configures an EA setjmp/longjmp pair and carries a conditional-branch recovery patch [N-manifest], [N-codegen-patch]. Removing LR/MSR state or unwinding support is not automatically safe because Sonic does so. In particular, register localization needs testing across nonlocal returns and hook boundaries.

Sonic release presets enable interprocedural optimization [U-presets]; root CMake uses a portable x86 Sandy Bridge target and its generated-code library requests strict FP and disables strict aliasing [U-root], [U-lib]. NHL already has Release `-O3`, x86-64-v3, ThinLTO and PGO scripts [N-opt], [N-pgo]. The SDK and executable are separate binaries; executable LTO does not automatically optimize across the DLL boundary. Installed binary flags/PGO provenance are unknown.

Transfer the discipline of explicit effective configuration and ABI-aware optimization, not `-march=sandybridge` as a performance upgrade to x86-64-v3, arbitrary fast-math, or unbounded inlining. Re-PGO can be evaluated on representative rendered AI/player matches only after an authorized build environment exists.

## B. Graphics and resource management

### Shaders, PSOs and loading integration

[XenosRecomp] converts Xenos shaders into HLSL for DXC output. [Y-doc], [Y-gen] explicitly describe Sonic-specific semantics, vertex input locations, reflection requirements and incomplete/generalization-sensitive features. [U-lib] wires it into a build-time shader cache. This is materially different from ReXGlue translating newly observed Xenos shaders at runtime.

Sonic's [U-video] `EnqueueGraphicsPipelineCompilation()`, `PipelineCompilerThread()`, asset traversal and loading hooks derive PSO combinations from Hedgehog model/material data. The `CGameModeStage::ExitLoading` hook waits for pending compilation tasks before allowing the stage to finish loading. Some known PSOs are also precompiled at boot. This moves preparation to places where the game knows what resources will soon be used; it does not mean runtime PSO construction disappears.

ReXGlue [R-pipeline] already has `InitializeShaderStorage()`, `EnsureShadersTranslated()`, `EnsurePipelineCreated()` and worker `CreationThread()`/`StorageWriteThread()`. Translation can occur on first use; worker PSO creation and persisted descriptions are not the same as full game-aware readiness gating. [R-vk] may skip presenting frames that used async placeholders, while the app's swap counter still increments [N-vk].

**Transferable pattern:** warm the pipeline combinations a scene actually needs before entering it, using valid cache identity and readiness checks. **Missing prerequisites:** NHL resource/scene boundaries, complete required state combinations, cache invalidation and evidence that compilation contributes to the present problem. Do not copy Sonic shader bytecode, hardcoded hashes, material layouts, addresses or compile-worker counts.

Both the inspected plume `VulkanGraphicsPipeline` construction and SDK `VulkanPipelineCache` graphics-pipeline creation pass `VK_NULL_HANDLE` as the Vulkan driver pipeline-cache argument [P-vulkan], [R-pipeline]. Their project-level “pipeline caches” should not be confused with evidence of a populated `VkPipelineCache`. Driver-managed caches are separate and were not measured. “Add pipeline caching” is too imprecise a recommendation.

### Textures, transfers and copy elimination

Sonic's [U-video] stores host `GuestTexture`, `GuestSurface`, shader and descriptor objects. Texture descriptor indices and GPU-side render-target layouts are tracked explicitly. `UploadAllocator::allocate()` uses mapped, aligned linear allocations from reusable upload buffers; `Video::Present()` reuses frame-indexed allocation storage after fence completion.

`StretchRect()`/`ProcStretchRect()` record logical source-surface/destination-texture relationships. `PopulateBarriersForStretchRect()`/`ExecutePendingStretchRectCommands()` decide what must be materialized, with native or shader resolves where needed. The renderer can avoid some copies because it knows the game resource consumer and intended representation.

NHL's FSI backend must preserve Xenos register/EDRAM/resolve semantics and coherency with guest RAM. [N-app], [N-sdk-patch] already skip CPU readback for resolves larger than 3 MB while retaining full synchronization for smaller equipment composites. [R-vk] `IssueCopy_ReadbackResolvePath()` waits, invalidates mapped data and copies to guest RAM; fast/some modes have delayed-data/cache-miss behavior. That is not equivalent to Sonic's resource aliasing.

**Transferable pattern:** replace coarse copy heuristics with proven consumer-aware GPU residency or selective current-data readback. **Barrier:** NHL's CPU-composited helmets/goalie equipment and other unknown consumers require correctness analysis; deleting all readbacks can render stale/incorrect textures. The existing size gate must be acknowledged rather than reintroduced as a new optimization.

Sonic is not synchronization-free: `ExecuteCopyCommandList()` executes a copy queue and waits for its fence, `Video::WaitForGPU()` drains queued work, and resize/resource paths also wait. The reviewed code does not justify “Sonic has no readbacks/waits” or transplanting its copy helper into the per-draw path.

### Queues, frame reuse and GPU timing

Sonic has a dedicated render worker that dequeues batches of up to 32 logical commands; `Video::Present()` coordinates render completion, swapchain readiness, two frame slots and fence-safe resource reuse [U-video]. Its renderer includes GPU timestamps and separate CPU update/render, present-wait, frame-fence and acquire profilers. These boundaries are a useful model for NHL instrumentation.

At plume's pinned Vulkan layer, `VulkanCommandQueue::executeCommandLists()` uses `vkQueueSubmit` with semaphores/fences and queue locking; `waitForCommandFence()` uses `vkWaitForFences`; `VulkanSwapChain::wait()` uses present-wait support when available [P-vulkan]. Abstract copy/graphics queues are not a guarantee of separate physical engines or parallel execution on this APU.

NHL already has a GPU command worker and deferred Vulkan recording. Copying Sonic's queue/thread count does not prove improved overlap. Measure guest command production, CPU recording, queue waits, GPU execution and presentation separately before changing batching or queue ownership. Correct barriers, resource lifetime, memory visibility and frame latency remain mandatory.

## C. Threading, scheduling and timing

Sonic [U-thread] creates host execution contexts for guest threads, binds PPC context/TLS and calls translated functions. Its Linux branch normally uses `std::thread`; direct pthread creation is selected for macOS stack-size handling [U-thread-h]. `SetThreadIdealProcessorImpl()` returns without setting affinity, and some priority/name behavior is Windows-only. Its guest spinlocks still retry CAS with `std::this_thread::yield()` [U-kernel]. This is not evidence that all busy-waiting has been eliminated.

NHL [R-thread] uses ReXGlue `XThread`, host Win32 threads under Proton, PPC contexts, fibers, guest CPU bookkeeping and optional affinity/priority mapping. The SDK defaults ignore game thread affinities/priorities; that does not establish the installed effective settings or actual Linux placement. `XThread0204` is the SDK default host-ID-derived label, not an identified NHL simulation/render function. TID 7148's approximately 95% CPU could include useful guest execution, spin loops, yield retries or runtime calls.

ReXGlue's spinlock acquisition, zero-duration delays and `CommandProcessor::WorkerThreadMain()`/`ExecutePacketType3_WAIT_REG_MEM()` contain spin/yield/wait behavior [R-thread], [R-kernel], [R-cp]. On the Windows backend, `MaybeYield()` uses `SwitchToThread`; small Sleep requests can become `Sleep(0)` [R-win-thread]. Sonic's use of yield is a comparison point, not a remedy to copy blindly. Adaptive sleep/atomic-wait changes require identifying a specific wait site and proving forward progress and latency bounds.

### Guest-vblank comparison: particularly important for NHL

[R-graphics] `GraphicsSystem::Setup()` chooses a guest-clock interval based on video refresh when `vsync=true`, but approximately `guest_tick_frequency/1000` when false. A 1 ms host sleep/catch-up loop calls `MarkVblank()`, increments the CP counter and dispatches a guest interrupt. [R-dispatch] `ExecuteInterrupt()` acquires a global critical-region lock and invokes the callback. [R-cp] also changes some WAIT_REG_MEM sleep/yield behavior with VSync.

That is a potential source of extra interrupt work or timing/synchronization coupling when users disable VSync for throughput. It is **not** measured proof of 1000 actual callbacks/s, a tie to TID 7148, or the cause of slow hockey simulation. Effective VSync and guest clock scaling must be verified; the app reapplies persisted settings after early environment handling [N-app].

Sonic directly hooks `CApplication::Update` to wait on swapchain readiness and record delta time [U-app]. `Video::Present()` implements a configurable sleep-plus-yield frame limiter, while [U-fps] patches particular camera, loading and gameplay timers; the `ADXM_WaitVsync` hooked routine uses a 60 Hz sleep boundary. This is an engine-specific timing strategy, not an implementation of NHL's guest interrupt contract.

**Lesson:** separate presentation limits, guest hardware-event cadence and simulation timing conceptually and in measurements. **Not transferable:** Sonic's hardcoded guest addresses, 30/60 Hz corrections, boss-step changes or delta-time clamps. Any NHL decoupling must preserve audio refill, input, engine waits, guest counters and physics timing.

## D. Native Linux lessons

Source-backed lessons from Sonic:

- Explicit platform source selection (`os/linux/*` versus `os/win32/*`) in [U-build], rather than Windows headers leaking into the common target.
- Native `mmap`/`mprotect` memory setup and a portable guest-thread boundary [U-memory], [U-thread].
- Separate renderer abstraction with SDL Vulkan integration and Windows-only D3D12 dependencies guarded in the build [U-thirdparty], [P-build], [U-build].
- Reproducible Linux presets/toolchains and release IPO settings [U-presets], [U-building].

The pin's ReXGlue already provides POSIX core implementations, GTK windowing, Vulkan selection and a POSIX app entry point [R-core-build], [R-ui], [R-helpers]. The remaining NHL blockers are the application CMake/source coupling described in report 002: unconditional D3D12/plume legacy sources and `.lib` names, Win32 diagnostics/hotkeys/process functions, VP6 child-process handling, optional texture tooling, and absent generated guest code.

Sonic's README reports a Linux CPU advantage but explicitly speculates about its synchronization cause [U-doc]. That is a project observation/hypothesis, **not an NHL benchmark**. Native Linux would retain NHL's recompiled game workload, FSI costs and readback semantics unless those were changed. A small asset-free native SDK window remains a feasible future milestone, not an immediate optimization or proof of higher FPS. No native build was attempted.

## E. Ranked transferable opportunities

Ranking balances source evidence, implementation cost, correctness risk and relevance to the existing measurements. “Potential” below is qualitative and conditional; no speedup is promised. All items are proposals requiring separate authorization; only documentation changed in this task.

| Rank / opportunity | Exact evidence and expected mechanism | NHL compatibility / change layer | Difficulty and correctness risk | Measurable validation / conditional benefit |
| --- | --- | --- | --- | --- |
| 1. Effective codegen/build audit | [U-config] enables local registers; [R-config-h], [R-builder], [R-init] already implement them; [N-manifest] lacks explicit flags. Locate which options/Release/PGO actually produced the current build. | Read-only audit of authorized existing generated header/provenance; no runtime change. Future flags belong to codegen config, not a new CPU pipeline. | Low audit cost; no behavioral risk. Generated artifacts absent here, and asset access remains outside scope. | Record effective macros/flags, binary identity and CPU hot paths. Benefit is avoiding redundant or misdirected work, not immediate FPS. |
| 2. Correctness-preserving readback-gate negative control | [U-video] shows consumer-aware copy elision; [N-sdk-patch], [R-vk] prove existing gate removes full-readback work. Temporarily disable only that gate to measure sensitivity. | Existing application-provided `NHL_VK_READBACK_MAX_LEN`; **no codegen/SDK rebuild**. Per-process environment in an approved test context. | Low implementation cost/risk relative to delayed readback: uses full readback for additional large resolves; may cause severe slowdown. Does not disable needed reads. | Compare baseline 3 MB with `=0`, same frame log/workload and simulation timing. Diagnostic benefit: shows whether removing those drains matters on Ally; not an optimization itself or proof remaining small reads dominate. |
| 3. Separate CPU/GPU/wait stage instrumentation | [U-video] separate profilers/timestamps expose acquire, fence, present and render cost; [N-vk] currently supplies swap averages. | SDK plus app diagnostic counters/timestamps, opt-in and aggregated; existing Vulkan path retained. | Low-to-medium engineering; low rendering risk if no new synchronization is inserted; probe overhead must be measured. | CPU-thread time versus wall, resolve-wait total/count, GPU timestamps and present intervals. Enables attribution; no standalone speedup claimed. |
| 4. Measured guest-vblank/presentation separation | [U-app], [U-fps], [U-video] manage timing explicitly; [R-graphics], [R-dispatch], [R-cp] reveal NHL coupling. Preserve guest event cadence independently of display policy if demonstrated wrong. | SDK timing design plus app configuration; prototype behind a default-off option. No Sonic timer constants copied. | Medium engineering; medium-to-high physics/audio/input/deadlock risk. First count callbacks and verify existing cadence before behavior changes. | Wall-normalized game clock/events, callback/interrupt CPU cost, audio continuity and p99 frame time at fixed settings. Potential useful if interrupt/pacing cost is material. |
| 5. Incremental register-localization experiment | [X-gen], [U-config] and [R-builder] show elimination of context stores and recognized save/restore calls. | Existing ReXGlue options plus **regeneration/rebuild**; SDK code changes not initially required. Hooks/context assumptions need audit. | Medium; medium-to-high ABI/nonlocal-return risk. Start a single conservative option group; do not enable skip LR/MSR/nonvolatile wholesale. | Synthetic PPC/ABI/hook/setjmp tests, generated assembly/context-store and executable-text comparison, then matched live correctness/per-frame CPU. Potential only if guest computation/context traffic is significant. |
| 6. Verify/retrain host compiler optimization | [U-presets], [U-lib] explicit IPO/FP contracts; [N-opt], [N-pgo] already offer Release, ThinLTO and PGO. | Application/generated-code compiler flags/profile; SDK optimized separately. | Medium build/profiling effort, low-to-medium portability/correctness risk when preserving FP/ABI. Not a new feature if already shipped. | Matched binaries and PGO provenance, text size, CPU samples and p95/p99 frame times. Benefit conditional on stale/missing profiles or unoptimized binary. |
| 7. Loading-aware PSO warmup | [U-video] compiler tasks and `ExitLoading` readiness gate; [R-pipeline] already caches/compiles asynchronously. Move unavoidable first-use work out of gameplay. | SDK pipeline scheduling plus NHL application/resource-loader integration; may need guest hooks. Build-time shader conversion is a separate larger step. | Medium-to-high; incomplete PSO coverage, stale cache, longer loads, worker contention and placeholder/drop correctness risks. | Count actual translation/creation events and correlate with first-visit spikes; compare warm second pass and total load time. Benefit mainly hitches if compilation is measured, not assumed sustained low FPS. |
| 8. Consumer-aware readback/copy selection | [U-video] logical surface/texture relationships; [N-sdk-patch] current byte heuristic and [R-vk] synchronous path. Keep GPU-only consumers resident while preserving current CPU consumers. | SDK renderer/cache coherency, possibly app resource hooks. Existing gate is baseline, not new work. | High; high equipment/atlas/guest-memory correctness risk. Delayed modes are not equivalent to selective correct reads. | Count bytes/waits by destination/consumer, prove CPU dependencies, validate helmets/goalies/jerseys/transitions and synchronized frame times. Potential if retained drains are critical. |
| 9. Targeted wait/fallback/worker tuning | [U-kernel], [U-thread] and [R-thread], [R-cp], [R-indirect] expose yields/dispatch; [U-video], [R-pipeline] choose compile workers heuristically. Optimize only measured hot waits/fallbacks or contention. | SDK runtime/codegen templates or one app hook, depending on site; no blanket scheduler rewrite. | Medium; medium-to-high forward-progress/latency/resource invalidation risk. Existing table fast path and shader workers must not be duplicated. | Count fallback reasons, CPU versus runqueue/wait time, time-to-ready and frame spikes; validate thread progress/audio/input. Potential conditional on site attribution, not raw 95% CPU. |
| 10. Direct game-level renderer and native-platform cleanup | [U-video], [Y-gen], [P-vulkan], [U-build] show a whole game-aware backend/platform boundary. Can bypass some guest GPU work and simplify native builds. | Major application/renderer work, shader tooling and possibly generated hooks; distinct from a bounded native SDK-window spike. | Very high renderer cost/risk; native platform cleanup medium-to-high independently. EA resource formats, EDRAM, memexport and CPU composites differ from Hedgehog. | Incremental asset-free platform milestone first; later separately authorized full visual/behavior parity and per-stage timing against FSI. Large architectural ceiling change is possible in principle, but benefit and feasibility are unmeasured. |

No separate allocator/descriptor rewrite is recommended merely because Sonic uses mapped pools/bindless descriptors. ReXGlue already has substantial resource caching/recording machinery, and earlier NHL descriptor micro-optimization reports were not decisive. Measure allocation/update/upload traffic first; copy or add only a missing capability with a critical-path cost.

## Prioritized roadmap

### Quick experiments and prerequisites

1. Obtain synchronized Desktop application-layer frame times and normalized simulation progression for **both rendered modes**. Keep 25 W/720p/1×/VSync-off/FSR/shadow settings unchanged, record actual output/caps and repeat with interleaved order.
2. Audit effective runtime/codegen/build provenance through a separately approved read-only artifact path. Do not regenerate merely to discover flags.
3. Run the readback-gate negative control described below. Preserve original files/settings and use identical warm workloads.
4. Only if first-use spikes are present, correlate existing shader/pipeline warnings and warm behavior; do not delete caches or create shader captures.

### Medium-term changes, gated by measurements

- Implement low-overhead per-stage and vblank/interrupt instrumentation if passive measurements leave attribution ambiguous.
- Investigate timing decoupling only after measuring guest callback cadence and simulation rate.
- Use existing codegen options one group at a time if effective flags and CPU hot paths justify them; preserve setjmp/longjmp and hook correctness.
- Re-PGO only after accepted hot-path changes or evidence that the shipped profile/build is unsuitable.
- Add narrowly scoped scene/asset PSO warmup if compilation events actually explain hitches.
- Replace specific proven redundant readbacks rather than switching all consumers to stale data.

### Major architectural work

A game-level NHL renderer, broad memory-semantics changes, multithreaded recording redesign and full native Linux gameplay port are separate projects. Defer them until measured cost and correctness milestones justify the effort. A Linux SDK empty-window spike can be bounded and asset-free; it is not a requirement for current Proton profiling.

## Single best low-risk experiment after frame-time measurements

**Interleaved baseline versus `NHL_VK_READBACK_MAX_LEN=0` at the existing `full` readback mode.** Baseline is the existing 3,000,000-byte gate. The negative control reinstates full CPU readback for large resolves instead of experimenting with stale equipment data. It tests the transferable principle of avoiding unnecessary resource transfers using a knob already present in NHL.

Prerequisites: establish the actual runtime honors the title patch; approve a one-session launch environment that does not edit Steam shortcuts, the playable installation or prefixes; preserve every other setting and the same per-frame logging setup. This task performs none of those actions. No launch command is supplied because the valid nonpersistent launch route is still unresolved.

Use matched rendered AI and player-controlled segments, warm-up and A/B/A ordering, then measure frame distributions, main GPU-worker/hot guest-thread CPU, labelled power and normalized game-clock progress. Severe slowdown is an acceptable diagnostic outcome; stop a pathological test rather than treating it as a playable configuration.

If gate-off is slower, that supports sensitivity to the **additional large-resolve readbacks**, not proof that all current stalls are readbacks or that reducing the gate further is safe. If unchanged, it weakens this particular lead under that workload without proving GPU- or CPU-bound execution. It does not recover invalid GPU utilization. This is selected ahead of `fast/some` because it avoids intentionally stale reads, and ahead of VSync-on/off because VSync changes several timing semantics and its environment precedence is not straightforward.

## Source catalog and link validation

All external code links below are immutable revision URLs. All **46 immutable source links** passed fresh HTTP reads through their corresponding raw URLs; paths and submodule relationships were also cross-checked against repository trees. Source contents, not search-result summaries or third-party explanations, support the technical comparison. A guessed old plume repository URL and guessed SDK template paths returned 404 during discovery; corrected authoritative paths below were used instead. No claim depends on a failed source link.

| ID | Exact path / significant functions |
| --- | --- |
| U-modules | `.gitmodules`, dependency repository URLs |
| U-config | `UnleashedRecompLib/config/SWA.toml`, enabled codegen options and helper addresses |
| U-lib | `UnleashedRecompLib/CMakeLists.txt`, CPU/shader generation and FP/aliasing flags |
| U-thread / U-thread-h | `UnleashedRecomp/cpu/guest_thread.cpp` / `.h`, `GuestThreadHandle`, `GuestThread::Start`, `SetThreadIdealProcessorImpl` |
| U-memory / U-memory-h | `UnleashedRecomp/kernel/memory.cpp` / `.h`, memory mapping and `Memory::FindFunction` |
| U-kernel | `UnleashedRecomp/kernel/imports.cpp`, `KeDelayExecutionThread`, `KfAcquireSpinLock` |
| U-video | `UnleashedRecomp/gpu/video.cpp`, `UploadAllocator`, `StretchRect`, `Video::Present/WaitOnSwapChain/WaitForGPU`, `PipelineCompilerThread`, `EnqueueGraphicsPipelineCompilation`, `ExitLoading` hook |
| U-app / U-fps | `UnleashedRecomp/app.cpp` / `patches/fps_patches.cpp`, update hook, delta-time fixes and waits |
| U-root / U-build / U-presets / U-building / U-thirdparty | Root CMake, app CMake, presets, build documentation and dependency CMake |
| X-gen / X-context / X-doc | XenonRecomp pinned `recompiler.cpp`, `XenonUtils/ppc_context.h`, README |
| Y-gen / Y-doc | XenosRecomp pinned `shader_recompiler.cpp`, README |
| P-vulkan / P-build | plume pinned `plume_vulkan.cpp` and CMake; `VulkanCommandQueue`, `VulkanSwapChain` |
| R-config-h / R-config-cpp / R-manifest / R-writer | ReXGlue config definitions, parsing, manifest loading and output flags |
| R-builder / R-init / R-indirect / R-context / R-memory-builder / R-sources | ReXGlue register/call builder, generated helpers, indirect fast path, context ABI, memory builder and generated CMake |
| R-thread / R-win-thread / R-kernel / R-dispatch | ReXGlue thread execution, Windows waits, guest kernel synchronization and function/interrupt dispatch |
| R-graphics / R-cp / R-vk / R-pipeline | SDK guest vblank, command processing, Vulkan readback and shader/PSO storage/creation |
| R-root / R-core-build / R-ui / R-helpers | SDK native platform selections and installed target helpers |

Reference definitions are clickable source URLs. Local N-* references point to repository files reviewed in this checkout.

## Files changed and validation

Only `reports/006-sonic-unleashed-architecture-comparison.md` and `reports/README.md` are changed. Validation consists of source retrieval/path/revision checks, local Markdown links, documentation whitespace and the exact staged-file allowlist before commit. No tooling changed, so no new synthetic tests were required; no performance/correctness test of an optimization was performed.

No NHL/Sonic assets, playable installations, generated game implementations or shader-cache binaries were accessed or copied. No application, SDK, renderer, generated-code, profiler or system source was modified. No build, game execution, invasive profiler, package installation, Steam setting or Proton-prefix operation occurred. Public research source files reside outside the repository in `/tmp` and are not staged.

## Outstanding uncertainties and recommended next action

The installed build/codegen provenance, TID 7148's function, input/control workload difference, vblank callback rate, active synchronization costs, shader first-use behavior and real application frame times remain unknown. Sonic's resource formats, pipeline coverage and optimization success do not establish any of those facts for NHL.

**Next recommended user action:** approve and complete the Desktop MangoHud frame-log pilot already specified in report 005, with the clarified rendered AI-versus-player workloads. After validating that baseline, approve the single gate-off negative-control experiment. Do not replace the renderer, enable all codegen flags, alter vblank timing or begin a native gameplay port on the strength of another game's results. Await further instructions after publishing this report.

[Unleashed Recompiled]: https://github.com/hedge-dev/UnleashedRecomp
[XenosRecomp]: https://github.com/hedge-dev/XenosRecomp
[U-modules]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/.gitmodules
[U-config]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecompLib/config/SWA.toml
[U-lib]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecompLib/CMakeLists.txt
[U-thread]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/cpu/guest_thread.cpp
[U-thread-h]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/cpu/guest_thread.h
[U-memory]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/kernel/memory.cpp
[U-memory-h]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/kernel/memory.h
[U-kernel]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/kernel/imports.cpp
[U-video]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/gpu/video.cpp
[U-app]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/app.cpp
[U-fps]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/patches/fps_patches.cpp
[U-root]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/CMakeLists.txt
[U-build]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecomp/CMakeLists.txt
[U-presets]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/CMakePresets.json
[U-building]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/docs/BUILDING.md
[U-thirdparty]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/thirdparty/CMakeLists.txt
[U-doc]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/README.md
[X-gen]: https://github.com/hedge-dev/XenonRecomp/blob/c5bfd90d87f2ed0db8cff5c19ea3aff0e161e527/XenonRecomp/recompiler.cpp
[X-context]: https://github.com/hedge-dev/XenonRecomp/blob/c5bfd90d87f2ed0db8cff5c19ea3aff0e161e527/XenonUtils/ppc_context.h
[X-doc]: https://github.com/hedge-dev/XenonRecomp/blob/c5bfd90d87f2ed0db8cff5c19ea3aff0e161e527/README.md
[Y-gen]: https://github.com/hedge-dev/XenosRecomp/blob/990d03b28a27b50277ee5d8d942e1c5f873869d1/XenosRecomp/shader_recompiler.cpp
[Y-doc]: https://github.com/hedge-dev/XenosRecomp/blob/990d03b28a27b50277ee5d8d942e1c5f873869d1/README.md
[P-vulkan]: https://github.com/renderbag/plume/blob/11926860e878e68626ea99ec88562ce2b8badc4f/plume_vulkan.cpp
[P-build]: https://github.com/renderbag/plume/blob/11926860e878e68626ea99ec88562ce2b8badc4f/CMakeLists.txt
[R-config-h]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/codegen/config.h
[R-config-cpp]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/config.cpp
[R-manifest]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/manifest.cpp
[R-writer]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/codegen_writer.cpp
[R-builder]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/context.cpp
[R-init]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/resources/templates/codegen/init_h.inja
[R-indirect]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/resources/templates/codegen/_indirect_call.inja
[R-context]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/ppc/context.h
[R-memory-builder]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/memory.cpp
[R-sources]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/resources/templates/codegen/sources_cmake.inja
[R-thread]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xthread.cpp
[R-win-thread]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/threading_win.cpp
[R-kernel]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/kernel/xboxkrnl/xboxkrnl_threading.cpp
[R-dispatch]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/function_dispatcher.cpp
[R-graphics]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/graphics_system.cpp
[R-cp]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/command_processor.cpp
[R-vk]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/command_processor.cpp
[R-pipeline]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/graphics/vulkan/pipeline_cache.cpp
[R-root]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/CMakeLists.txt
[R-core-build]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/core/CMakeLists.txt
[R-ui]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/ui/CMakeLists.txt
[R-helpers]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/cmake/rexglue_helpers.cmake
[N-manifest]: ../nhllegacy_manifest.toml
[N-vk]: ../renderer/core/nhl_vk_backend.cpp
[N-app]: ../src/nhllegacy_app.h
[N-cmake]: ../CMakeLists.txt
[N-sdk-patch]: ../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch
[N-codegen-patch]: ../sdk/rexglue-codegen-bcctr-tail-fix.patch
[N-opt]: ../scripts/_build_vk_opt.bat
[N-pgo]: ../scripts/_build_vk_pgo.bat
