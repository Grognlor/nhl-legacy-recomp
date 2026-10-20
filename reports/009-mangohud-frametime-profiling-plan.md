# 009 — Temporary MangoHud frame-time profiling plan

## Objective and outcome

Prepare a Desktop Mode application-layer frame-time workflow for the ASUS ROG Ally Z2A, Bazzite 44, NHL Legacy Recomp v0.6.0 through Proton Experimental. Starting HEAD `b7da4a3e054d72c61a5437ae60652208c9567200`; verified branch `perf/ally-investigation`, origin `https://github.com/Grognlor/nhl-legacy-recomp.git`, and initial clean working tree. Reviewed reports 003–008, their relevant profiling/provenance findings, and the profiler runbook.

**Installed capability verified; actual game injection and launch route unverified.** MangoHud 0.8.4 is present with both Vulkan layer architectures and documented CSV logging. A bounded, temporary workflow is documented, but no launch command is provided because the actual launcher/client lifecycle and environment propagation remain unresolved. No game or Steam client was launched/terminated, no capture started, and no configuration file was created or applied.

The two historical approximately 120-second captures were both rendered hockey matches, AI-versus-AI and player-controlled. Approximately 335% process CPU includes the approximately 95%-of-one-core thread; these overlap. Invalid GPU utilization and absent synchronized frame times still prevent a bottleneck verdict. This task adds no real-game measurements.

## Read-only environment verification

| Check | Observed evidence / limit |
| --- | --- |
| Session variables | `XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=KDE`, `WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`; consistent with Desktop Mode, not proof of display refresh/cap |
| Available commands | `/usr/bin/mangohud`, `/usr/bin/mangoapp`, `/usr/bin/gamescope`, `/usr/bin/steam`, `/usr/bin/flatpak` |
| MangoHud version | `/usr/bin/mangohud --version` prints `v0.8.4`; inspected wrapper exits directly for that argument, launching no application |
| Actual RPM ownership | `rpm -qf /usr/bin/mangohud` identifies `terra-mangohud-0.8.4-2.fc44.x86_64` and `.i686`. Initial generic `rpm -q mangohud` query failed because the installed package has the Terra name, not because MangoHud is absent. |
| Gamescope / Steam package | `terra-gamescope-3.16.28^3-1.fc44.x86_64`; `steam-1.0.0.87-2.fc44.x86_64`. Native Steam availability does not establish the user's actual launcher or selected Proton revision. |
| Vulkan manifests | `/usr/share/vulkan/implicit_layer.d/MangoHud.x86_64.json` and `MangoHud.x86.json`, overlay layer names with corresponding architectures, enable `MANGOHUD=1`, disable `DISABLE_MANGOHUD=1` |
| Layer library existence | `/usr/lib64/mangohud/libMangoHud.so` and `/usr/lib/mangohud/libMangoHud.so` exist. Existence is not a runtime loader/container test. No binary contents inspected. |
| Installed docs | `/usr/share/doc/mangohud/MangoHud.conf.example` and `/usr/share/doc/terra-mangohud/README.md` document logging toggle, duration, zero interval, output directory and upload prohibition. |
| Relevant invoking-shell environment | No output for queried `MANGOHUD`, `MANGOHUD_CONFIG`, `MANGOHUD_CONFIGFILE`, `VK_INSTANCE_LAYERS`, `VK_LAYER_PATH`, `VK_ADD_LAYER_PATH`, `STEAM_COMPAT_DATA_PATH`, `SteamAppId`; this says nothing about another process's environment. |
| Process-name snapshot | `ps -eo pid,comm` filtered for Steam/NHL/Gamescope/MangoHud had no matches during inspection. Momentary visibility is not authority to start/restart a client or proof no relevant runtime exists elsewhere. No process environments/command lines were read. |

No `vulkaninfo`, graphics test, game, nested compositor, invasive profiler or package installation was run. No Steam shortcut, installation, compatibility database, Proton prefix or copyrighted asset was opened. The system Steam wrapper was read as public launcher source; no user Steam state was accessed.

## Capture capability and source references

The installed docs support `log_interval=0`, `log_duration`, `output_folder`, `toggle_logging=Shift_L+F2`, and `permit_upload=0`. Upstream **v0.8.4**, matching the installed version label, was checked directly:

- [Logger implementation](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/logging.cpp), `writeFileHeaders`, `writeToFile`, `start_logging`, `try_log`: CSV includes `frametime` and `elapsed`; elapsed is emitted in nanoseconds relative to the logging start. It creates application-named timestamped files and a separate summary. Its append behavior differs from the profiler's exclusive file creation; unique directories and no rapid repeated toggle are required.
- [Overlay implementation](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/overlay.cpp), `update_hud_info_with_frametime`: frame-update logging path when interval is zero. `frametime` is in milliseconds. These are application presentation intervals, not scanout or simulation ticks.
- [Versioned configuration example](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/data/MangoHud.conf) and installed examples: logging controls. Distribution patches/runtime interactions remain subject to the pilot.

The current Vulkan rendering path described in reports 001/002/006 makes application-layer interception through Proton plausible. No D3D wrapper invocation is needed merely because the executable is Windows. However, Wine/Proton loader visibility, pressure-vessel environment propagation, active layer order and hotkey delivery have not been exercised. **Can capture in principle; actual NHL capture is unverified.** Do not equate installed manifests, visible overlay or a high menu FPS with validated application-frame logs.

## Nonpersistent launch-route decision and blocker

The intended candidate is a fresh native Steam client with a process-scoped environment, then the user's unchanged existing NHL shortcut. Steam would retain responsibility for Proton selection, prefix and normal runtime setup. This requires confirmation that native Steam is the actual launcher, approval for the client lifecycle and game launch/normal writes, and a successful environment/logging pilot. It affects descendants of that temporary client rather than NHL alone. No claim is made that the candidate already works.

Do not call Proton directly, guess compatibility-data IDs, create a prefix, use an alternate wrapper that bypasses Steam, modify shortcut/launch options, or use a global/session environment. `MANGOHUD=1` in a terminal cannot alter an existing game. An already-running Steam client may simply accept an IPC launch request without inheriting the requester's environment. The installed `mangohud` wrapper also adds an OpenGL shim to `LD_PRELOAD`; wrapping all of Steam would unnecessarily broaden this Vulkan experiment.

**Approval question before any launch work:** How is NHL currently launched (native Steam shortcut, Flatpak Steam, or another launcher), and does the user approve a temporary fresh client session using that existing route, including normal game writes? If a client is already running, its exit/restart must be explicitly agreed; do not terminate it automatically. No launch command is supplied until the route is concrete. Task 009 authorizes planning, not a gameplay capture or client/session changes.

## Repeatable pilot and full capture procedure

The complete copy-paste preparation/collection/analysis commands and stopping instructions are in the [Task 009 runbook section](../tools/ally-profiler/README.md#task-009-gated-desktop-frame-time-pilot). They reuse existing commands and safeguards; no launcher or new parser/helper was added. Preparation is gated on launch-route agreement and produces only a unique external config under the canonical `~/nhl-ally-profiles/` root. It was reviewed but not executed in this task. Config/telemetry files never belong in the playable installation.

Pilot: a 20-second application CSV with a 40-second passive telemetry window, after five minutes of warm-up. Use manual Left Shift+F2, no automatic logging/startup. Check raw application-named CSV, not `_summary.csv`; confirm one header, finite positive millisecond intervals, nanosecond elapsed progression, plausible row count/duration and no concatenation or gaps. Compare sum of intervals, elapsed span and stopwatch interval, allowing documented edge/focus uncertainty; there is no invented universal tolerance. Existing importer checks row shape/frame values, **not elapsed monotonicity or actual sampling cadence**. Do not assert `--per-frame` until independent cadence/unit checks pass; stop if they cannot be established.

Full measurements: new 120-second configs and 150-second telemetry windows, three repetitions per workload in interleaved AI/player order. Preserve 720p, 1×, VSync off, FSR on, shadows off, nominal 25 W, existing display/refresh/scaling, caps and Steam/Proton configuration. Record arena, teams, camera, period rules, score/phase, stoppages/replays, control differences, AC/battery state/charge, actual display/VRR/caps and warm-up conditions. Record telemetry and raw CSV paths together. Uninterrupted gameplay portions must be explicitly identified; exclude or separately segment setup/menu/replay rows, never silently trim them to improve results.

Report p50/p95/p99 frame times in ms; linear interpolation at `(N-1)*p/100`. Mean presentation FPS for a validated complete stream is `1000*N/sum(frame_ms)`; never mean instantaneous FPS. Stutter descriptors: counts and fractions of frames strictly over 16.67/33.33/50/100 ms, not causal diagnoses or time fractions. Small pilots make tails weak; use them to validate capture, not rank optimizations. Separately record normalized game-clock progression versus stopwatch time during continuous play, respecting period scaling/stoppages. Presentation FPS does not measure simulation speed.

## Clock correlation and uncertainty

MangoHud's elapsed origin resets at its logging toggle. Telemetry `collect()` uses Python host monotonic time for scheduling/deltas and records `monotonic_ns`, UTC and collection duration on each sample. CPU figures describe intersample deltas; sensor reads are sequential rather than atomic. A 0.5-second interval cannot resolve each frame's CPU use.

Use two numeric host-monotonic/UTC markers bracketing the manual start toggle; the runbook gives a read-only marker command. With start bracket `[A,B]` and MangoHud relative E, approximate frame timing is bracketed by `[A+E,B+E]`, with additional producer timestamp semantics. Focus switching/reaction delay widens the bracket and must be retained as uncertainty. This is **coarse alignment**, not precise clock synchronization. File timestamps are local wall-clock seconds and insufficient; UTC adjustment is another reason not to derive offsets from filenames. Do not interpolate sensor samples into invented frame-level activity. Broad coincident windows may guide hypotheses but cannot identify a particular GPU wait or CPU spin.

Old captures cannot be paired with future frame streams. GPU utilization near 10000 remains invalid, including MangoHud values if sourced through the same driver; no scaling/clamping. slowPPT is not GPU-only power. CPU process/thread totals overlap. Even synchronized presentation/telemetry data cannot alone distinguish useful CPU work, polling, shader compilation, rendering and synchronization costs conclusively.

## Stop, restore and limitations

The duration timer or logging toggle ends CSV recording; Ctrl-C stops only the collector and preserves partial output. Gameplay can continue, but stopping logging does not unload MangoHud or restore uninstrumented overhead. Full restoration requires the later approved normal game exit and end of the temporary client session, then an ordinary launch without capture variables. Use process-scoped environment only: no exports, shortcut edits, shell startup edits or prefix settings. External configs remain inert without explicit selection. No lifecycle action was performed here.

Desktop application-layer logging and Gaming Mode Gamescope/mangoapp logging remain separate producers. Do not inject another overlay into Gaming Mode, launch nested Gamescope, or treat compositor cadence as interchangeable with NHL application frames. That workflow requires separate validation.

Outstanding: actual launch entry point and client ownership; selected Proton Experimental build; runtime layer/config propagation; actual CSV cadence/units/content; hotkey behavior; display/cap state; synchronization bracket width; observer overhead. No real capture or output correctness is claimed yet.

## Files changed, validation and next action

Changed only this report, `reports/README.md`, and `tools/ally-profiler/README.md`. Automation was deliberately limited to documented invocations of existing safe functions: no new logic was needed while launch propagation is unresolved, so no new synthetic parser tests were added. Existing complete synthetic suite **22/22 passed**, using temporary fake sensors/process data. No home capture was generated. Confirmed installed option names, manifests, package ownership/version, wrapper behavior and profiler CLI/source; checked local documentation links, command-snippet syntax and Git whitespace/staged allowlist. No application/SDK/renderer/profiler source changed.

**Exact next user action:** state the current NHL launch method and whether a temporary fresh client session and subsequent 20-second pilot are approved. Resolve that route before creating/applying the configuration or launching anything. Publish documentation only and wait for further instructions.
