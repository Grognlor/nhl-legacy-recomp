# 018 — Ally wait-state capture analysis

## Executive summary

**The active GPU Commands thread is frequently observed inside a DRM synchronization wait.** In the wait recording, Linux TID **8471** exposes `drm_syncobj_array_wait_timeout.constprop.0` in **194/300 snapshots (64.67%)** and averages **28.91% of one logical core**. The guest-execution thread **8519**, `XThread0204 (F8`, averages **95.67%**, predominantly R. This establishes real sampled host-side DRM waiting, improving on CPU-only inference in Report 016. It does **not** identify the SDK/Vulkan caller, a continuously blocked interval, useful guest work, GPU saturation or the cause of a freeze.

**DRM waiting is not a stable freeze-specific signature:** at ±1 s it appears in **42/70 freeze-neighborhood samples (60.00%)**, versus **152/229 other interval-ending samples (66.38%)**. The direction reverses at other window widths. CP CPU activity is lower around markers in both recordings, while hot-thread occupancy does not increase. A coupled pipeline with synchronization/backpressure remains plausible; a sole hot-thread computation bottleneck is not demonstrated.

**These are separate sessions, not synchronized measurements.** The CPU/GPU telemetry starts **66.587 s after the last wait snapshot**, or **66.387 s after its end record**. There is zero overlap. GPU clocks/power in the later session cannot explain waits or freeze events in the earlier one. The marker file contains **43 events**: 16 belong to the wait window (seven freezes/nine camera transitions), four to the CPU window (all freezes), and 23 to neither (21 older-session events and two later presses).

Recommend one **verified-overlap, typed-scene 60-second comparison** using the already implemented three tools, with ≥50 seconds of actual shared coverage. This adds the missing joint observation of waits, CPU and sensors during known bench/player close-ups. No rebuild, overlay, new package, cap or settings change is needed. Further gameplay profiling remains a separate approval; no live test or optimization is run here.

## Scope, inventory and evidence preservation

Branch `perf/ally-investigation`; starting HEAD `758c8e73f0c3d1c560cc884b9f0782bcaab2b917`; origin `Grognlor/nhl-legacy-recomp`. Tracked tree initially clean; a pre-existing untracked `tools/ally-profiler/__pycache__/` was left untouched and excluded from staging. Read reports [016](016-emulated-thread-bottleneck-investigation.md), [017](017-targeted-thread-wait-state-diagnostic.md), relevant 013–015 source findings, profiler README, sampler and existing offline analyzer. All inspection/analysis is offline. No live PID access, game/Steam operation, system/controller modification, asset/executable inspection or privilege use.

Inputs are the five named files under local `diagnostics/capture-017/`. Sizes: wait metadata **747 B**, wait JSONL **230,478 B**, CPU metadata **381 B**, telemetry JSONL **1,657,433 B**, markers **4,408 B**. All parse completely; JSON nonfinite constants are rejected. Original files remain unmodified, locally excluded and untracked. Their hashes are retained in the analyzer's local aggregate output for preservation checks; raw recordings, boot UUID, private paths, binaries and system identifiers are not published.

Dates below are **recorded UTC values**, not independently calibrated wall time. The files label these sessions 2026-10-24; this report does not alter them to match any external calendar/context date.

## Validation and timing methodology

| Check | Wait-state recording | Separate CPU/GPU recording |
| --- | --- | --- |
| Requested session | 60 s / 0.2 s; two explicitly selected threads | Desktop, 60 s / 0.5 s |
| First sample UTC | **2026-10-24 04:53:05.088790** | **2026-10-24 04:55:11.475742** |
| Last sample UTC | **04:54:04.888811** | **04:56:10.975708** |
| Sample span | **59.800017889 s** | **59.499963666 s** |
| Samples / CPU-rate intervals | **300 / 299** | **120 / 119** |
| Gap range | **197.961–203.260 ms** | **499.464–500.542 ms** |
| Gaps >1.5× requested interval | **0** | **0** |
| Read-duration mean / median / max | **0.907 / 0.806 / 5.904 ms** | **9.748 / 9.552 / 14.419 ms** |
| UTC-minus-monotonic offset spread | **0.0277 ms** | **0.0141 ms** |
| Footer / errors | End at **04:54:05.088831**, reason `duration`, 300 samples, 390 unavailable-channel observations; counts verified | No end record by collector design; no process/task/discovery errors |

Both metadata sets identify historical process PID **8435**, start tick **87309**; selected guest TID **8519**, start **87818**, and active command TID **8471**, start **87570**, match every available snapshot in both streams. Names/start identities are stable and counters nondecreasing. This supports continuity of the same process/thread identities; it does not prove executable provenance or exclude unobservable same-tick reuse/re-exec. Wait metadata records a boot ID; CPU/marker metadata do not, so same-boot consistency rests on timestamps and identities rather than a second boot token.

First-to-first separation is **126.386954 s**. No timestamp rebase, equal-row pairing, sensor interpolation across the gap or cross-run event correlation is performed. Requested durations and folder names are not capture boundaries. The last sample is the conservative event-alignment end, even though the wait footer is ~0.2 s later. CPU capture's actual shutdown time is not recorded.

Markers are filtered by timezone-aware UTC coverage **first**, then checked against monotonic coverage and clock-offset consistency. This avoids admitting earlier-boot markers merely because uptime values overlap. Full marker-file monotonic order is not required across reboots; filtered subsets must increase. Old October 22 events are excluded. The two later freezes at **04:56:29.120274 / 04:56:32.059446** lie outside both captures; no samples are assigned to them. The current-session marker offsets agree with the recordings under the analyzer's explicit 50 ms discontinuity guard; observed sample-clock spreads above are far tighter. That guard is a sanity check, not a claim of 50 ms reaction accuracy.

Rates use same-identity tick deltas / recorded `SC_CLK_TCK=100` / actual interval duration. Wait rates use adjacent host monotonic stamps; CPU telemetry rates use its recorded elapsed times, independently reproducing selected-thread recorded percentages within 1e-8 percentage points. Means below are arithmetic means of valid interval rates. State/wchan full-run counts include the initial snapshot, whose rate is unavailable. No missing rate is replaced by zero. **100% is one logical core; process/thread values overlap and must not be added.**

CPU/state/wchan reads are non-atomic. At 0.2 s, one CPU tick represents about five percentage points. The hot thread's derived peak **105.00%** is retained, not clamped: tick quantization/accounting and timestamp/read skew can make one short interval exceed 100%. Its integrated rate is **95.6689%**, not sustained execution above one core. Snapshot and read duration are observer measurements, not measured gameplay overhead.

## Wait-state recording: execution, state and wait channels

| Metric | Guest 8519 | GPU Commands 8471 |
| --- | ---: | ---: |
| Recorded comm | `XThread0204 (F8` | `GPU Commands (F` |
| Mean / median CPU | **95.669 / 95.003%** | **28.913 / 29.998%** |
| Min / max CPU interval | **69.94 / 105.00%** | **10.00 / 45.00%** |
| Integrated CPU seconds over sample span | **57.21 s** | **17.29 s** |
| State snapshots R / S / D | **296 / 4 / 0** | **94 / 205 / 1** |
| Mean voluntary / involuntary switches per second | **409.41 / 276.02** | **822.24 / 154.14** |
| Hidden/unavailable raw `0` | **296** | **94** |
| Exposed symbols | **4 futex** | **206 total**, detailed below |

CP wchan distribution, all 300 snapshots:

| Raw wait-channel text | Count | Interpretation boundary |
| --- | ---: | --- |
| `drm_syncobj_array_wait_timeout.constprop.0` | **194** | Sampled DRM sync-object host-wait function; object, flags, caller and completion cause unavailable |
| `0` | **94** | No exposed wait symbol; often running, but not proof of no wait |
| `anon_pipe_read` | **6** | Pipe-read wait category; no IPC peer or asset-I/O attribution |
| `futex_do_wait` | **5** | Generic synchronization wait, not an identified SDK mutex/GPU fence |
| `lock_mm_and_find_vma` | **1** | Memory-management-related kernel site; insufficient evidence for a resource-streaming/page-fault diagnosis |

The hot thread exposes `futex_do_wait` four times; the other 296 are raw `0`. Missing symbols are **not** silently translated into active execution. State and wchan can differ because read at different instants: CP has 192 S+DRM pairs and two R+DRM pairs, plus three S+`0`. This does not invalidate either sampled field or identify an exact transition time. Status counters are available; no permission/read errors are encoded in the supplied wait snapshots. Footer **390** unavailable observations equals 296 guest +94 CP raw-zero values, not 390 proven permission failures.

The longest consecutive run of the DRM label is **12 sampled observations**, spanning sample endpoints **t=0.600–2.800 s**. This is **not a measured uninterrupted 2.2-second wait**: the thread may wake/work/re-enter many times between snapshots. It precedes the first freeze press, and shows why repeated occurrence alone cannot diagnose a slideshow.

### What the DRM symbol establishes

The official [DRM sync-object documentation](https://docs.kernel.org/gpu/drm-mm.html#drm-sync-objects) describes synchronization containers used for Vulkan-style fences/semaphores and host waits. The representative upstream [Linux v6.18 implementation](https://github.com/torvalds/linux/blob/v6.18/drivers/gpu/drm/drm_syncobj.c#L1003), `drm_syncobj_array_wait_timeout`, lines **1003–1152**, waits for relevant objects/fences and can sleep; binary/timeline wait wrappers call it around **1184–1217**. Depending on flags, fence availability/submission can matter as well as completion. A sync object may also involve dependencies/shared producers; shader execution is not its only possible delay.

These references explain the **kernel category**, not the captured machine's exact kernel build or user-space call chain. The `.constprop.0` suffix is a compiler-generated symbol variant, not a different measured wait type. No supplied sample gives object handle, timeout argument/result, Vulkan API, submission ID, driver stack, lock owner or GPU workload. The name containing `timeout` does **not** mean an actual timeout or error occurred. The capture supports downstream graphics synchronization being exercised, not GPU saturation, a specific readback or a broken driver.

## Freeze-aligned analysis: wait recording

Seven freeze markers and nine camera markers are inside this window. Event time is relative to its own first sample. Main neighborhoods include interval-ending timestamps in **[marker−1 s, marker+1 s)**; union comparisons deduplicate overlapping windows. CPU work in an interval precedes its ending timestamp by ~0.2 s. Presses have unmeasured human delay and no end/duration field. “Unmarked” may include freezes not reported; it is not verified smooth gameplay.

For each event, pre is **[t−3,t−1)**, near **[t−1,t+1)**, post **[t+1,t+3)**. Each wait event has ten samples per group.

| Freeze | Relative t (s) | Hot near CPU | CP pre → near → post CPU | DRM-label hits near /10 | Seconds since prior camera |
| --- | ---: | ---: | --- | ---: | ---: |
| W1 | 9.730 | 97.00% | 38.50 → 30.50 → 30.00% | 4 | 5.089 |
| W2 | 18.055 | 94.99% | 34.50 → 23.50 → 28.00% | 7 | 1.998 |
| W3 | 24.276 | 93.50% | 23.50 → 25.00 → 26.00% | 2 | 2.812 |
| W4 | 28.568 | 95.00% | 26.00 → 23.00 → 26.00% | 7 | 2.529 |
| W5 | 31.193 | 95.53% | 24.49 → 25.01 → 26.00% | 8 | 1.159 |
| W6 | 34.184 | 97.50% | 26.00 → 24.50 → 25.98% | 8 | 4.150 |
| W7 | 51.074 | 93.50% | 21.50 → 28.00 → 35.50% | 6 | 6.608 |

| Group | Intervals | Hot CPU | CP CPU | CP sampled R/S/D | CP DRM-label hits |
| --- | ---: | ---: | ---: | --- | --- |
| Full valid rate stream | 299 | 95.67% | 28.91% | 93/205/1 | 194/299 |
| ±1 s freeze neighborhoods | 70 | **95.29%** | **25.64%** | 22/47/1 | **42/70 (60.00%)** |
| Other interval-ending samples | 229 | **95.78%** | **29.91%** | 71/158/0 | **152/229 (66.38%)** |

Hot occupancy is slightly **lower**, not higher, near freezes. CP activity falls versus the pre window at four of seven events and increases at three; W1 near is above the full-run CP mean. There is no single per-event CPU signature. Quiet CP can reflect less generated work, blocked completion/dependencies or phase changes; CPU percentage alone cannot choose.

### Window sensitivity and context switches

| Half-width | Selected intervals | CP CPU near / outside | CP DRM-label fraction near / outside |
| --- | ---: | --- | --- |
| 0.5 s | 35 | **23.71 / 29.60%** | **26/35 (74.29%) / 168/264 (63.64%)** |
| 1 s | 70 | **25.64 / 29.91%** | **42/70 (60.00%) / 152/229 (66.38%)** |
| 2 s | 128 | **26.95 / 30.38%** | **87/128 (67.97%) / 107/171 (62.57%)** |

Lower CP CPU is robust to these window choices; an increase in DRM-label hit fraction is **not**. Neither hit fraction is actual wait duration. Small event counts, autocorrelation, reaction delay, scene changes and mixed phases preclude a causal/statistical significance claim. A real few-millisecond delay can be perceptually important and largely invisible at five Hz.

Mean voluntary/involuntary rates near versus outside are **370.15/314.32 versus 421.41/264.31 per second** for the guest; **671.59/175.44 versus 868.29/147.63** for CP. Involuntary counts increase in aggregate here, unlike earlier captures, but do not measure scheduler latency. W2 includes a guest peak of **3108.53 involuntary switches/s**; a **2575.25/s** interval also occurs in W7's pre window. This motivates caution about scheduling/activity transients, not a diagnosis of CPU starvation. Many switches per second and repeated identical wchan samples can coexist with short repeated waits.

The single D snapshot is CP at **t≈28.000 s**, exposing `lock_mm_and_find_vma`, about 0.568 s before W4. The hot thread is R then. This is a distinct observation from Report 016's multi-thread D sample, not evidence the same event recurred. No sustained D episode is measured.

## Camera transitions and changes over time

The nine camera markers identify **transitions only**, without scene types/durations. Four freezes occur within three seconds of a prior camera marker; the others are ~4.15, 5.09 and 6.61 seconds later. Camera markers can also occur after a freeze press. No alternating wide/close-up assumption is justified, and no bench/introduction/replay can be identified from these files.

| Camera | Relative t (s) | CP CPU 2 s pre → 2 s post | DRM hits pre → post |
| --- | ---: | --- | --- |
| C1 | 4.641 | 34.50 → 39.00% | 5/10 → 5/10 |
| C2 | 10.127 | 33.50 → 30.00% | 6/10 → 6/10 |
| C3 | 16.057 | 35.00 → 28.00% | 8/10 → 6/10 |
| C4 | 21.464 | 27.50 → 24.00% | 7/10 → 7/10 |
| C5 | 26.040 | 26.00 → 24.50% | 4/10 → 8/10 |
| C6 | 30.035 | 24.49 → 25.01% | 9/10 → 8/10 |
| C7 | 44.467 | 28.50 → 22.99% | 7/10 → 7/10 |
| C8 | 52.530 | 30.00 → 35.50% | 6/10 → 5/10 |
| C9 | 58.911 | 35.50 → 36.00% | 6/10 → 3/5 |

C9's post window is truncated to five samples by recording end; it is not comparable to a full two seconds. CP CPU increases at four transitions and falls at five, with no uniform transition spike or sleep pattern. Camera and freeze neighborhoods overlap and cannot be treated as independent trials.

Ten-second phase summaries (no scene labels):

| Wait-relative interval | Hot CPU | CP CPU | DRM hits / rate-ending samples |
| --- | ---: | ---: | --- |
| 0–10 s | 95.80% | 35.10% | 30/50 |
| 10–20 s | 95.51% | 29.59% | 32/49 |
| 20–30 s | 94.70% | 25.10% | 32/50 |
| 30–40 s | 96.57% | 25.20% | 38/51 |
| 40–50 s | 95.82% | 24.49% | 34/49 |
| 50–60 s | 95.60% | 34.00% | 28/50 |

The hot thread stays ~95% across phases; CP dips in the middle and rises near the end. The first phase already contains many DRM waits. These changes could reflect scene/state/workload, but cannot be named as close-ups or active play. This phase structure can confound pooled marker comparisons.

## Separate CPU/GPU telemetry recording

This recording has **four in-window freezes and zero camera markers**. The same identities persist, but neither wchan nor earlier scene labels can be carried forward across the gap.

| Metric | Whole later stream | ±1 s freeze neighborhoods | Other samples |
| --- | ---: | ---: | ---: |
| Valid CPU intervals | 119 | 16 | 103 |
| Whole-process CPU | **343.04%** | **355.02%** | **341.18%** |
| Hot TID 8519 CPU | **94.86%** | **94.50%** | **94.91%** |
| CP TID 8471 CPU | **32.55%** | **27.75%** | **33.30%** |
| Hot snapshot states (rate-ending samples) | 116 R/3 S | 16 R/0 S | 100 R/3 S |
| CP snapshot states (rate-ending samples) | 47 R/72 S | 5 R/11 S | 42 R/61 S |

All 120 snapshot counts, including first: guest **117 R/3 S**, CP **48 R/72 S**. Hot CPU range **89.97–98.00%**; CP **18.00–44.00%**. CPU values and context-switch deltas were recalculated; read errors and identity changes are absent. The whole-process increase near freezes contrasts with the quieter CP; one worker's lower CPU is not general spare capacity or proof of whole-process underload.

| Later freeze | Relative t (s) | Hot near CPU | CP pre → near → post CPU |
| --- | ---: | ---: | --- |
| T1 | 11.004 | 95.52% | 28.99 → 29.01 → 27.00% |
| T2 | 14.235 | 93.50% | 28.50 → 24.50 → 23.00% |
| T3 | 16.958 | 93.50% | 23.50 → 25.00 → 22.00% |
| T4 | 48.603 | 95.50% | 39.00 → 32.50 → 33.50% |

Four samples per pre/near/post window. T1 is essentially unchanged from pre; T2/T4 decline and T3 rises. CP near/outside at half-width 0.5 s is **25.25/33.08%**, at 2 s **28.37/33.78%**: the broad lower-CP pattern persists, not an every-event causal rule. Mean switch rates near/outside: guest voluntary **678.40/808.81**, involuntary **338.26/307.74**; CP voluntary **969.54/1120.93**, involuntary **182.01/171.63** per second. No wait categories can be inferred from these counts.

CPU phase means by successive ten-second bins: hot **95.79, 94.38, 94.30, 94.84, 94.95, 94.95%**; CP **28.84, 25.81, 27.80, 40.21, 37.81, 35.26%**. This later session's phase pattern differs from the earlier wait session; matching their relative seconds would fabricate synchronization.

### Later-session sensors only

| Sensor | All 120 samples mean / median / range | Freeze-neighborhood / outside mean (16 /103 valid rate-ending samples) |
| --- | --- | --- |
| hwmon sclk | **903.08 /1160 /200–1160 MHz** | **719.56 /938.20 MHz** |
| edge temperature | **69.07 /69 /67–72 °C** | **69.06 /69.06 °C** |
| slowPPT average | **19.582 /19.6855 /18.370–20.161 W** | **19.893 /19.530 W** |
| slowPPT input | **20.848 /20.539 /11.328–28.486 W** | **19.827 /21.014 W** |

GPU busy readings are rejected out of range in **108/120** samples; the other 12 do not validate that source. All 120 are excluded from utilization conclusions; no rescaling/clamping. DPM states are not instantaneous clock guarantees. slowPPT channels share a power-domain label, are not GPU-only, and must not be added. Power target/settings, throttle flags and CPU frequencies are not independently verified.

Lower sclk around later freeze markers is an observation, not evidence of throttling or CPU/GPU power redistribution. Temperature is unchanged in aggregate and power channels show different behavior. A clock can fall because work is blocked or less work arrives, rather than causing that blockage. None of these sensors was measured during the earlier DRM wait events. No current frame-time, animation-step, image-freshness or display-delivery stream exists.

## Ranked hypotheses and evidence limits

| Candidate | Supporting observation/source | Contrary/missing evidence | Assessment |
| --- | --- | --- | --- |
| **1. Graphics synchronization / bounded-resource backpressure** | CP repeatedly sampled in a DRM wait; quieter CP near freezes in both streams. Pinned runtime has fence/frame-slot waits and retained synchronous readbacks. | Same wait common outside markers; no stable near-freeze hit-fraction increase, wait duration/object/caller or GPU completion. | **High confidence waiting occurs; moderate plausibility as a contributor, low confidence in any causal site.** Actual wait-origin/latency attribution still needed. |
| **2. Serial guest execution or polling** | Guest uses ~95% of one core in both captures and most phases. | No freeze-linked increase; useful instructions/function unknown; hot occupancy is not a dependency graph. | **High confidence sustained occupancy, low–moderate possible contribution; sole-cause claim unsupported.** |
| **3. Scene-dependent rendering/resource/animation work** | User's severe close-ups; CPU/CP phases vary and renderer supports equipment composites and resource work. | No typed scenes, readback/upload counts or workload timing in supplied files. Camera changes mixed. | **Plausible, unlocalized.** Bench/player attribution cannot be verified here. |
| **4. Presentation/freshness problem** | Historical high present FPS plus motion freezes and mailbox reuse architecture. | No present/image/animation progress data in either new run. DRM waits may be upstream or downstream of presentation. | **Still viable, unmeasured.** |
| **5. GPU workload saturation** | Some completion/dependency waiting is compatible with GPU work; lower CP CPU does not exclude it. | Invalid busy source, non-simultaneous clocks, no device timings. | **Unknown; “GPU-bound” unsupported.** |
| **6. Guest command starvation / CP submission computation bottleneck** | Quiet CP can fit missing work or brief serial submission costs. | Exposed waits predominantly DRM, not an identified empty-ring event; mean CP ~29/33%, peaks ~45/44%, not sustained CPU saturation. | **Pure empty-ring starvation weakened as a complete explanation, not ruled out; sustained CP compute limit has weak support.** |
| **7. Host scheduling starvation / global simulation clock fault** | Some involuntary-switch spikes; guest and render progress can decouple. | No runqueue delay, CPU clocks, effective priorities, simulation steps or timer-rate measurements; spikes not consistent across events. | **Low positive evidence.** No timing/priority/affinity change justified. |

Pinned source mechanisms from Report 016 remain relevant: `CommandProcessor::WorkerThreadMain` waits on missing commands and delays read-pointer writeback until batch execution; Vulkan `IssueCopy` retained full readback can await GPU work; `BeginSubmission`/fence checks await bounded slots; presenter can wait for swapchain/paint resources and queue acquisition. The wchan does not select among those call sites. Match-clock progression, reported rendering FPS, sampled thread R state and CPU execution rates are different observations; none alone establishes smooth animation or real-time input/simulation progress.

## Single recommended next step

**Approve one genuinely concurrent 60-second run of the existing three tools with independent typed-scene notes.** The new information needed is the *joint* behavior of CP wait categories, CPU work and valid sensor trends inside known bench/player shots, compared with neighboring wide-angle play. Existing runs lack both concurrency and scene identity, so another calculation on these files cannot recover it. The tools already exist; no code/runtime optimization or package is prerequisite.

Use Report 017's foreground-terminal workflow: the existing marker recorder unchanged; CPU collector at 0.5 s; targeted sampler at 0.2 s after current discovery and explicit identity confirmation. Prepare identities/terminals before starting the timed collectors; start them within a few seconds, rather than finishing one first. Record current run paths and exact scene descriptions keyed to marker order/UTC. Do not reuse historical IDs. Both readers end automatically; Ctrl-C only observer terminals for early stop. No game/Steam launch, cap, graphics/power/controller change or MangoHud.

Acceptance before interpretation: normal end records/errors checked, **≥50 s actual overlap**, compatible clocks/identities, at least one clearly typed close-up/bench segment and neighboring wide-angle coverage. If overlap or scenes are missing, report insufficient coverage rather than invent alignment or repeat automatically. Freeze press reaction remains uncertain; compare neighborhood/window sensitivity and local scene controls, not individual sample hits as durations. If collection worsens responsiveness or access is unavailable, stop without privilege escalation.

A shared change in CP DRM waits, CPU activity and clocks during typed close-ups would localize a useful follow-up but still not identify a Vulkan caller. Similar rates/labels across scenes despite visible freezes would show that coarse external sampling is insufficient; subsequent *separately approved* wait-origin/latency or producer-side lineage evidence would be required. Repeated `drm_syncobj` alone is not that evidence. This recommendation does not authorize the run now.

## Reproducibility, tests and changed files

Added [analyze_wait_capture.py](../tools/ally-profiler/analyze_wait_capture.py), a standard-library offline reader that accepts explicit recording files, validates clocks/identities/counters/footer, filters multi-session markers with UTC plus monotonic checks, and emits sanitized aggregate JSON on stdout. It neither reads live proc/sysfs nor writes inputs, launches processes or infers synchronization. Full snapshot counts differ deliberately from valid rate-ending groups. Entire invalid GPU utilization source is excluded. Derived JSON is not committed.

Reproduce from the repository root; this command reads existing recordings and prints aggregate JSON:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/analyze_wait_capture.py   --wait-dir diagnostics/capture-017/20261024T045305Z-6yf86ze1   --telemetry-dir diagnostics/capture-017/20261024T045511Z-d6zw9zsz   --markers diagnostics/capture-017/scene-markers.jsonl
```

The command prints JSON only; save it locally with exclusive/non-overwriting redirection if desired. No specific output file is required. Run safe tests with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/ally-profiler -p 'test_*.py'
```

**68 tests pass: 57 existing plus eleven new offline tests** covering old-session/boot marker exclusion, inconsistent clocks, order/timezones, tick-derived rates, hidden channels, PID/TID/counter changes, duplicate IDs, deduplicated marker neighborhoods/empty events, distinct non-overlapping captures, invalid/truncated footers, nonfinite JSON and preservation of synthetic inputs. Actual files were checked against metadata, identities, counters, normal footer and clock/gap statistics; five-file SHA-256 checks before/final analysis verify preservation. Syntax, local links, proposed shell syntax, whitespace and staged allowlist checked. No real-game speed/overhead claim follows from tests.

Changed files: this report, report index, offline analyzer and tests, and a short profiler README entry. No sampler/runtime behavior changes. Existing raw evidence, outside marker script and pre-existing `__pycache__` are untouched/uncommitted. Only the investigation branch is pushed; no master/upstream changes. Stop after publication.
