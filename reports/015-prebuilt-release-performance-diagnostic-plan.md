# 015 — Practical diagnostics for the prebuilt release

## Executive summary

**Recommend one scene-tagged, 120-second passive telemetry capture using the existing `ally_profiler.py`, without MangoHud, a cap, a rebuild or a restart.** Compare naturally occurring wide-angle hockey with bench/player close-ups; include an introduction only if one naturally occurs. Prioritize multiple close-ups rather than reproducing historical slideshow episodes. Timestamp scene boundaries and visible freezes on the same host clock as telemetry. A few explicitly selected process/thread wait-state snapshots can supplement the capture.

This is a deliberately narrower answer than Report 013's internal lineage diagnostic. It can identify whether severe close-ups coincide with a specific CPU thread remaining busy, peers becoming inactive, sampled sleeping states, or changes in valid GPU clocks/temperature/labelled power. It cannot identify unique game images, GPU completion, simulation steps or physical display delivery. A negative result is useful: stop repeating aggregate telemetry and request targeted producer diagnostics rather than pretending external FPS resolves frame freshness.

No gameplay test is executed. No runtime/source changes, installs, dependency downloads, executable inspections or playable-installation access occur. Report 014's build prerequisites remain unmet and **its proposed build-first next step is superseded for this task**.

## Scope and evidence

Starting repository state: clean `perf/ally-investigation`, HEAD `2d209c58c733572ffd209eaaf6b552420d1cd187`; origin `https://github.com/Grognlor/nhl-legacy-recomp.git`. Reviewed reports [011](011-correlated-frametime-telemetry.md), [012](012-simulation-timing-and-synchronization.md), [013](013-frame-freeze-and-catchup-investigation.md), [014](014-diagnostic-build-feasibility-and-implementation-plan.md), earlier profiling/codegen constraints, index, collector/runbook and title renderer/SDK patch references. No branch changes or upstream writes.

Labels used below: **source** means tracked/pinned implementation, not proof the downloaded executable includes that code; **measured** means historical recordings or current tool/permission inventory; **reported** means user observations; **hypothesis** means causal attribution still unverified. The SDK source references remain at `bd9b51918faa71f962fa38af6d5f744af9aba2ce`; Report 013 provides immutable links and detailed lifecycle ranges.

Reported current symptoms: wide-angle players briefly freeze then jump forward; bench and individual-player shots are consistently much worse, resembling stop-motion. Introduction pacing is ambiguous. Thirty displayed clock seconds took approximately 4.62 and 5 wall seconds; scaling and human uncertainty prevent a simulation-rate conclusion. Inherited uncapped/VSync-off/FSR Ultra Performance/~720p/1×/shadows-off/~25 W settings are context, not freshly verified. Do not change them. The previous MangoHud 60 FPS regression is source-plausible queue-lock interaction, not proven causality and not an explanation established for today's no-overlay freezes. Do not reintroduce it.

## Existing prebuilt-release observability

| Facility and source reference | Observable without rebuilding | Important boundary |
| --- | --- | --- |
| Existing collector: [ally_profiler.py](../tools/ally-profiler/ally_profiler.py), `ProcSampler.sample`, lines 126–181; `collect`, 267–300 | Per-process and per-thread CPU deltas, identity/start ticks, names, instantaneous state, cumulative voluntary/involuntary context switches; UTC, monotonic timestamps and collection duration | No stacks, guest entry-point attribution, scheduler latency, wait channel or simulation counter. Process and thread CPU overlap; 100% is one logical core. State snapshots miss brief waits; a spinning thread also consumes CPU. |
| Same collector: `gpu_sample` and discovery; [runbook](../tools/ally-profiler/README.md) | Available AMD labelled clocks, temperature and distinct power channels, with errors/nulls preserved | Invalid `gpu_busy_percent` source remains excluded entirely, including occasional in-range values. `slowPPT` is not GPU-only power; clocks/power do not establish saturation. Active DPM state is not instantaneous frequency. No CPU-frequency collection. |
| Title [nhl_vk_backend.cpp](../renderer/core/nhl_vk_backend.cpp), `NhlVkCommandProcessor::IssueSwap`, 230–277 | Source emits approximately once-per-second `[nhl-vk-fps]`, average draw count and `frames_total` after SDK swap; publishes perf-HUD snapshot | Counts command-processor swaps, not unique images, simulation updates or display refreshes. One late message may span a stall; no per-stage latency. Installed inclusion, logging sink/location and verbosity are unverified. No installation log search performed. |
| Same file, `NHL_VK_DRAWLOG`; [SDK patch](../sdk/rexglue-vulkan-nhl-legacy-bd9b519.patch), `NHL_VK_RB_STATS`, around 385–425 | Optional draw/inventory logs and periodic resolve/readback destination/size statistics exist in source | Do not enable: no verified installed runtime route; flags may require a restart, inventory logging adds work, and destination details are unnecessary. Readback stats are not timed completion probes. Environment changes in another shell cannot retrofit a process. |
| SDK optional performance counters; Report 014 | Some compile-time counters/profiling facilities exist | Release scripts disable generic profiling; runtime variables cannot recreate compiled-out code. No verified release control exposes the full lineage trace. |
| Existing MangoHud recordings/analyzers | Historical application-present interval distributions and validated per-frame cadence | Not new current-session data. High FPS does not identify new images, animation progress, simulation/input health or physical scanout. No fresh layer injection into an already running Vulkan process. |

Existing non-asset logs could be valuable **if the user supplies an explicitly selected existing log outside the playable installation**, ideally a small sanitized excerpt containing `[nhl-vk-fps]` and timestamps. That is a later optional evidence request, not an instruction to scan installations, enable logging, upload arbitrary logs or restart NHL. Absence of messages is not proof of no swaps or pipeline activity.

## Verified local tools and permission limits

Read-only PATH checks and self-process/kernel-node reads were performed; no game PID was sampled for this task. Inventory date: 2026-10-20.

| Tool/capability | Verified result | Use/permission limit |
| --- | --- | --- |
| Python | `python3`, version 3.14.7 | Existing standard-library collector/tests; no install needed. |
| procps | `ps`, `top`, `pgrep`; `ps` version procps-ng 4.0.6 | PID/name selection and read-only thread snapshots; `top` is redundant with collector CPU deltas. Target-process accessibility still must be checked at test time. |
| Scheduler statistics | `/proc/sys/kernel/sched_schedstats` = **0**; self `schedstat` readable and contained nonzero numbers | Disabled collection makes run-queue-delay deltas unsuitable as a reliable starvation measure. Existing nonzero values do not establish live accounting. Do not enable the sysctl. |
| Wait channels | Self `/proc/self/wchan` readable, returned **0** | Demonstrates node access only. A target's symbol/visibility is unverified. `0`, `-`, denial or unavailable is Unknown, not “no wait.” `ps ... wchan` is a proposed opportunistic snapshot. |
| CPU frequency | `policy0/scaling_cur_freq` node exists and is readable by mode | Not sampled here; policy scope/driver semantics and other policies not verified. Frequency alone cannot prove thread throttling; collector currently omits it. |
| AMD busy node | `card1/device/gpu_busy_percent` exists/readable by mode | Previously invalid values; existence does not repair semantics. No fresh values collected. |
| MangoHud/mangoapp/Gamescope/vulkaninfo | Commands present; Report 009 verified installed MangoHud 0.8.4 and Vulkan layers | No Vulkan probe or compositor process inspection executed. Binary availability does not prove an active overlay, usable timing extension, per-game compositor trace or recording support. |
| gdb / turbostat | Commands present | Debugger attach can stop/perturb threads; turbostat privileged access/AMD coverage not established. Neither is selected. |
| perf / pidstat / strace / bpftrace / trace-cmd / amdgpu_top / radeontop | Not found on current PATH | Not available through this verified shell; no claim they are absent everywhere. No install or workaround attempted. |
| Kernel tracing policy | `perf_event_paranoid=2`, `ptrace_scope=0` | Does not prove perf events, GPU tracepoints, debugfs, tracefs, BPF or another process's stacks are usable. No tracing/attach performed; privileged tracing requires separate approval. |

Do not run `vulkaninfo` as an assumed per-game profiler: it probes another application/device and does not timestamp NHL submissions. No verified existing compositor facility currently supplies physical-display timing or NHL image freshness. Desktop Wayland and Steam Gaming Mode are different paths; do not change sessions to acquire a new metric in this test.

## Comparison of practical methods

A=guest/command progress; B=CPU scheduling/synchronization; C=GPU completion/load; D=host pacing; E=old output; F=scene resource/pipeline operations. “Indirect” means correlation only.

| Method | What it measures / diagnostic reach | Cannot establish | Restart, privilege, perturbation and installation risk |
| --- | --- | --- | --- |
| Existing telemetry + scene markers **(primary)** | CPU work/state/switch deltas and valid sensors; A/B/C/F indirect through scene correlation | No queue depth, GPU completion, simulation steps, D/E or exact F event identity | No restart/root/install; read-only sampling and private output. Small but unmeasured overhead; stop if behavior changes. |
| Selected `ps -L` wait snapshots | B: sampled thread state, kernel wait-channel name if exposed | Wait duration, Windows lock owner, running versus runnable time, useful work versus spin; futex is not a subsystem label | No restart/elevation expected for own PID; denial remains Unknown. Brief process traversal/output; no attach. |
| `/proc/.../schedstat` deltas | With enabled accounting could measure runnable delay versus on-CPU time | Currently disabled; not usable proof here. Even enabled, off-CPU time needs further classification | No restart for reads, but enabling accounting changes system state and is outside this plan. |
| Already-existing title log | A/F coarse swap/draw/readback evidence if actually emitted and timestamped | Unique images, GPU completion, simulation progress, lock timing | Reading a supplied non-asset excerpt needs no restart/root. Enabling new flags/logging is not authorized; avoid installation scans. |
| MangoHud application CSV | D: application present intervals | E, simulation progress, exact GPU execution or compositor delivery | New injection normally needs approved relaunch/environment setup; runtime behavior changes. Prior limiter catastrophe rules out caps, not all timing collection, but lower-impact primary test comes first. |
| Existing Gamescope/mangoapp timing | Potential compositor/client cadence if already available and its measurement point verified | E or physical timing from an arbitrary FPS number; no equivalent Desktop application log assumed | Availability of usable current logging unverified. No new compositor/overlay/session configuration proposed. |
| perf scheduling / off-CPU trace | Could refine B and CPU stacks, subject to permissions/symbols | A guest function mapping without symbols; GPU completion or E by itself | Tool absent; kernel tracing/privileges unverified. Installation or elevated tracing needs separate approval. Not first step. |
| GPU profiler/API capture/debugger | Potential C/F or API spans; some tools alter execution substantially | Rendered image freshness/simulation from API timing alone; present return is not scanout | Not verified available; attach/injection/capture may stall, require restart and expose proprietary data. Not recommended. |

CPU computation versus waiting can be narrowed, not solved: high CPU means execution (including polling), low CPU plus repeated S/D samples suggests off-CPU waiting, while runnable-state samples with low CPU are only suggestive of starvation. Context-switch counts measure transitions, not delay or cause. CPU saturation and GPU limitation can coexist. Reliable utilization/completion evidence is missing, so no CPU-versus-GPU verdict follows from this table.

## Bench/close-up comparison and existing evidence

Use scene classes **A introduction**, **B wide-angle active play**, **C bench/player close-up**. C is primary. Mark the transition and visible freeze separately; a camera transition may itself create a short-lived resource/synchronization burst. Capture every C segment in the time limit, not only smooth ones. Distinguish bench, player close-up and replay in notes rather than silently merging them. Do not deliberately change camera settings to manufacture scenes.

Source-supported candidates from Report 013 include guest/CP waits and command-ring backpressure; Vulkan queue/fence/acquire waits; retained synchronous resolves/readbacks for equipment/player texture compositing; upload/pipeline work; and mailbox reuse/overwrite or UI repaint scheduling. Relevant pinned functions are `CommandProcessor::WorkerThreadMain/ExecutePacketType3_WAIT_REG_MEM`, `VulkanCommandProcessor::IssueSwap/EndSubmission/CheckSubmissionFenceAndDeviceLoss/IssueCopy`, and `Presenter::RefreshGuestOutput/ConsumeGuestOutput`, `VulkanPresenter::PaintAndPresentImpl` (Report 013 lifecycle and mechanism tables give file/range links). These are mechanisms, **not identified close-up call sites**. Do not assume more polygons or shader compilation in C.

Most informative passive comparison:

- Does C maintain/increase CPU work on the same hot thread while CP/other workers lose activity? Consistent with a serial producer, polling or dependency; cannot distinguish them without stacks/internal progress.
- Do multiple workers instead increase CPU work, or do repeatedly sleeping threads show an accessible wait channel? Supports a different workload/wait pattern; does not identify the waited object or prove GPU blocking.
- Do clocks/power/temperature change with C consistently across multiple segments? Context for shared-power/workload hypotheses, not utilization or causality. Retain per-label units and invalid/missing channels.
- Is severe visible freezing present with little change in these metrics? Strengthens the need for freshness/presentation or internal synchronization measurements; does not establish either as the cause.

Historical measured evidence is unchanged: ~74.34 present FPS, p95 26.03 ms, p99 35.75 ms, 126 >33.33 ms, nine >50 ms, none >100 ms. Report 013 already showed **85/126 long intervals followed by <5 ms**, so no duplicate reanalysis is needed. The recording had no scene labels, no image identity, conditional ~one-second alignment, a ~95%-of-one-core hot guest thread and less worker activity in poorer intervals. Four named pipeline workers had zero sampled CPU ticks in that warm capture; this does not rule out driver compilation or intro work. No demonstrated sustained GPU clock/power collapse. These findings cannot be assigned retrospectively to bench scenes or the current no-overlay session. Thread names/IDs must be re-established per run; `XThread` names do not identify an NHL subsystem.

## Recommended single gameplay test — proposed, not executed

**One 120-second Desktop Mode passive capture of an already-running, user-approved CPU-versus-CPU match**, with manual same-host scene/freeze markers. Keep current session, launch route, settings, uncapped behavior and AC/battery state. No deliberate match restart: if the intro has already passed, mark A absent and prioritize B/C. If there is no naturally occurring C, report insufficient coverage; do not prolong automatically or change game settings. If NHL is not already running, stop and request separate launch approval.

User effort: about 2–3 minutes setup and two minutes capture, plus a short note; typically **5–7 minutes total**. An observer at the terminal is preferable. Switching focus to type markers can itself affect scheduling/input: record focus changes and avoid classifying those intervals. A solo observer may write approximate UTC times instead; explicitly retain human timing uncertainty (often seconds), not invented subsecond accuracy.

### Exact proposed commands

These commands are for a **later approved capture**, not run by this task. They use verified command names and the existing collector interface. No environment variables are exported or game launch commands supplied.

Terminal 1, repository checkout:

```bash
cd "$HOME/Projects/nhl-legacy-recomp" || exit 1
ps -C nhllegacy.exe -C nhllegacy -o pid=,comm=
read -r -p 'Verified Linux PID of the already-running NHL process: ' NHL_PROFILE_PID
ps -p "$NHL_PROFILE_PID" -o pid=,comm=
# Continue only after confirming that this is NHL.
python3 tools/ally-profiler/ally_profiler.py collect \
  --session desktop --pid "$NHL_PROFILE_PID" --duration 120 --interval 0.5
```

The `ps` names are candidate filters, not a guarantee of the release's Linux comm spelling. If no unambiguous candidate appears, **stop** and request the known PID/name; do not guess, attach, scan prefixes or select Steam/wineserver. The second `ps` checks the entered PID/name before collection: execute these steps individually and continue only after confirming NHL. The collector itself does not prove a PID belongs to NHL. It guards subsequent PID reuse with start ticks.

The collector prints a new unique directory under `~/nhl-ally-profiles/`; it exclusively creates `metadata.json` and `telemetry.jsonl`. Do not override its base, reuse a previous run directory, redirect into the installation or upload these raw files. It records 240 requested samples; the first CPU delta is null and errors may reduce valid coverage. Actual schedule/coverage must be checked, not assumed.

Terminal 2, marker helper **in the shell only**; no file, launcher or service is installed:

```bash
while read -r -p 'Scene/freeze marker (A-intro, B-wide, C-bench, C-player, freeze-start/end; q stops notes): ' NHL_SCENE; do
  test "$NHL_SCENE" = q && break
  python3 -c 'import datetime,json,sys,time; print(json.dumps({"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"monotonic_ns":time.monotonic_ns(),"marker":sys.argv[1]}))' "$NHL_SCENE"
done
```

Keep marker output locally with the new run as a **new** `scene-notes.txt` after collection, using an editor without overwriting existing files; no raw notes go to GitHub. Mark transitions back to B, not just C starts. Mark uncertain boundaries and focus interruptions. Timestamp is key submission time, not event onset: note estimated human delay. Marker monotonic time and collector `monotonic_ns` share the Linux host clock, avoiding filename-based clock alignment; sampling still has ~0.5 s granularity and non-atomic reads. UTC is corroboration and could be adjusted by clock synchronization. No game-clock or simulation timestamp is generated.

Optional **within this same test**, only if another observer can do it without disrupting play: one wait-state snapshot during B and one during C. In another shell enter the same verified PID, then run:

```bash
read -r -p 'Same verified NHL PID: ' NHL_PROFILE_PID
date -u '+%Y-%m-%dT%H:%M:%S.%NZ'
ps -L -p "$NHL_PROFILE_PID" -o pid=,tid=,comm=,stat=,wchan:32=
```

Retain output locally with its scene label. No CPU percentage is requested because `ps %cpu` is a lifetime average, not the collector's interval delta. `wchan` visibility is conditional; one snapshot is weak evidence. Skip this supplement entirely if cumbersome or denied; never retry as root. This optional spot check is not a scheduling trace and does not add a second gameplay run.

### Stop, coverage and concise result

Automatic stop is 120 seconds. **Ctrl-C in the collector terminal stops sampling only**, retaining partial telemetry; `q` exits marker entry. Stop early if the collector appears to worsen responsiveness, access errors persist, PID is wrong/exited, or output isolation fails. Do not stop the game or Steam. The collector otherwise continues to its deadline even after a target exits; inspect errors. No configuration was changed, so rollback is simply stopping these observer commands; there is no cap, overlay, service or environment setting to undo.

Record teams/arena, CPU-versus-CPU, current session type, warm/cold session context, controller/focus events, visible symptoms, AC/battery and only settings actually known. Do not open settings to reverify mid-test. Do not infer missing values. Limit comparisons to continuous scene segments, flag transition/observer intervals and conservatively exclude at least one sample on either side of uncertain boundaries; increase exclusions by stated human timing uncertainty. Very short C segments may be unusable. Keep wall-time durations and coverage in the result.

Produce a small offline table: scene and number/duration of usable segments; freeze notes; per-process and per-identity hot/CP/other thread CPU distributions; switch-count deltas per second; sampled R/S/D fractions; valid sensor median/range and errors; collector duration/gaps. Compare multiple C segments with neighboring B rather than relying on a single outlier. Do not sum process plus threads, reuse old TIDs, treat first null as zero, or describe CPU state counts as wait durations. No new FPS estimate is available in this test. Raw collection files remain outside Git; publish only sanitized aggregates after separate analysis.

## Expected diagnostic value and decision rule

| Observed scene-tagged result | Supported next inference | Still unknown / next boundary |
| --- | --- | --- |
| C freezes with one thread persistently busy, other workers decrease | Scene-associated serial/polling/dependency pattern worth investigating | Starvation versus useful execution versus spin; guest versus CP blockage. A hot thread alone is not the culprit. |
| C workers repeatedly S/D with low CPU, perhaps same exposed wait channel | Waiting is plausible; kernel wait category may guide follow-up | GPU fence, host synchronization, driver wait and guest logic not identified; low CPU alone is not proof. |
| C increases broad CPU work and/or GPU clock/power | Additional scene workload or shared-power behavior is plausible | No valid GPU busy/completion measurement, no CPU/GPU-bound verdict. |
| Strong visual C freezing, passive metrics similar to B | This passive test has reached its attribution limit | Repeated output, animation stalls and presentation scheduling remain unresolved; request producer lineage/wait evidence or separately approve an appropriate external trace. |
| No C or no freeze occurs | Non-reproduction/insufficient scene coverage | Cannot exonerate any stage; report coverage rather than fabricate a diagnosis. |

This test can characterize **scene-associated intermittent freezing**, but cannot measure exact freeze length from sensors alone or distinguish sustained simulation slow motion from intermittent stale images. It cannot conclusively separate CPU starvation from waiting, CPU from GPU limitation, slow rendering from repeated output, or presentation from simulation stalls. Neither period-clock samples nor high FPS fill those gaps. A fresh MangoHud pilot could later add cadence, with separate launch approval, but still cannot establish image freshness; it is not automatically the next answer.

## Safety, validation and recommended next action

No game process sampling, gameplay capture, process attach, stack inspection, log search in an installation, profiler injection, privileged operation, settings change or build occurred. Only tool discovery, self-process/kernel policy reads, source/report inspection and synthetic/offline documentation validation were used. Expected collection overhead is low but **unmeasured**: historical collection duration (~10.5 ms per 0.5 s sample) is observer work duration, not a proven FPS penalty. Do not increase sampling frequency to chase millisecond stalls. Manual notes and optional `ps` snapshots add observer disturbance; acknowledge it.

Files changed: this report and `reports/README.md` only. Existing **32 synthetic tests** passed; documentation whitespace, local Markdown links, proposed shell syntax and staged-file allowlist were checked. No new parser, collector, analysis script, raw recording or proprietary artifact is committed. Existing 011/013 statistics were reviewed rather than rerun without a new question.

**Recommended next action:** approve this one 120-second passive, scene-tagged test on the already-running release, prioritizing naturally occurring bench/player close-ups. It needs no NHL restart, root privileges or additional software. Any launch/restart, instrumentation, new logging flags, tracing privilege, package installation or Steam/Proton/session change remains a separate approval gate. Stop after publishing this plan; do not execute the test now.
