# 007 — CPU codegen optimization audit

## Objective and executive findings

Audit the eight register-localization/state-elision options without generating code, building, launching NHL, or reading its installed executable or generated game artifacts. Target: ASUS ROG Ally Z2A, Bazzite 44, Proton Experimental, Windows NHL Legacy Recomp v0.6.0.

**Verified:** NHL's tracked manifest and include do not set any of the eight options. The pinned ReXGlue generator supports all eight and initializes all to false. Sonic's pinned configuration explicitly sets all eight true. **Conditional inference:** a fresh generation using the inspected NHL inputs, pinned generator, stock templates and no external modifications would leave all eight false. **Unknown:** the settings actually used to produce the installed executable. Tracked source, script intent and a release tag do not establish that provenance.

**New prerequisite:** these options affect the layout of `PPCContext`, not just local instruction selection. The SDK header conditionally removes fields, while pinned runtime thread save/restore code accesses those fields. NHL diagnostics also access `ctx.lr`. Generator support is therefore insufficient evidence that simply adding a flag is compatible with the existing SDK binary. Audit the complete runtime/application ABI before any experiment.

No settings were enabled. The recommended next step is an explicitly authorized inspection of the matching build's generated configuration block and provenance, followed by synchronized frame-time measurements. Do not regenerate merely to discover what an existing executable used.

## Scope, checkout and evidence

Starting HEAD: `86363221563ca7811c041d96bd41ead38861497b`; branch `perf/ally-investigation`; origin `https://github.com/Grognlor/nhl-legacy-recomp.git`. Initial working tree was clean. Read reports 001–006 and the index; inspected tracked configuration, SDK patches, scripts, packaging code, source hooks, Git metadata and pinned public SDK source. No installation paths referenced in the manifest were followed.

Source revisions:

- NHL references below use starting HEAD, preserving this audit's inputs.
- ReXGlue: `bd9b51918faa71f962fa38af6d5f744af9aba2ce`, pinned by [SDK setup][N-setup], plus the tracked Vulkan/title patch and [conditional-bcctr scanner patch][N-patch]. Searches of these patches found no changes to the eight configuration flags or `PPCContext` definition.
- Unleashed Recompiled: `cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c`; [SWA configuration][U-config]. Its XenonRecomp submodule revision established in report 006 is `c5bfd90d87f2ed0db8cff5c19ea3aff0e161e527`. Sonic does not use ReXGlue; identical option names do not prove identical integration contracts.

Historical telemetry remains contextual: both AI-versus-AI and player-controlled captures were **rendered matches**; process CPU was approximately 335% of one logical core, including the approximately 94.9% hot thread. These overlap and must not be added. Lower live GPU clocks do not establish CPU codegen as the cause. No synchronized frame-time baseline or proven bottleneck exists. No new telemetry was collected for this task.

## Option inventory

In this table, **absent** means no explicit key in `nhllegacy_manifest.toml` or its only include, `nhllegacy_functions.toml`; it is not an observed value in a generated build. **Unknown** applies to the installed executable for every row. Risk rankings are engineering judgments, not measured failures or guarantees.

| Option | Pinned SDK support / default | Tracked NHL value | Verified installed effective value | Generated-header marker when true | Correctness concerns / relative priority |
| --- | --- | --- | --- | --- | --- |
| `ctr_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_CTR_AS_LOCAL` | Function-local CTR for loops and indirect dispatch; validate call boundaries, callbacks and context ABI. First localization candidate after ABI gate; medium risk. |
| `xer_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_XER_AS_LOCAL` | Carry, overflow and summary-overflow state; cross-call/condition dependencies and nonlocal return need tests. Medium risk. |
| `reserved_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_RESERVED_AS_LOCAL` | Reservation state participates in load-reserve/store-conditional emission; verify lifetime, retry paths and helper boundaries. Higher risk; defer. |
| `cr_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_CR_AS_LOCAL` | Localizes all eight CR fields; cannot assume arbitrary callees/helpers obey required preservation conventions. Higher risk. |
| `non_argument_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_NON_ARGUMENT_AS_LOCAL` | Groups r0/r2/r11/r12, f0, v32–63. A single flag changes several register classes and context layout; audit r2 and nonstandard helpers. Medium-to-high risk. |
| `non_volatile_as_local` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_NON_VOLATILE_AS_LOCAL` | r14–31, f14–31, v14–31/v64–127; recognized save/restore calls can disappear. Guest ABI, context capture and EA nonlocal returns require detailed validation. High risk. |
| `skip_lr` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_SKIP_LR` | Omits LR operations and removes context LR. NHL diagnostics read that member; blindly enabling can cause compilation failures and loses caller-state visibility. High risk. |
| `skip_msr` | Yes / false | Absent; fresh-input inference false | Unknown | `REX_CONFIG_SKIP_MSR` | Suppresses emitted MSR reads/writes, fences and global interrupt-lock operations, and removes context MSR. Synchronization/correctness change; high risk, last. |

Support/default evidence: [RecompilerConfig][R-config-h], fields at lines 82–90. Parsing evidence: [ApplyToml / MergeBool][R-config], lines 96–114. Register selection: [BuilderContext accessors and calls][R-builder]. LR and MSR emission: [control-flow builders][R-flow] and [system builders][R-system]. Header recording: [writer][R-writer] and [init template][R-init]. Reservation access: [memory builders][R-memory].

## Configuration and override path

1. [Manifest `LoadBinaryConfig`][R-manifest] creates a fresh `RecompilerConfig{}` and loads the entrypoint table using `LoadFromTable`. Options belong to `[entrypoint]` in this project, or the top level of an included option file; putting them under `[project]` or `[functions]` would not use this parsing path.
2. [ApplyTableWithIncludes][R-config] loads includes depth-first in listed order, then applies the including table. Later includes can override earlier ones; explicit keys in the parent win. `MergeBool` preserves the previous value when absent and accepts explicit false as an override. Wrong-typed values are not equivalent to a supported boolean override.
3. NHL's [manifest][N-manifest] includes only [functions][N-functions], which supplies function analysis entries, not these flags. Neither file requests custom templates. No matching flag settings were found in tracked TOML/build scripts/CMake configuration.
4. [ProjectRecompiler::Run][R-project] moves the loaded configuration into `CodegenContext`. Its exception-handler override concerns a separate option, not these eight. The inspected [CLI registration][R-cli] exposes a config path and module targets, not eight dedicated localization switches. [Codegen CVars][R-cvars] cover analysis/output limits; these eight are configuration booleans, not the listed CVars. No runtime environment-variable route to turn them on was established.
5. Alternative config files, private includes, a modified generator/API caller, or custom templates could change a producer's output. Those are possibilities, not evidence that the installed build used overrides. `template_dir` is a supported configuration field and the writer renders templates; custom output must be considered when interpreting provenance.

This is a generation-time decision. Adding a compiler `-DREX_CONFIG_*` afterward cannot safely transform already emitted context-member code into register-local code, and can instead remove members that the emitted code references. A runtime setting cannot retrofit these optimizations into an existing executable.

## Where effective settings are recorded

[CodegenWriter::buildTemplateData][R-writer] serializes all eight values as `config_flags` (lines 82–90). The writer renders `{project}_init.h` (lines 200–203). For the tracked project name/output directory, the expected artifact is **`generated/default/nhllegacy_init.h`**; [src/main.cpp][N-main] includes that exact path.

The stock [init header template][R-init] starts a `Project Configuration` block with `REX_CONFIG_H_INCLUDED`, conditionally emits the eight markers above, then defines image constants and includes SDK headers. With a known stock template/revision, a marker means true; absence in the complete block means false. Header absence or a truncated extract proves nothing. The generated C++ also reveals local versus context accesses, but reading bodies is unnecessary for the first audit and was not done.

The header records generation settings, **not proof that a particular executable incorporated that generation**. Conclusive installed-build attribution needs the matching producer's build record: header identity/configuration, SDK revision and patches, compile/link provenance, and the resulting executable digest tied to the installed file. The inspected writer/header do not provide an automatic complete chain of that kind. A header from a different build cannot close this gap.

## Existing provenance: what it establishes

- [Manifest][N-manifest] has a `Generated by ReXGlue v0.8.0` comment and `[project].sdk_version = "0.8.1"`. These labels and the Windows paths describe configuration history; neither identifies the executable's generator commit or effective booleans. The explicit SDK checkout pin is stronger source evidence but still not a binary identity.
- Local `v0.6.0` tag resolves to `0852183dd13e6efb108170d3a814c0aa00cd3879`. No generated files are tracked under `generated/` at HEAD or that tag. Named repository locations `generated/`, `generated.bak_080/` and `out/` were absent on this checkout. No generated contents were accessed.
- [.gitignore][N-ignore] excludes generated code/build outputs. Absence from Git cannot establish a producer's inputs. Git history searches for the eight keys in the tracked manifest/include/scripts/CMake returned no matching changes; this is limited to available local history and those paths.
- [build_out.txt][N-log] contains only a Windows version banner and repository prompt: no compile commands, codegen summary or flags.
- [Packaging][N-package] supports prebuilt directories and optional codegen; Vulkan packaging can consume an already built tree. A package version therefore does not prove regeneration or which optimization script ran.
- NHL diagnostics include the generated header and access `ctx.lr` in `src/diag_hooks.cpp` around lines 457 and 997. Under the inspected stock header, `skip_lr=true` would remove that member. **Inference only:** this argues against a straightforward unchanged current-source build with that flag. It cannot identify an installed binary produced from different sources or overrides, and is not promoted to a verified false value.

Search boundaries: tracked project source/configuration/build logs, local Git metadata, existence checks of the three named repository output directories, and public pinned SDK source cached under `/tmp`. No home-wide search, installation access, game asset access, PE inspection, PDB inspection or generated game artifact reading occurred.

## ABI and correctness gate

[include/rex/ppc/context.h][R-context] conditionally excludes localized/skipped members; the structure is not merely a fixed backing store with optional local copies. Native calls still pass `PPCContext&` and guest memory base. Different macro sets across application and SDK translation units can mean different member offsets or structure sizes despite using the same C++ type name. That is a potential ABI/ODR incompatibility, not a performance toggle to try blindly.

Pinned [xthread.cpp][R-thread], `SaveContext`/`LoadContext` around lines 1074–1290, directly reads/restores LR, CTR, GPRs, FPRs and vectors. The displayed accesses are not individually conditional on these eight flags. The inspected SDK CMake files do not establish propagation of a title's generated configuration into the prebuilt SDK. Thus even CTR localization requires proving a consistent runtime contract; rebuilding with macros alone could encounter missing-member errors. A future solution might preserve a fixed runtime ABI while localizing selected state or deliberately implement compatible save/restore bridges, but neither solution is established or implemented here.

Other required checks:

- **Hooks/imports/callbacks:** `BuilderContext::emit_function_call` invokes translated functions/imports with context/base. Native hooks can inspect context directly. A localized register may no longer exist or be represented there; normal ABI assumptions do not automatically cover proprietary helpers, hand-written hooks or reentrant callbacks. Audit reads/writes and live-ins across each boundary.
- **Nonvolatile state:** the same builder omits resolved functions whose names begin `__rest`/`__save` when nonvolatile localization is enabled. That assumes recognized helpers are correctly identified and their effects are covered by native local lifetime. NHL's EA CRT history makes helper correctness particularly relevant.
- **setjmp/longjmp:** NHL explicitly supplies addresses `0x830801C0`/`0x8307E1B0`. The builder saves `env = ctx`, calls `ppc_setjmp`, restores context on a nonzero return and sets r3. The stock template maps guest buffer addresses to thread-local native `jmp_buf`s. A context snapshot does not by itself capture state removed into local variables. Verify required register restoration and native nonlocal-jump behavior rather than assuming context assignment suffices. This is a risk, not a demonstrated NHL failure.
- **Exceptions:** `generate_exception_handlers` is separate from these eight. Its default is false; do not conflate native compiler exception flags, optional generated wrappers and NHL's configured CRT nonlocal return handling. Localization must remain compatible with all paths actually used.
- **MSR:** `build_mfmsr` emits a sequentially consistent fence and `REX_CHECK_GLOBAL_LOCK`; `build_mtmsrd` emits a fence, masked MSR update and enter/leave lock. `skip_msr` deletes these operations. It is particularly unsuitable as a first CPU experiment.

Expected performance mechanism, if compatible: locals may reduce repeated context loads/stores and expose state to host register allocation and dead-store elimination; nonvolatile localization can also remove save/restore traffic. Native register pressure/spills, code size and already effective compiler optimization can offset this. None of the sources establishes Ally gains or that the hot thread is doing computation rather than polling.

## Codegen versus host compiler optimization

[Optimized build script][N-opt] requests Release `-O3 -DNDEBUG -march=x86-64-v3 -flto=thin` with lld. [PGO-use script][N-pgo] adds a profile-use input; [PGO-generation script][N-pgogen] instruments a separate build. SDK scripts separately configure runtime optimization. These act on the emitted/native C++, whereas the eight flags select the emitted representation and context layout before compilation.

`-O3`, ThinLTO or PGO does not prove any generator boolean true. Conversely, a local-register header does not prove Release, successful profile matching or LTO. Script comments and available `.profdata` paths do not prove the installed executable was produced by those commands. Each dimension needs independent build provenance. No compiler flags, binaries or profiles were changed or inspected outside approved tracked source.

## Ranked, correctness-first experimental plan

All regeneration/build/runtime work below is **future work requiring authorization**, not performed in this audit.

| Stage / priority | Proposed action | Gate and measurable acceptance criteria |
| --- | --- | --- |
| 0 — smallest next step | Obtain matching generated config block and producer provenance, then bind the installed executable identity with a separately approved digest. | All eight recorded explicitly; producer SDK/template/source/patch identity and executable linkage documented. If matching provenance is unavailable, retain Unknown. |
| 1 — baseline | Collect synchronized application-layer MangoHud frame times and passive telemetry for matched rendered AI/player matches, using report 005/006 workflow. | Stable settings/scenes/warm-up, repeated runs, frame-time p50/p95/p99, simulation time versus wall time and thread CPU. No GPU-bound assumption; invalid utilization remains invalid. |
| 2 — mandatory source/test prerequisite | Audit fixed-versus-configured `PPCContext` layout across SDK DLL, executable, hooks and imports; design a consistent bridge if needed. | Static layout/offset agreement plus synthetic call/return, callback, context capture and setjmp/longjmp tests. No flag-only executable experiment before this passes. |
| 3 — first individual option | `ctr_as_local` only, if currently false and ABI gate passes. | PPC decrement/branch/indirect-call and cross-boundary tests, then unchanged gameplay correctness and simulation rate; compare native context traffic/text size and repeated frame-time results. Revert for any correctness change or no useful benefit. |
| 4 | `xer_as_local` alone against baseline, then a separately tested combination if justified. | Carry/overflow/summary-overflow and cross-call/nonlocal-return tests; same frame-time and simulation criteria. |
| 5 | `non_argument_as_local`, then `cr_as_local`, individually after their specific boundary audit. | Test every grouped register class, live-in conventions and CR preservation. Higher breadth means less confidence from merely booting. |
| 6 | `reserved_as_local`; `non_volatile_as_local` only after dedicated reservation/helper/nonlocal-return validation. | Atomic retry/contended handoff tests; EA save/restore and register restoration checks. Defer if ABI cannot be demonstrated. |
| 7 — last / may reject | `skip_lr`, then `skip_msr`, considered independently. | Resolve direct LR consumers and prove omitted state/locking unnecessary for NHL. Do not remove synchronization to chase a CPU percentage. Evidence may justify never enabling them. |

This ordering ranks limited scope and correctness above speculative speed. Even the first localization candidate is not currently established as a low-risk drop-in change. No percentage gains are predicted. Once codegen compatibility exists, confirm CPU work on the critical frame path before investing in broad flag combinations or fresh PGO.

## Minimal separately approved inspection and outstanding questions

The smallest useful read is the **complete Project Configuration macro block only** from the producer's matching `generated/default/nhllegacy_init.h`, ending before image constants. No generated function bodies, XEX or assets are necessary. Also request an existing non-asset build record linking that header/configuration and SDK revision to the produced executable's SHA-256. With separate authorization, hash **only the user-specified installed executable** to compare against that record; do not launch it. No such inspection was performed.

A matching record plus digest can conclusively attribute settings. An arbitrary local header or an executable digest by itself cannot. If the producer did not retain provenance, there may be no small inspection that conclusively recovers all eight booleans: targeted binary/debug-symbol analysis could support inferences, but optimized/stripped machine code does not guarantee recoverable configuration markers. Request producer evidence before proposing disassembly.

Outstanding: Where are the exact producer artifacts? Were custom templates/generator patches used? How were SDK/application context layouts kept compatible? Which native optimization/PGO commands actually produced v0.6.0? Does the hot thread's work affect measured frame and simulation timing? These remain unanswered.

## Files changed and validation

Only `reports/007-cpu-codegen-optimization-audit.md` and `reports/README.md` changed. Validation: verified branch/origin/initial cleanliness; checked config defaults/parser/include precedence/header markers against pinned source; checked tracked script and diagnostic references; inspected local tag/history and approved log; validated report/index local links and immutable public source URLs; reviewed diff and staged path list before commit. Source research fetched two public pinned SDK files after sandbox network access failed. No application tests were needed for documentation-only changes; no game build, code generation, game execution or real performance tests were performed. See commit history for the resulting documentation commit.

## Immutable source references

[N-setup]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/scripts/setup_sdk.ps1

[N-patch]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/sdk/rexglue-codegen-bcctr-tail-fix.patch

[N-manifest]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/nhllegacy_manifest.toml

[N-functions]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/nhllegacy_functions.toml

[N-main]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/src/main.cpp

[N-ignore]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/.gitignore

[N-log]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/build_out.txt

[N-package]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/release/package.ps1

[N-opt]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/scripts/_build_vk_opt.bat

[N-pgo]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/scripts/_build_vk_pgo.bat

[N-pgogen]: https://github.com/Grognlor/nhl-legacy-recomp/blob/86363221563ca7811c041d96bd41ead38861497b/scripts/_build_vk_pgogen.bat

[R-config-h]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/codegen/config.h

[R-config]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/config.cpp

[R-builder]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/context.cpp

[R-flow]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/control_flow.cpp

[R-system]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/system.cpp

[R-writer]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/codegen_writer.cpp

[R-init]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/resources/templates/codegen/init_h.inja

[R-memory]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/builders/memory.cpp

[R-manifest]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/manifest.cpp

[R-project]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/project_recompiler.cpp

[R-cli]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/rexglue/commands/codegen_command.cpp

[R-cvars]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/codegen_flags.cpp

[R-context]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/include/rex/ppc/context.h

[R-thread]: https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/system/xthread.cpp

[U-config]: https://github.com/hedge-dev/UnleashedRecomp/blob/cf829a9eca8fb680fba4b0409ddeb6ca92f22e3c/UnleashedRecompLib/config/SWA.toml
