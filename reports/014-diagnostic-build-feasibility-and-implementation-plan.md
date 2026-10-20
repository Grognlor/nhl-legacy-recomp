# 014 — Diagnostic build feasibility and phased implementation plan

## Executive summary

**The current checkout/shell cannot build NHL with the files and tools already verified present.** It lacks generated guest output and generated CMake integration, a complete pinned SDK and its installed libraries, vendored plume/other dependencies, FidelityFX build inputs, and the documented Windows compiler/toolchain environment. CMake, Ninja and Clang are not on PATH. GCC is present but targets Linux; it is not a substitute for the documented Clang/MSVC-ABI Windows build.

A separate instrumented Windows executable and matching SDK are feasible **in principle**, conditional on an authorized, complete producer/build environment. Prefer a known Windows build host over simultaneously inventing a Bazzite cross-build or native Linux port. Neither a downloaded release executable nor Steam/Proton supplies missing generated C++ or Windows development inputs. This task downloads nothing and performs no configure/build/codegen.

The safest Task 015 is **Phase A only: establish producer provenance, isolated inputs/paths and an unchanged source-baseline build**. Diagnostic code should wait until that gate passes. Then implement a bounded **CPU-only lineage/wait trace** (Phase B), validate disabled/enabled behavior, and defer independent GPU query probes to Phase C. Phase B can already reveal missing/repeated output and CPU backpressure but cannot prove device completion timing, simulation-step progress, pixel uniqueness or physical display timing.

The original playable installation, shortcuts and prefix can remain untouched during inspection, acquisition planning and compilation. A future gameplay test needs a separately approved launch/data/save/cache isolation plan: “separate exe” alone does not guarantee no writes to shared game state.

## Verified repository and inspection boundaries

Starting HEAD **`e9ed6371a5ed2c65d1a9c33e4429a08af3d8d439`**; branch **`perf/ally-investigation`**; initial working tree clean. Origin: `https://github.com/Grognlor/nhl-legacy-recomp.git`; upstream: `https://github.com/puckhead73/nhl-legacy-recomp.git`. No branch switch, fetch, submodule update or upstream write occurred.

Read the completed investigation context, particularly reports [011](011-correlated-frametime-telemetry.md), [012](012-simulation-timing-and-synchronization.md), [013](013-frame-freeze-and-catchup-investigation.md), the index, [BOOTSTRAP.md](../BOOTSTRAP.md), [DEV-README.md](../DEV-README.md), [current status](../docs/current-status.md), [Linux guide](../docs/linux.md), CMake files and build/vendor scripts. Reports [002](002-ally-profiling-and-linux-feasibility.md), [007](007-cpu-codegen-optimization-audit.md) and [008](008-generated-config-provenance-inspection.md) remain relevant to platform/provenance limits.

`/home/cody/Projects/nhl-legacy-recomp` resolves to `/var/home/cody/Projects/nhl-legacy-recomp`. Inspection covered tracked source/build documentation, component-wise existence checks of named repository build/generated/vendor paths, explicitly named tool executables/environment variables, available memory/disk, and already cached public SDK source/tree metadata under `/tmp/nhl-investigation-012` and `013`. No home-wide search, user container entry, Steam installation/prefix scan, playable file access, historical Windows path access or generated-content inspection occurred. Missing components below mean absent from these checked locations/PATH, not proof that no other machine/container has them.

Source organization: `src/` host application/hooks; `renderer/core/` title Vulkan wrapper/overlay; `gpu/` hooks/translator source; `sdk/` patches; `scripts/` build/bootstrap drivers; `tools/` packager/replay/offline analysis; `reports/` permanent records. `git submodule status` returned no entries, no root `.gitmodules` exists, and the Git index has no mode-160000 entries. **The parent project does not currently track those dependencies as submodules**: vendor scripts clone nested repositories; the SDK itself has its own pinned submodules.

## Local toolchain and resource inventory

Version queries only were executed; no compilation, graphics program, Wine/Proton, game, Steam client or container was launched. `vulkaninfo`, Steam and protontricks were located but not executed.

| Facility | Verified local result | Build meaning |
| --- | --- | --- |
| Host | Linux x86-64; 8 logical CPUs reported | Bazzite shell, not the documented Windows developer shell |
| GCC / G++ | `/usr/bin/gcc`, `/usr/bin/g++`, **16.2.1 20260819**; `gcc -dumpmachine` = `x86_64-redhat-linux` | Native compiler available; Windows MSVC-compatible link inputs/toolchain not established |
| Clang / LLVM | `clang`, `clang++`, version-20 variants, `clang-cl`, `lld`, `lld-link`, `llvm-ar`, `llvm-profdata`, `llvm-config` absent from PATH | Documented compiler, ThinLTO linker and PGO tooling unavailable in this shell |
| CMake / Ninja | `cmake`, `cmake3`, `ninja`, `ninja-build` absent from PATH | No installed-command version to report; no configure attempted |
| Python / Git / pkg-config | **Python 3.14.7**, **Git 2.55.0**, **pkg-config 2.5.1** | Sufficient for current offline/documentation validation, not NHL compilation |
| Windows build tools | `cl`, `link.exe`, `rc`, `llvm-rc`, `pwsh`, `powershell` absent from PATH | No verified VS2022/MSVC/Windows SDK environment; batch/PowerShell bootstrap cannot simply run in this shell |
| Cross compiler | `x86_64-w64-mingw32-gcc/g++` absent from PATH | No established Windows cross-build; MinGW ABI alone would not establish compatibility with MSVC SDK libraries anyway |
| Wine / Proton | `wine`, `wine64`, `proton` absent from PATH; `/usr/bin/steam` and `/usr/bin/protontricks` present | Does not imply Steam's selected Proton is missing; no runtime/prefix scan done. Proton is a runtime, not the missing compiler/SDK. |
| Vulkan development | `vulkaninfo` command exists; `/usr/include/vulkan/vulkan.h` absent; `pkg-config --modversion vulkan` finds no package | Runtime/tool availability is not a verified development SDK. Layer directories exist but contents/capabilities were not tested in this task. |
| Shader/Rust tools | `dxc`, `glslangValidator`, `cargo`, `rustc` absent from PATH | Vendored shader compilation chain unverified; Rust is only needed for optional RX2 FFI feature unless future build scope changes |
| Utilities | make/ar/ld/bash/curl/tar/unzip/zip/7z present | Availability only; fetch/extraction commands not run |
| Isolation utilities | `/usr/bin/distrobox`, `/usr/bin/podman` present | No container created, started, entered or inventoried; possible future environment route, not a ready Windows toolchain |
| Memory snapshot | MemTotal **9,848,912 KiB (~9.39 GiB)**; MemAvailable **4,972,584 KiB (~4.74 GiB)**; swap total **4,924,412 KiB** | Shared-memory pressure matters for large optimized/LTO builds. These are a momentary snapshot, not a build benchmark. |
| Repository filesystem | **474.35 GiB total, ~70.22 GiB free** at inspection | Free space does not establish sufficient capacity for Windows tools, dependencies, FFX permutations and multiple SDK/game builds. |

Whitelist environment checks all returned unset: `REPO_ROOT`, `REXGLUE_SDK_SRC`, `REXGLUE_SDK_BUILD`, `REXGLUE_SDK_INSTALL`, `REXGLUE_FFX_PREBUILT`, `CMAKE_PREFIX_PATH`, `VULKAN_SDK`, `VCVARS64`, `CC`, `CXX`, `CMAKE_TOOLCHAIN_FILE`, `INCLUDE`, `LIB`. No broad environment dump or credentials were read. These results agree with report 002's missing Clang/CMake/Ninja/PowerShell inventory; no new build-readiness discrepancy was found.

### Existing inputs/artifacts checked

Absent: `generated/` (therefore its init/header/source lists and `generated/rexglue.cmake`), `generated.bak_080/`, `third_party/` (therefore SDK/plume, SDK build/install and FFX prebuilt paths), `tools/xenos_recomp/`, `out/`, root `build/`, `pgo/`, and `CMakeUserPresets.json`. Descendant symlinks were not followed. Root directory inventory exposed no alternate local build/vendor tree; no broader search was performed.

The `/tmp` public research cache contains selected flattened SDK source files and Git tree metadata, **not** a checkout: no root SDK `CMakeLists.txt`, `.git`, installed CMake package, generated include tree or link libraries there. Treating that cache as the SDK would be incorrect. This confirms report 008's build-artifact absence rather than superseding it with a usable SDK.

## Required build inputs and verified requirements

| Input | Evidence and requirement | Present / verified? |
| --- | --- | --- |
| Generated integration | [CMakeLists.txt](../CMakeLists.txt), **5–12**, includes `generated/rexglue.cmake` before normal target setup. | **Missing**; configure would already lack its required include even if CMake were installed. |
| Matching generated guest implementation | [src/main.cpp](../src/main.cpp) includes `generated/default/nhllegacy_init.h`; generated output must include all matching translated translation units, init/registration implementation, source lists/build helpers and image metadata needed by that generation. | **Missing**. Exact producer output inventory and hashes are not available; do not substitute one header for the complete generation. Historical docs describe ~181 files; `.gitignore` estimates ~374 MB per generated tree, not measurements here. |
| Codegen inputs, if regeneration ever becomes necessary | [manifest](../nhllegacy_manifest.toml), function include, supported original XEX, exact generator/SDK/options/template identity and scanner patch. | Manifest/include exist; its Windows game paths are historical, not locally verified inputs. No XEX/assets were accessed. Regeneration is **not authorized** and is not a shortcut around missing producer outputs. |
| ReXGlue source/package | [setup_sdk.ps1](../scripts/setup_sdk.ps1), **12–39**, pins **`bd9b51918faa71f962fa38af6d5f744af9aba2ce`**, applies title Vulkan patch plus conditional-bcctr scanner patch. | Patch sources exist; complete SDK source, dependency checkouts and installed headers/import/static libs absent. |
| Renderer/codegen patches | [title patch](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch), [bcctr patch](../sdk/rexglue-codegen-bcctr-tail-fix.patch) | Present as patch text; not applied to any verified local SDK. Preserve FSI renderer behavior/readback gate and scanner semantics. Do not apply the historical `docs/` patch in addition. |
| SDK dependencies | Cached immutable SDK tree shows gitlinks for FFmpeg, catch2, cli11, fmt, glslang, imgui, inja, libmspack, o1heap, SDL3, simde, snappy, spdlog, SPIRV-Headers/Tools, tomlplusplus, Tracy, utfcpp, volk, Vulkan-Headers/VMA and xxHash. Parent SDK pin fixes their gitlink identities. | Metadata only; no dependency checkout/build verification. Optional target settings determine which are actually built. Prior Linux-support findings remain source evidence, not local configuration. |
| Project plume | [fetch_thirdparty.ps1](../tools/fetch_thirdparty.ps1) pins `renderbag/plume` **`4f556be1531698174a597e7e0a215c22d3238a24`**. CMake **116–134** unconditionally adds plume, D3D12/DXGI libraries and its shader-generation helpers even though high-cut runtime paths are reference-only. | **Missing**, mandatory for current CMake graph; do not remove it to simplify this first diagnostic build. |
| Project shader tool checkout | Same script pins XenosRecomp **`990d03b28a27b50277ee5d8d942e1c5f873869d1`** under `tools/xenos_recomp`. | Missing; part of documented bootstrap/tooling. Current root CMake does not directly add that checkout as a target, so do not claim it is independently required for every already-generated baseline without producer verification. |
| Project glslang | CMake **141–180** FetchContent tag **14.3.0**, followed by an in-place `SpvBuilder.cpp` patch. Separate from SDK's pinned glslang gitlink. | No `_deps`/cached configure tree. Tag's resolved commit and patched source hash should be recorded before reproducible builds. |
| FidelityFX | [FFX configure](../scripts/_ffx_sdk_configure.bat), [FFX DLL build](../scripts/_ffx_dll_build.bat): Vulkan backend and FFX enabled; documented Visual Studio 17 2022 x64 step builds/stages `amd_fidelityfx_vk.dll` and import `.lib`. | SDK's downloaded FFX source/prebuilt package, compiler inputs, resolved dependency identity and staged DLL/import lib **not available or verified**. No binary was inspected. |
| Windows compiler/SDK/shader tools | BOOTSTRAP requires **Clang 20+**, CMake **3.25+**, Ninja, **VS2022 Desktop C++**/Windows SDK environment, Vulkan SDK (developer used **1.4.350.0**). Root CMake requires **C++23** and C. | Not established locally. Prior report 002's SDK Linux Clang 18+ requirement is a different platform/minimum, not a replacement for this documented Windows setup. |
| Native link configuration | CMake **182–197** expects config-specific Windows snappy `.lib` and RenderDoc include layout; current scripts use lld for ThinLTO inputs. | Missing installed SDK package/library tree. Debug/Release/RelWithDebInfo library/compile-definition compatibility needs verification. |
| Optional RX2 FFI / other payloads | CMake **199–213** warns and disables `.dds` override support if `tdb-rx2-ffi` missing. Packager/replay targets **218–231** are optional; FFX/FFmpeg runtime staging is documented separately. | Private FFI is **not a mandatory baseline compile blocker**. Its absence may change behavior versus a producer build. Runtime payload inventory must be explicit before later tests, without copying game assets. |
| PGO/effective codegen/native flags | Optimized/PGO scripts exist; original eight codegen settings remain Unknown (reports 007/008). | `pgo/` absent. PGO-use build is not ready. A fresh non-PGO source baseline is not proof of v0.6.0 binary-equivalent performance. |

A complete matching generated artifact bundle **may** avoid reading/regenerating from the original image for compilation. This must be checked against its generated CMake dependencies/custom commands first: do not assume a normal target cannot automatically invoke codegen or depend on a game image. Any transfer/inspection of game-derived producer files needs explicit authorization; none is requested or performed implicitly by this plan.

## Build process review and discrepancies

The documented order is: pinned SDK/dependency setup → FFX configure/bootstrap → Visual Studio FFX build → SDK configure/build/install → codegen → application configure/build. This task reads those commands; it does not execute any of them.

Important corrections to avoid accidental changes in a later authorized task:

1. **Environment override documentation is broader than actual script behavior.** BOOTSTRAP/`_env.bat` prose says locations can be overridden; `_env.bat` **16–20** only preserves an externally set `REXGLUE_SDK_SRC`. It unconditionally derives/overwrites SDK build/install/FFX paths and repository root. Merely setting `REXGLUE_SDK_INSTALL` or `REXGLUE_SDK_BUILD` is not a safe isolation plan.
2. **Configure is not read-only.** `_ffx_sdk_configure.bat` **4–6** deletes `CMakeCache.txt`/`CMakeFiles`. Root CMake downloads through FetchContent and patches glslang source in place. Plume shader helpers may acquire DXC. No configure/dry-run invocation was used to inspect readiness.
3. **Build outputs are hardcoded or relative.** `_build_vk_opt.bat`/PGO scripts reset BDIR under the source tree; `_game_ffx_build.bat` uses a working-directory-relative `out/build` path. FFX builds may write source-relative `ffx-api/bin` and shared `%USERPROFILE%/_ffxbuild/vk`. Future isolation must include source/dependency/build/install/stage trees, not just a final exe filename.
4. **Comments are not authoritative flags.** `_build_vk_opt.bat` mentions retaining RelWithDebInfo in stale commentary, while the actual command selects `Release`. PGO script also has a stale `rd` runtime comment. Use actual configure commands/cache/compile commands and imported target properties, never a suffix/comment alone.
5. **“Reference-only” paths still compile/link.** CMake unconditionally links plume/D3D12/DXGI and translator support. Linux presets do not remove Windows dependencies. Native Linux is a separate port; do not start it as diagnostic preparation. A Linux cross-build needs explicit MSVC-ABI headers/libs, shader/host tools and handling of Windows-only scripts/FFX generator; none is verified. MinGW or Proton alone does not supply these.
6. **Bootstrap parity is not shipping parity.** BOOTSTRAP documents a missing SDK color-grade pass with no-op compatibility cvars; optional RX2 FFI and original PGO inputs may differ. `docs/current-status.md` retains old machine paths, historical release claims and `-march=native`/supersampling statements superseded by newer scripts/docs. Do not infer Ally performance, current build paths or native compile flags from them. The manifest's generator-version comment/SDK-version label likewise does not identify the installed generation.

No discrepancy invalidates reports 011–013's measurements; they reinforce the build/provenance limitations. Original reports are preserved rather than rewritten.

## Feasibility verdict and isolation

1. **Can this local repository produce an instrumented NHL executable now? No.** Required files and the supported toolchain are not present/verified; even normal configuration has missing generated integration and vendor inputs.
2. **Are generated artifacts verified? No.** Header/config/source inventory and effective options are Unknown. Do not recompile a partial or differently configured guest generation to make a diagnostic appear ready.
3. **What environment is preferred?** An established **Windows x64 producer host** with Clang/MSVC-ABI build tools, VS2022/Windows SDK, Vulkan development SDK, CMake/Ninja/PowerShell, complete pinned dependencies and matching generated output. Record exact versions. An isolated local VM/cross-toolchain is possible future engineering, not established here; a Linux container would still need Windows-target inputs and tool compatibility.
4. **Can the playable installation remain untouched? Yes for preparation/compilation/staging.** Do not use it as a source of executable/DLL/generated input files or run the end-user builder/packager. Later gameplay may read game data and write saves/logs/cache; access and isolation require a separate approved plan, not an implicit exemption.
5. **Safest output location:** a new dedicated source/build/stage root, never the installation/prefix/shared SDK install. Proposed Bazzite planning root **`/var/home/cody/Projects/nhl-legacy-diagnostic-builds/task015/`**, verified before future creation; on a Windows producer prefer a short **`C:\nhldiag\t015\`** to avoid FFX path-length problems. These paths are proposals and were not created/inspected as existing inputs. Keep runtime diagnostic logs under separately validated `~/nhl-ally-profiles/`.

Use immutable/exported source snapshots of the approved commit and private dependency copies, with distinct `baseline` and `diagnostic` SDK prefixes, CMake output trees and runtime stages. Do not switch this working branch or overwrite a shared SDK prefix. Pin `CMAKE_PREFIX_PATH`/package resolution to the intended private SDK and record all resolved imported paths; use app-local DLL staging so the diagnostic cannot load a shipping/shared runtime by accident. No global PATH/library/environment change is needed.

### Space and resource budget

~70.22 GiB free here is a snapshot, not proof of enough build space. Historical generated source estimate is ~374 MB/tree and ~13.4 million lines in comments; vendor scripts mention hundreds of MB, but build intermediates, LLVM bitcode, PGO, shader permutations and installed libraries can dwarf sources. No complete local build exists to measure peak disk/RAM usage.

Planning reserve: **50–100 GiB free on the chosen build volume**, excluding any Windows OS/VM image and game data, plus margin if several optimized copies/FFX variants are retained. This is an engineering reserve, not a measured minimum. A producer with ~16–32 GiB RAM is preferable for large optimized builds; current ~9.39 GiB total shared memory/~4.74 GiB available suggests conservative build parallelism would be needed if a suitable local toolchain were later established. Do not set jobs, install a VM, allocate storage or alter power/scheduling now. Recheck disk and input byte inventories at Phase A before authorizing actual builds.

## Report 013 design review: required implementation corrections

These are planning corrections/acceptance conditions; no code is changed.

| Area | Feasible approach / correction | Validation gate |
| --- | --- | --- |
| G/W guest/ring tracking | Count `VdSwap_entry` entry/exit and write-pointer publications separately. Defer exact G→C packet side-table matching in initial Phase B; indirect buffers, concurrent writers, ring wrap and reused packet locations can defeat naive FIFO equality. No guest packet edits or memory dump. | Synthetic wrap/reuse/concurrency tests; unmatched stays Unknown, not latency. |
| C/F/S IDs | Use separate session-local CP swap/frame/submission identities. `counter_` also advances at vblank; allocation version/slot is not per-frame identity. Only close F on actual frame close, not every `EndSubmission(true)` helper invocation. Distinguish empty/failed/auxiliary/paint submissions. | Double-close, skipped refresh, multi-submit and failure tests. |
| R mailbox sidecars | Set R under the **producer's existing slot ownership and release publication**, copy it under the consumer's acquired-slot lifetime. The consumer mutex is not a new producer lock and must not be assumed to synchronize a producer that never takes it. Verify same-slot/relaxed paths and reuse carefully. Preserve existing GPU resource synchronization. | Model/interleaving tests for new, repeated, overwritten, inactive and resized output; R is CPU lineage, not pixel uniqueness. |
| P / paint tracking | Carry the copied R through the exact paint and accepted/failed present result. Never re-read “latest R” after an old paint. Record thread role, swapchain epoch and blank output. | UI/CP mode change, reconnect, failed acquire/present and repeat/drop tests. Return time is not scanout. |
| DLL ownership / ABI | One SDK-owned trace service/session and shared C-compatible event schema/export boundary; avoid duplicate header-static trace registries in exe and DLL. Prefer private sidecars rather than public class/vtable changes. If host layouts change, rebuild all affected consumers with matching headers. Never change `PPCContext`, guest register layout, codegen flags or generated functions. | App/runtime/package build manifest, event-size/enum checks, matching ABI/feature macros and source provenance. No mixing rebuilt headers with old DLLs. |
| Thread safety and lifetime | Preallocated per-producer SPSC buffers with release/acquire commit and explicit native-thread registration generations. TID reuse/churn must not relabel old data. Cross-thread `active_phase` snapshots must be atomic/sequence-validated, not unsynchronized reads of CP, mailbox or fence containers. | Full/wrapped/partial records, producer disappearance, concurrent disable, registration-capacity and race-oriented synthetic tests. No shared logger mutex on render paths. |
| Wait durations / nesting | Bracket existing queue-lock acquisition separately from API call/wait. Nested waits must not be double-counted as additive time; retain total/inclusive/exclusive definitions. Aggregate cheap draw/resource counts, not timestamps per draw. Do not move locks or add waits. | Nested-span tests and entry-only unfinished-span handling; trace loss invalidates exact counts. |
| Timestamp correlation | Same process QPC/frequency across exe/SDK; preserve ticks as integers. Pair QPC/UTC brackets for external notes/collector; Python monotonic epoch is not assumed equal. Scene markers include human/focus uncertainty. | Ordering/clock-step/missing-marker decoder tests; no false microsecond alignment. |
| Completion observations in B | Record existing fence-owner updates and wait returns only; do not have the writer poll reusable runtime fences or inspect mutable queues. Flat completion counter can mean no polling. | Decoder explicitly separates “not observed” from “GPU not complete”; no assertion of device busy time. |
| GPU query pools in C | Separate guest-output and paint completion markers are needed to avoid overlooking FSR/UI GPU work. Use immutable per-capture slots, known-complete reset before observation, legal queue stages, valid bits/period/wrap and dedicated ownership. Deferred command encoding must preserve order. No WAIT/PARTIAL reads, per-frame queue-idle or new image readbacks. | Capability checks on the actual diagnostic runtime/device; order/lifetime tests and small bounded query trial after separate authorization. Never query an uninitialized/reset-in-flight slot as completed output. |
| Query observer cost | Report 013's 5 ms/64-slot schedule is a design ceiling, **not a safe default established by measurement**. Begin with fewer batched nonblocking checks (e.g. nominal 20 ms), recording actual poll span/coverage; increase only when overhead evidence and diagnostic need justify it. Distinct pools/committed ranges simplify batching and ownership. | `VK_NOT_READY`/availability handled per slot; unavailable result values never used. Record observer descheduling, slot exhaustion, failed submit and driver-call overhead. |
| Budgets / output paths | Preserve 90 s, 16 MiB event pool, ≤17 MiB files as upper bounds; size type-specific payloads rather than stuffing every ID into each 64-byte record. Enforce file quota, producer/slot caps and drop counters. Windows path must map to canonical trusted home output outside prefix/install. No cwd fallback or per-frame flush. | Synthetic quota/symlink/traversal/exclusive-file/decoder truncation tests, then separately authorized mapped-path check. Python's path safety does not automatically implement Win32/Wine path safety. |
| Capture stop / destruction | Stopping capture disables new records/probes; **does not free active query pools or buffers immediately**. Keep service alive until producers cannot emit; stop/join observer before device destruction, and retire queries only after normal GPU lifetime guarantees. Never join a writer/observer while holding queue/paint locks. | Shutdown order tests: duration/file-full, pending GPU, device loss, partial file, exception, process teardown. No blocking writer backpressure or added mid-game GPU drain. |

Report 013 already acknowledges many of these risks; this report makes them implementation gates and **moves GPU probing out of the first patch**. Phase B should not inherit the full report's independent GPU-completion claims.

## Phased proposal for a future authorized Task 015

These phases are not execution authorization. Each phase has a stop gate; Task 015 should initially authorize only Phase A's concrete, approved scope.

### Phase A — reproducible isolated source baseline

1. Identify a willing build producer/host and obtain a **non-asset inventory/provenance manifest first**: source/SDK/dependency revisions, applied patches, generator/templates/config flags, compiler/linker versions, exact generated file list/hashes, native flags and PGO identity if used. No game assets or generated files are copied merely to complete inventory.
2. Agree explicit authorization for any required dependency acquisition, tool installation or producer artifact transfer. Matching generated artifacts are preferred to regeneration; if unavailable, stop and ask about a separately scoped generation workflow rather than using the playable installation.
3. Define private source/dependency/build/SDK-install/stage paths and inspect the configure graph for network/codegen/source mutations. Use offline-populated dependencies/private copies. Do not execute current destructive/shared-prefix scripts as-is; a reviewed isolated invocation plan is needed. Preserve the canonical FSI/Vulkan/FFX feature set and codegen/ABI configuration.
4. Once authorized and inputs complete, produce an **unchanged source-baseline** application and SDK in private stages. Disable unrelated packager/trace-tool targets if scope permits; do not run `package.ps1` or an asset-consuming integration test. Verify that normal target builds did not invoke codegen. Record actual dependency/link resolution, compile commands, artifact inventory and hashes of newly produced artifacts only.
5. Before any gameplay test, establish the separate runtime launch and data/save/cache plan. Do not equate this baseline with the installed v0.6.0 without producer evidence; differences such as non-PGO, optional FFI or missing color grade must be disclosed.

**Exit gate:** complete, reproducible matching-input build and documented differences, ABI/library-feature agreement, isolated outputs, no playable/prefix/system modification. If required inputs remain missing, Phase A is blocked and instrumentation does not start.

### Phase B — CPU-only lineage and wait spans

Implement the smallest useful vertical slice in private/reviewable source changes: SDK trace service with default-off gate and bounded writer; G/W/C/F/S counters; exact R→P mailbox lineage and outcomes; queue-acquire, submit, acquire-image, present and existing fence/readback wait spans; minimal per-frame draw/readback summaries and manual scene notes. GPU pools/probes, exact guest-packet G→C matching, broad PSO/resource tracing and unidentified simulation hooks stay out of the initial patch. Add other aggregate counters only if needed after the vertical slice works.

Use existing Report 013 source sites (`VdSwap_entry`, CP worker/`XE_SWAP`, Vulkan `BeginSubmission`/`EndSubmission`, `RefreshGuestOutput`, `ConsumeGuestOutput`, `PaintAndPresentImpl`). Private host metadata only. Build a separate diagnostic-capable SDK and exe with the **same native/codegen feature settings** as A; do not turn on all Tracy/SDK profiling to obtain a few counters. Existing Release scripts intentionally compile generic counters/profiling out; environment variables cannot restore that code, and changing those macros can change compatibility/overhead.

Asset-free synthetic tests should validate the event schema/buffer/decoder, mailbox state model, trace drops, path handling, invalid timestamps, frame close, producer reuse and cleanup before any authorized game run.

**Useful evidence:** G/W/CP progress gaps, CPU queue/wait spans, new outputs versus repeated/overwritten R, host paint scheduling and generation-to-present age. This can localize starvation/backpressure and establish repeated producer output during marked close-ups.

**Still ambiguous:** actual GPU completion when the owner stops checking fences; shader execution versus semaphore waiting; active GPU time; true simulation/animation step count, unique pixels, physical display delivery and input latency. New R is not a new pose. Phase B can justify a focused next probe without claiming all A/B/C cases are solved.

### Phase C — independent GPU output and paint completion, only if needed

First inspect capabilities through the authorized diagnostic's initialized device and confirm safe reset/availability support; do not run a standalone Vulkan probe now. Preserve the existing queue/render/readback policy. Implement one end marker for successful R and one for paint P, with separate query/lifetime management and bounded asynchronous availability checks, as refined above. No start/end per-pass profiler, CPU readback of images or new blocking query. If capability/lifetime correctness cannot be demonstrated, leave this phase disabled and document GPU Unknown.

Test supported/unsupported capability, reset completion, failed submit, slot exhaustion, wraparound, partial readiness, observer descheduling and shutdown/device loss. Unavailable/missing marker results must never be used as a GPU-stall verdict. Device timestamps remain separate from QPC unless calibration is separately verified. GPU query instrumentation changes command streams slightly; its effect must be measured, not assumed negligible.

### Phase D — controlled diagnostic comparison

After separate launch approval, compare **A source-baseline**, **diagnostic-capable build disabled**, and **the same diagnostic-capable build enabled**; CPU-only and GPU-enabled traces are separate steps if C is needed. Disabled versus enabled alone does not detect compile-time/layout overhead relative to baseline. Keep compiler/SDK/runtime and codegen flags constant across the relevant comparison; no FPS cap, no extra overlay, no cache clearing or settings/power/scheduler changes.

Use marked scenarios **A introduction** (no assumed cinematic slowdown), **B wide-angle continuous play**, **C bench/player close-ups as highest priority**. Gather multiple naturally occurring C segments rather than silently dropping the worst shots. Manual clock-rate samples from report 013 are context, not normal-animation proof. Compare freshness/repeat age, CP progress and wait distributions, then independent completion where available. Input/motion notes and timing uncertainty accompany each trace; absence of a freeze is a valid non-reproduction outcome.

**Acceptance gate:** disabled/enabled run behavior sufficiently comparable for attribution, no new correctness/lifetime errors, bounded output with explicit loss/coverage, and no violation of installation/prefix/runtime constraints. If a probe changes the symptom materially, stop interpreting it as representative; simplify/disable it and preserve evidence.

## Isolation, rollback and estimated complexity

Compilation needs no playable installation access. Source/dependencies/generated outputs must be separately authorized and privately staged; no hardlinks or shared mutable caches back into the playable tree. Baseline/diagnostic DLL search paths and CMake install prefixes are separate. Do not let FFX source-relative outputs, shared SDK install scripts or PGO paths overwrite another build. Keep report/offline data public, but generated/proprietary inputs and runtime binaries outside Git unless separately authorized.

Runtime isolation is a **separate gate**: normal game reads/writes may touch settings, saves, cache or assets even from a second exe. Preserve the original game/shortcut/prefix and require an approved independent test-data/write-routing method. This plan neither creates another prefix nor assumes the existing prefix may be modified. If no route meets those constraints, finish build-only verification and stop. Rollback of a future test is a later approved normal exit and return to the original route; no file replacement or automated termination is necessary. Capture cessation is distinct from destroying SDK/GPU resources or unloading instrumentation.

Rough engineering effort **after inputs, access and authorization exist**; not a delivery commitment or measured build time:

| Phase | Estimated implementation/validation effort | Main uncertainty |
| --- | --- | --- |
| A: establish reproducible source baseline | ~1–3 engineer-days on an already provisioned Windows producer | Missing generated provenance/dependencies may add indefinite external lead time; tool provisioning/cross-build work is additional. |
| B: CPU-only trace, decoder and synthetic/concurrency validation | ~3–6 engineer-days | DLL integration, mailbox ownership and reliable bounded logging; source/ABI gaps can extend this. |
| C: independent GPU queries and lifetime/overhead validation | ~3–6 engineer-days, optional and deferred | Deferred encoder support, reset/capability/driver behavior, teardown correctness. |
| D: scene comparisons and interpretation | ~1–3 engineer-days | Natural bench/close-up occurrence, baseline comparability, measurement overhead and user availability. |

Approximately **2–4 engineer-weeks** for A–D in a suitable environment is a planning range; unknown producer inputs and baseline mismatches can dominate. Phase B can be delivered/evaluated independently of C. Building natively on Linux or establishing a new MSVC cross-toolchain is extra scope, not included in those estimates. Do not begin a port to obtain the diagnostic.

## Specific prerequisites and recommended next action

Before Task 015 can authorize build work, resolve:

- Named Windows producer/build host, exact toolchain and permitted installation/dependency-acquisition scope.
- Complete matching generated-output inventory and provenance; explicit permission for any game-derived file access/transfer. No automatic generation from the installed game.
- Complete SDK pin/patch/submodule/FFX/plume/glslang inventory, private output layout and sufficient disk/RAM; no shared-prefix/dependency mutations.
- Known compiler/codegen/profiling/PGO/feature configuration, with baseline differences from v0.6.0 explicitly accepted rather than hidden.
- A reviewed isolated build invocation plan that avoids destructive scripts, implicit downloads/codegen and end-user packaging/install flows.
- Separate agreement for any runtime smoke test, data/save/cache isolation and launch method. A build-only authorization is not permission to run NHL or change Steam/Proton.

**Recommended next action:** ask the existing build producer for the non-asset provenance/inventory and choose the isolated Windows environment. Authorize a narrowly scoped **Phase A** only once those prerequisites can be made concrete. Do not start Phase B simply because the source sites are identified, and do not implement Phase C in the first patch.

## Files changed and validation

Only `reports/014-diagnostic-build-feasibility-and-implementation-plan.md` and `reports/README.md` change. Read-only checks: Git branch/status/remotes/index/submodule metadata, tracked docs/scripts/CMake, named output-path existence without symlink traversal, PATH tool/version/native target, whitelist environment, disk/RAM and cached public SDK metadata. No dependency download, submodule update, container initialization, CMake configure, compiler build, codegen, GPU probe or application execution occurred. Existing **32 offline synthetic tests pass**; local links/source references, documentation whitespace and final staged-file allowlist checked before commit. No source/test changes, raw files, binaries or generated guest files are staged. Push only to origin's investigation branch and stop.
