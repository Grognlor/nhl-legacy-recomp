# 008 — Generated configuration and build provenance inspection

## Objective and outcome

Perform the explicitly authorized, read-only search for an existing generated CPU configuration header and non-asset build metadata. Repository: `Grognlor/nhl-legacy-recomp`; branch: `perf/ally-investigation`; starting HEAD: `0db4690f05bf232e1226d7804db9400936b64f2a`. Verified origin URL and a clean working tree before investigation. Read [report 006](006-sonic-unleashed-architecture-comparison.md), [report 007](007-cpu-codegen-optimization-audit.md), their source references and the [index](README.md).

**No generated configuration header was found in the locations checked.** Expected generated/build/vendor directories are absent. The available tracked metadata describes intended build inputs, not an executed build. All eight observed header values and all eight installed-executable values remain **Unknown**. Manifest omissions are not substituted for observations.

No generated code was produced. No executable, DLL, PDB, game asset, memory dump, playable installation or Proton prefix was opened or hashed. No game was launched or built. Only this report and the index were changed.

## Exact search boundaries and method

The authorized root `/home/cody/Projects/nhl-legacy-recomp` resolves to `/var/home/cody/Projects/nhl-legacy-recomp`. These are aliases for this checkout, not two independently searched trees. The normal home-directory alias was resolved solely to establish the trusted root. Descendant symlinks were not followed.

The search used tracked build scripts/presets to identify local output paths, component-by-component `lstat` existence checks, and a filename-only traversal of the explicit project source directories below. Nothing was executed from those scripts. No historical Windows path was treated as a locally accessible location.

| Checked location, relative to repository root | Result / scope |
| --- | --- |
| `generated/default/nhllegacy_init.h`, `generated/` | Absent; first missing component is `generated`. No header block available to inspect. |
| `generated.bak_080/` | Absent. Backup location named by `.gitignore`. |
| `out/`, hence `out/build/`, `out/install/`, `out/release/` | Absent at `out`; no child traversal. `out/release` is recorded only as absent, not searched for payloads. |
| `out/build/<presetName>/` | Not reachable because `out` is absent. Preset-derived path, not a discovered build tree. |
| `out/build/win-amd64-vk-ffx`, `out/build/win-amd64-vk-opt`, `out/build/win-amd64-vk-pgogen`, `out/build/win-amd64-vk-pgo` | All covered by missing `out`; script-derived paths, not present artifacts. |
| `third_party/`, `third_party/rexglue-sdk/` | Absent at `third_party`. |
| `third_party/rexglue-sdk/out/build/win-amd64-ffx`, `third_party/rexglue-sdk/out/install/win-amd64-ffx`, `third_party/rexglue-sdk/out/ffx-prebuilt/vk` | Not reachable because `third_party` is absent; paths established by `scripts/_env.bat`. No binary/prebuilt contents inspected. |
| `build/`, `pgo/` | Absent; existence checks only. No profile contents inspected. |
| Repository root | Filename inventory; no root `.h`, `.hpp` or `.inja` files. `CMakeUserPresets.json`, `CMakeCache.txt`, `compile_commands.json`, `build.ninja`, `CMakeConfigureLog.yaml` absent. Read only approved source/build metadata. |
| `docs/`, `gpu/`, `release/`, `renderer/`, `reports/`, `scripts/`, `sdk/`, `src/`, `tools/` | Filename-only traversal: 44 directories visited in total. No candidate generated configuration header or build record matched the patterns below; no symlinks encountered in that traversal. |

Filename candidates were `*_init.h`; names containing `config` ending in `.h`/`.hpp`; `CMakeCache.txt`, `compile_commands.json`, `build.ninja`, `CMakeConfigureLog.yaml`, `CMakeOutput.log`, `CMakeError.log`, `CMakeUserPresets.json`; and names containing `provenance`. Root metadata names were inventoried separately. This is a bounded search, not proof that no differently named private artifact exists anywhere.

Traversal excluded sensitive/tool-private roots `.git`, `.aws`, `.codex`, `.agents` and directory names `assets`, `game`, `games`, `payload`, `stage`, `steamapps`, `compatdata`, `prefix`, `pfx`, `shader_cache`, `screenshots`, `captures`, `target`, `node_modules`, `__pycache__`. Git was queried for repository identity/status and tracked output paths without searching object contents. No generated files are tracked under `generated`, `generated.bak_080`, `out` or `third_party`.

The root filename inventory also exposed `guest_stacks.txt`; its contents were **not read**, because memory/stack inspection is outside authorization. No excluded file contents were used as evidence. No scan of the rest of `/home/cody`, Steam directories, external drives, archives or installed packages occurred. No actual external project build-directory path was established by available local metadata. Historical Windows repository, SDK and game-root strings were not followed or translated into guessed Linux mount paths.

## Flag observations

The stock template interpretation below is inherited from the pinned-source verification in report 007; it is not an observation of a generated header here. In a complete block produced by that verified template, a marker present means true and absent means false. A missing header supplies neither result.

| Option | Marker | Observed generated-header value | Proven installed-executable value |
| --- | --- | --- | --- |
| `ctr_as_local` | `REX_CONFIG_CTR_AS_LOCAL` | Unknown | Unknown |
| `xer_as_local` | `REX_CONFIG_XER_AS_LOCAL` | Unknown | Unknown |
| `reserved_as_local` | `REX_CONFIG_RESERVED_AS_LOCAL` | Unknown | Unknown |
| `cr_as_local` | `REX_CONFIG_CR_AS_LOCAL` | Unknown | Unknown |
| `non_argument_as_local` | `REX_CONFIG_NON_ARGUMENT_AS_LOCAL` | Unknown | Unknown |
| `non_volatile_as_local` | `REX_CONFIG_NON_VOLATILE_AS_LOCAL` | Unknown | Unknown |
| `skip_lr` | `REX_CONFIG_SKIP_LR` | Unknown | Unknown |
| `skip_msr` | `REX_CONFIG_SKIP_MSR` | Unknown | Unknown |

The public pinned SDK [writer](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/src/codegen/codegen_writer.cpp) serializes these settings and renders `{project}_init.h`; its [stock template](https://github.com/rexglue/rexglue-sdk/blob/bd9b51918faa71f962fa38af6d5f744af9aba2ce/resources/templates/codegen/init_h.inja) conditionally emits their macros before SDK includes. These exact source references were validated in report 007; no new remote source retrieval was needed. [src/main.cpp](../src/main.cpp) corroborates the expected `generated/default/nhllegacy_init.h` path. No equivalent header was found to compare against this template.

## Available provenance and its limits

| Evidence read | What it identifies | What it does not establish |
| --- | --- | --- |
| [scripts/setup_sdk.ps1](../scripts/setup_sdk.ps1), parameter and patch list | Intended SDK pin `bd9b51918faa71f962fa38af6d5f744af9aba2ce`; title patch and conditional-bcctr scanner patch; overridable SDK directory/pin | Actual producer checkout, applied patches, template contents or generator executable identity |
| [scripts/_env.bat](../scripts/_env.bat), lines 16–20 | Repository-relative SDK source/build/install/prebuilt defaults; source location can be externally overridden | An actual override value used by a producer; no external path was resolved from an existing build record |
| [CMakePresets.json](../CMakePresets.json), Windows/Linux base presets | Intended `${sourceDir}/out/build/${presetName}`, compiler names and build variants | Installed compiler versions or an executed configure/build |
| [scripts/_build_vk_opt.bat](../scripts/_build_vk_opt.bat), configure command | Requested Release, `-O3 -DNDEBUG -march=x86-64-v3 -flto=thin`, lld | That these commands produced any particular executable |
| [scripts/_build_vk_pgo.bat](../scripts/_build_vk_pgo.bat) and [PGO-generation script](../scripts/_build_vk_pgogen.bat) | Separate intended instrument/use build paths and profile input | Profile existence, freshness, matching, successful use or effective codegen flags |
| [release/package.ps1](../release/package.ps1), parameters and codegen/build branches | Optional regeneration, build-directory override and prebuilt Vulkan packaging | A release-to-header identity chain; packaging intent is not an execution record |
| [build_out.txt](../build_out.txt), complete file | Windows version banner and repository prompt | Any compilation, configuration summary, source commit, header identity or successful build |
| Local HEAD / [report 007](007-cpu-codegen-optimization-audit.md) | Current source baseline; prior verified template/default behavior | Source revision of the producer of the user's installed v0.6.0 executable |

No approved existing build cache, compile database, Ninja record, configuration log, generated-header digest, template override record or header-to-executable build attestation was found. Source comments/version labels and script defaults remain source evidence only. In particular, native compiler options do not determine the eight generation booleans, and neither source HEAD nor a release name binds a missing header to the installed executable.

## Smallest next step and outstanding questions

Request from the build producer **only the complete `Project Configuration` macro block** from the exact generated `nhllegacy_init.h` used for the released build, ending before image constants/SDK includes. Include a non-asset provenance record specifying source commit, generator/SDK revision and patches, stock/custom template identity, and which produced release/build used that header. No generated function bodies or assets are necessary.

If these artifacts exist in another directory, the smallest additional authorization is that directory's exact path and permission to inspect only the header block and named non-asset build metadata there. Do not expand to a home-wide search. A supplied block establishes settings for that header only; a trustworthy matching producer record is required to attribute them to a release. Proving identity of the installed copy would remain a separate step requiring separate authorization; no executable inspection or hashing is authorized by Task 008 or proposed as part of this completed search.

Until then, retain all eight Unknown values and the report 007 context-ABI correctness gate. There is no basis here to enable options, regenerate code, rebuild, assert a CPU-codegen bottleneck or claim any performance improvement. Synchronized frame-time profiling remains a separate future task.

## Files changed and validation

Changed only `reports/008-generated-config-provenance-inspection.md` and `reports/README.md`. Validation performed: repository/origin/branch/initial-cleanliness checks; bounded directory-existence and filename checks with no descendant symlink following; script/preset path cross-checks; local Markdown-link and eight-row table checks; `git diff --check`; staged-file allowlist verification before commit. Documentation-only work requires no application or synthetic profiler tests, and none were run. No source, SDK, generated code, binaries, assets, installation or configuration was modified. Commit/push applies only to `origin/perf/ally-investigation`; master and upstream are untouched.

Stop after publishing this report and await further instructions.
