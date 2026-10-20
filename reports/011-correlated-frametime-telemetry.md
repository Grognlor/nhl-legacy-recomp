# 011 — Correlated frame-time and CPU/GPU telemetry investigation

## Executive findings and scope

Read-only analysis of the supplied recordings on `perf/ally-investigation`, starting commit `9d804c9beb8f3a9ea29b7c423f4ccccd65d66abd`; initial working tree clean. Repository/origin match `Grognlor/nhl-legacy-recomp`. Reviewed report 009/runbook, earlier thread/synchronization findings in report 005, and report 006/007 limitations. Task 010 was a conversational read-only inspection and did not create a numbered report; previous reports/index are preserved.

**The long CSV strongly supports genuine per-frame application logging. It captured brief and clustered pacing problems, but not the reported approximately ten-second presentation slideshow.** A severe simulation slowdown or repeated/stale visible frames cannot be excluded by application presentation intervals. This is consistent with the user's assessment that this capture was smoother than usual; it does not invalidate other episodes.

- 8,909 frames, 119.846495 s summed intervals, 74.337 presentation FPS from frame durations; p50/p95/p99 **14.982 / 26.031 / 35.746 ms**, maximum 75.744 ms.
- 126 frames exceed 33.33 ms (1.414%), nine exceed 50 ms (0.101%), none exceed 100 ms. 2,716 exceed 16.67 ms (30.486%). Thresholds are strictly greater, and percentages are frame fractions.
- Worst complete one-second window: **20–21 s, 55 frames, 55.01 duration-derived FPS**, p95 51.85 ms. Worst rolling ten-second window: **11–21 s, 67.50 FPS**, p95 33.44 ms. Neither is a sustained 10–20 FPS collapse.
- New capture's hot thread is **TID 11838, `XThread020C (F8`, mean 94.99% of one core**. Earlier `XThread0204` is not the hot identity here; current TID 11836 averages 18.27%. Do not map names to fixed guest functions across launches.
- Poorer windows coincide approximately with **lower process/worker CPU**, while the hot thread remains nearly constant. This supports investigating dependencies/workload/pacing; it proves no causal bottleneck.
- GPU clock/temperature/labelled power are available. The broken utilization source is excluded throughout, including its occasional in-range readings. Four named pipeline workers show **zero accumulated CPU ticks** across the entire telemetry interval; sustained compilation on those workers is unsupported in this run.

No launch/termination, game build, runtime setting, Steam/Proton/system modification, executable/asset access or raw-data upload occurred. Only repository analysis code, tests, aggregate artifacts and documentation were added.

## Recordings, identity and gameplay context

The four user-provided data sources were directly accessible and read in place:

- `~/nhl-ally-profiles/mangohud-pilot-20261020T161457Z/nhllegacy_2026-10-20_09-43-18.csv` and its `_summary.csv`.
- `~/nhl-ally-profiles/20261020T164316Z-wi4msjfl/{metadata.json,telemetry.jsonl}`.
- Earlier `~/nhl-ally-profiles/mangohud-pilot-20261020T161457Z/nhllegacy_2026-10-20_09-31-34.csv`.

Exact byte sizes and SHA-256 identities for all five files are in [analysis.json](artifacts/011/analysis.json), `input_identity`. Raw files remain outside the repository. The long CSV's SHA-256 is `e04934a99c3ae903a2b0ca9e93845d2bab7c1759c32323bbeaa52bca86398b36`; telemetry SHA-256 is `5bd1d37726dee45e582da5a8869e06ba7a15c91d6b77237d67dffa9e5fcbf6f6`.

User-supplied long-run context: rendered CPU-versus-CPU Toronto at home against Chicago, Toronto arena, approximately 720p/25 W with previously documented settings (1×, VSync off, FSR on, shadows off). Busy gameplay, whistles, close-ups and replays are reported triggers across play sessions, not timestamped events in these recordings. No exact event labels, simulation/game-clock series, actual display refresh/cap/VRR series or AC/battery history are available. The old and new recordings are not controlled comparisons of teams, arenas, camera or game phase. Successive launches improving speed remains a user observation, not a measured cold/warm experiment.

The MangoHud preamble identifies Steam Runtime 4, AMD Ryzen Z2 A, RADV VANGOGH and a `powersave` scheduler string. This is producer metadata, not proof of an enforced low CPU frequency or the exact selected Proton version. Numeric CPU load is a different metric from the process's core-equivalent utilization. No shortcut, prefix or installed game was inspected in this task.

## CSV schema and per-frame validation

Both CSVs contain a two-line system preamble, followed by one 16-column metrics header: `fps,frametime,cpu_load,cpu_power,gpu_load,cpu_temp,gpu_temp,gpu_core_clock,gpu_mem_clock,gpu_vram_used,gpu_power,ram_used,swap_used,process_rss,cpu_mhz,elapsed`. No repeated/duplicate header, malformed numeric row, nonfinite value, nonpositive frame interval or nonincreasing elapsed was found by the strict offline parser.

The [MangoHud v0.8.4 logger](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/logging.cpp), `start_logging`/`try_log`/`writeToFile`, records elapsed nanoseconds from logging start and creates the application/time filename at start. The [overlay frame-update path](https://github.com/flightlessmango/MangoHud/blob/v0.8.4/src/overlay.cpp) uses millisecond frame times and per-frame logging at interval zero. Version/capability were established in report 009. Actual configuration contents were not re-read; cadence is checked directly here rather than assumed from a config label.

| Consistency check | 120-second log | Earlier 20-second log |
| --- | --- | --- |
| Data rows | 8,909 | 1,503 |
| First / last elapsed s | 0.166558 / 120.016770 | 0.423180 / 20.006382 |
| Sum of all frame intervals s | 119.846495 | 19.596460 |
| Last minus first elapsed s | 119.850212 | 19.583202 |
| Sum of intervals excluding first minus elapsed span | −20.320 ms | −3.501 ms |
| Median adjacent residual, `elapsed_delta_ms - current_frametime_ms` | +0.001946 ms | +0.001933 ms |
| p99 absolute adjacent residual | 0.019162 ms | 0.018862 ms |
| Maximum absolute adjacent residual | 0.749447 ms | 0.423462 ms |

The first logged frame ends after logging has already begun; requiring sum(all frames) to equal last elapsed exactly would be incorrect. The approximately 2 microsecond mean adjacent residual is consistent with small measurement-point/recording overhead. Neither file resembles periodic sparse sampling; long timestamp gaps not represented by frame intervals were not found. These checks strongly support a complete per-frame stream **over the logged portion**, not coverage before the first row, physical scanout, one simulation update per row, one swapchain only, or unique visible game images.

1,519/8,909 frames (17.05%) are below 5 ms; minimum 1.364 ms, median 14.982 ms. Short intervals interspersed with longer ones inflate the mean presentation rate relative to a smooth ~60 Hz game. Do not discard them as invalid or claim simulation acceleration. Mixed cadence, multiple presentation paths or other behavior remain unverified without render/presentation attribution. The summary's rounded 74.3 average FPS, 13.5 ms average frame time and other aggregate values agree with the raw stream. Its 1%/0.1% FPS metrics use a different definition from this report's frame-time percentiles and are not substituted for p99.

## Time alignment: conditional, coarse and sensitivity-tested

Telemetry metadata requests **150 s at 0.5 s**, Desktop session, PID 11708, `SC_CLK_TCK=100`. There are 300 samples spanning UTC **16:43:16.368150–16:45:45.868156**, elapsed 0.000111–149.500125 s. Maximum interval is 0.500920 s; no process errors or PID replacement: identity `(11708, start_ticks=205823)` is stable. The initial CPU sample is null, leaving 299 rate intervals. Collection duration averages 10.51 ms, maximum 22.44 ms; this is collector work duration, not a measured gameplay overhead percentage.

UTC span and monotonic span differ by only **4.129 microseconds** across telemetry. This supports internal clock stability there, but does not synchronize MangoHud's independent elapsed origin.

Current host timezone is PDT (UTC−07). If the CSV filename reflects that same unchanged timezone/clock, its start lies within **16:43:18–16:43:19 UTC**, corresponding to a telemetry-relative offset of approximately **1.631850–2.631850 s**. File modification times corroborate the coarse timeline: CSV 16:45:18.759775 UTC; telemetry 16:45:45.876967 UTC. They are filesystem write times, not start markers; no precise offset is inferred from them. The containing directory's `161457Z` name is a preparation timestamp, not CSV start time.

All aligned comparisons use three **assumed offsets**: lower endpoint, midpoint 2.131850 s, and upper endpoint. Sub-millisecond distinctions from subtracting the first telemetry elapsed value are immaterial beside the one-second filename uncertainty. There was no shared marker, verified capture-time timezone record, or timestamped event. Thus same-session overlap is well supported under the filename-clock assumption, broad multi-second associations are useful, and **individual frame-to-sample attribution is not established**. If filename timezone/clock history is wrong, these alignments are invalid. Never align by inventing simultaneous zero times or by the preparation-directory name. The earlier CSV is about 11 minutes earlier and cannot be correlated with this telemetry.

For illustration, Pearson correlations across 23 nonoverlapping five-second bins (5–120 s) between bin mean frame time and process CPU range **−0.510 to −0.515**, and clock **−0.450 to −0.424**, over the three offsets. No significance test, causal inference or independent replication is claimed; workload/time trends, repeated sensor values and measurement delays confound these descriptive correlations.

## Frame-time behavior across the recording

The table uses fixed ten-second timestamp bins, half-open `[start,end)`. FPS is derived from the included intervals, so edge-crossing frames cause small duration differences. Initial unlogged time is absent; one final frame at 120.016770 s is outside the table but included in global statistics. Rolling windows step by one second and use complete nominal windows from 1 s onward.

| CSV elapsed s | Frames | Duration FPS | p95 ms | p99 ms | >33.33 ms | >50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0–10 | 751 | 76.39 | 18.97 | 27.76 | 0 | 0 |
| 10–20 | 691 | 69.00 | 31.41 | 46.02 | 31 | 2 |
| 20–30 | 704 | 70.53 | 31.15 | 44.72 | 22 | 4 |
| 30–40 | 738 | 73.72 | 29.01 | 38.50 | 17 | 1 |
| 40–50 | 798 | 79.78 | 19.73 | 22.12 | 0 | 0 |
| 50–60 | 705 | 70.51 | 28.33 | 36.45 | 16 | 0 |
| 60–70 | 713 | 71.43 | 30.36 | 39.58 | 21 | 1 |
| 70–80 | 762 | 76.21 | 26.88 | 32.82 | 7 | 0 |
| 80–90 | 764 | 76.36 | 26.16 | 31.93 | 1 | 0 |
| 90–100 | 774 | 77.39 | 22.52 | 30.40 | 6 | 0 |
| 100–110 | 754 | 75.36 | 19.59 | 31.81 | 4 | 0 |
| 110–120 | 754 | 75.41 | 21.46 | 30.20 | 1 | 1 |

Additional pacing evidence:

- Complete one-second duration FPS ranges **55.01–82.99**, five-second **64.00–80.95**, ten-second **67.50–79.91**. These quantify presentation, not simulation.
- Worst five-second window **16–21 s**: 321 frames, p95 **44.36 ms**, 28 frames >33.33 ms, six >50 ms. Short frames keep its duration FPS near 64 despite conspicuous hitches.
- Clustering rule: slow frames >33.33 ms belong to one cluster when successive slow-frame timestamps are no more than one second apart. It allows fast intervening frames and is not a continuous stall definition. Largest cluster: **17.505–21.645 s**, 30 slow frames over 4.140 s. Other clusters: **57.867–61.872 s**, 21 over 4.005 s; **29.070–33.671 s**, 18 over 4.601 s.
- Longest-duration consecutive run >33.33 ms contains **two frames totaling 83.905 ms**, near 20.550–20.634 s. All nine >50 ms spikes are isolated by at least one frame <=50 ms. No 100+ ms interval appears.

There is real pacing degradation, concentrated in particular multi-second regions, but the logged presentation stream does not show continuous ten-second severe low-rate episodes. No event annotations tie the 17–22 s cluster to a whistle, close-up or replay; doing so would invent context. Physical display repetition, simulation pauses or an uncaptured severe episode remain possible.

## CPU, threads and scheduling

Process CPU over all 150 seconds: **317.43% mean, 330.00% median, 236.00–398.00% range**, where 100% is one logical core. It overlaps thread totals; never add them. CPU deltas summarize elapsed intervals, thread states are instantaneous observations, and context-switch rates measure counts rather than wait/runqueue duration. Short-lived threads may escape 0.5-second sampling.

| Linux TID / recorded truncated name | Mean CPU % | Notable observation |
| --- | ---: | --- |
| 11838 / `XThread020C (F8` | 94.99 | 86–100%; observed R in 291/300 snapshots; sustained hot thread |
| 11762 / `nhllegacy.exe` | 39.07 | 36–42%; role not established from name |
| 11800 / `GPU Commands (F` | 32.96 | 16–50%; primary command worker by recorded name |
| 11830 / `XThread01F8 (F8` | 30.55 | 4–66%; substantial phase-dependent variation |
| 11837 / `XThread0208 (F8` | 25.90 | 18–36% |
| 11836 / `XThread0204 (F8` | 18.27 | Not this launch's ~95% thread |
| 11835 / `XThread0200 (F8` | 18.21 | Variable worker |
| 11834 / `XThread01FC (F8` | 17.79 | Several other short-lived TIDs reuse this name |
| 11743 / `rex::thread::Ti` | 11.26 | Truncated name; precise role unknown |

76 distinct `(TID,start_ticks,name)` identities appear; 13 do not cover all 300 samples. Names alone cannot identify guest addresses/subsystems. Report 005's pinned SDK `XThread` naming derives from host thread identity, not a stable simulation function. Current Linux TIDs are local to this recording, not continuations of earlier TIDs.

Under the midpoint alignment, compare poorer pacing regions and a smoother region:

| CSV elapsed s | Process CPU % | Hot 11838 % | GPU worker 11800 % | Guest 11830 % | Guest 11836 % |
| --- | ---: | ---: | ---: | ---: | ---: |
| 17–22 | 266.80 | 94.80 | 27.00 | 10.40 | 8.20 |
| 40–50 | 341.90 | 95.10 | 36.90 | 38.50 | 21.40 |
| 57–65 | 263.13 | 95.12 | 25.88 | 8.13 | 9.63 |

These windows have uncertain boundaries as described above. The data does **not** show process-wide increased computation when pacing worsens. Several workers do less CPU work while a hot thread persists, compatible with blocked dependencies, reduced work/progress, changed scenes, or polling elsewhere.

Hot-thread voluntary/nonvoluntary context switches average **834/275 per second** over telemetry. In 17–22 s they are approximately **656/159**, versus **745/460** in smoother 40–50 s. Guest 11836 voluntary switches similarly decrease from about 2,380/s in the smooth region to 813/s in 17–22 s. There is no simple generalized preemption-rate spike explaining the bad window. High switch counts do not measure how long a thread waited, and low counts do not prove useful computation. CPU saturation on one thread is verified; its critical-path role and useful-work versus spin composition are not.

All four `Vulkan Pipeline` TIDs 11808/11809/11811/11812 have **zero CPU-rate deltas** and no R snapshots across all 150 seconds, at 100 ticks/s resolution. This weakens sustained heavy compilation on those workers in this warm capture. It does not exclude sub-tick work, synchronous compilation on other threads, driver compilation or cold-launch effects. Shader and PSO events are not directly logged.

## GPU clocks, temperatures and power

All 300 samples contain the named clock/temp/power readings used below. 284 utilization samples explicitly fail range validation; the other 16 do not rehabilitate this unreliable channel. Raw values are preserved outside Git; neither this analysis nor correlations uses utilization. MangoHud's 84.7% mean `gpu_load` may use a different path, but that path has not been verified as independent/reliable, so it is **not used to declare GPU limitation**.

Whole telemetry window: sclk **median 1,160 MHz, range 200–1,160**; edge temperature **median 67 C, range 64–71 C**. Labelled slowPPT average mean **19.220 W**, input mean **19.114 W**; these are separate channels of the same labelled platform/APU domain, not GPU-only power and not quantities to add. Three average readings are zero (telemetry elapsed ~116/136.5/146.5 s) despite positive contemporaneous input readings. They are retained as recorded, explicitly unexplained; no correction or inference of zero system power follows.

| Approximate CSV region | Mean sclk MHz | Mean edge C | Mean slowPPT average W | Mean slowPPT input W |
| --- | ---: | ---: | ---: | ---: |
| 17–22 | 1,014.5 | 67.7 | 19.86 | 18.47 |
| 40–50 | 1,040.6 | 69.0 | 20.05 | 18.94 |
| 57–65 | 1,003.9 | 67.8 | 19.71 | 21.02 |

The principal clusters are not characterized by a dramatic persistent drop in these multi-second clock/power means or a temperature peak. Clock swings exist on shorter timescales; their cause is unmeasured. Overall five-second mean frame time/clock correlation is negative but confounded by scenes and demand: higher clock can be a response, not a remedy. CPU temperature in the MangoHud CSV reaches 92 C, but no throttle counters, per-core clocks or GPU execution times establish thermal throttling. A nominal 25 W target is not a promise of 25 W constant recorded slowPPT input or average.

## Earlier 20-second comparison

| Metric | Earlier 20 s | Current 120 s |
| --- | ---: | ---: |
| Duration-derived presentation FPS | 76.70 | 74.34 |
| Mean frame time ms | 13.038 | 13.452 |
| p95 / p99 ms | 24.704 / 31.524 | 26.031 / 35.746 |
| Maximum ms | 46.265 | 75.744 |
| >33.33 ms frames | 7/1,503 (0.466%) | 126/8,909 (1.414%) |
| >50 / >100 ms frames | 0 / 0 | 9 / 0 |

The longer run has a heavier observed tail and more opportunity to sample rare events. Different teams/arenas/game states, length, warm-up and lack of concurrent earlier telemetry prevent attributing this difference to a setting, launch, cache effect or hardware change. Neither run establishes a ten-second presentation slideshow. CPU/GPU sensor CSV columns repeat between frames because those sensors are polled more slowly; they are not independent per-frame hardware measurements.

## Ranked hypotheses and what the evidence can distinguish

Ranking is investigation priority, not a proven probability ordering for episodes absent from this capture.

1. **Workload-dependent handoff/synchronization/presentation pacing, with a persistently busy guest thread.** Strongest pattern here: bad frame tails coincide coarsely with lower worker/process CPU while the hot thread stays busy. Source-known guest waits/readback/queue handoffs in reports 005/006 make this plausible. No stack, wait-duration, per-stage or GPU queue timings isolate a specific path; lower work could also reflect scene changes. Do not optimize a particular lock/readback from this evidence alone.
2. **Guest simulation/progress or visible-frame repetition not represented by presentation FPS.** High presentation rate with many short intervals and subjective slideshow reports warrants distinguishing simulation/visible change from present calls. There is no game-clock or visual-event timeline here. This is a measurement gap, not evidence of a confirmed simulation bug.
3. **GPU execution/resource-transfer demand or shared CPU/GPU power behavior.** Still possible, particularly for camera/scene changes, but invalid utilization, unverified MangoHud load and absent GPU timestamps prevent a GPU-bound conclusion. Cluster clock/power/temperature means do not show a simple power-collapse explanation. Cannot exclude memory bandwidth or synchronization involving GPU work.
4. **Shader/pipeline warm-up or other launch-to-launch cache/resource state.** User's successive-launch improvement is compatible with warm caches, but this run has inactive named pipeline workers. Cold synchronous/driver work, asset/resource initialization, shader compilation outside those workers or unrelated launch variability remain possible. No cache deletion, asset inspection or shader captures are justified.
5. **Thermal throttling or broad CPU scheduler starvation.** Not established: no throttle counters; edge temperature is stable; hot-thread preemption counts are actually lower in a bad region. CPU temperature is worth recording, but counts and high temperature alone do not identify a thermal/scheduling cause.

No model can assign whistles/close-ups/replays to timestamps without event evidence. No claimed optimization gain follows from these recordings.

## Next single most informative low-risk experiment

**One event-marked, otherwise unchanged capture that actually includes a user-recognized severe episode, with manual game-clock progression against a stopwatch.** Reuse application-layer frame logging and passive telemetry; do not change resolution, clocks, VSync, readback mode, caches or Steam/Proton configuration. Keep the same rendered AI matchup/camera where practical, warm up, and label onset/end plus whistle/close-up/replay and any focus change using numeric host-monotonic markers. Obtain approval for the new launch/capture as usual; none was performed here.

The distinguishing outcome is: (a) long present intervals with worker/GPU-clock changes, strengthening a presentation/handoff/workload lead; (b) unchanged present cadence but stalled normalized game-clock/visible progress, moving simulation or repeated-frame attribution ahead of rendering-throughput tuning; (c) first occurrence worse than the same event later with observed pipeline-worker activity, strengthening warm-up investigation. If no episode appears, record that outcome rather than relabel this run a successful reproduction. Manual markers have reaction/focus uncertainty; record that uncertainty and discard focus-induced disruption as gameplay evidence. For close-ups/replays where the match clock intentionally stops, explicitly label that state instead of calling it simulation slowdown.

This captures the missing phenomenon before recommending intrusive stack sampling or new stage instrumentation. It will narrow, rather than conclusively solve, CPU/GPU/synchronization attribution; the next instrumentation choice should depend on which outcome occurs.

## Artifacts, reusable analysis and reproducibility

Derived artifacts contain aggregate statistics only:

- [analysis.json](artifacts/011/analysis.json): identity hashes, global/cadence statistics, rolling windows, clusters/runs, thread aggregates, conditional alignment bins/sensitivity and phase summaries.
- [rolling_1s.csv](artifacts/011/rolling_1s.csv), [rolling_10s.csv](artifacts/011/rolling_10s.csv): full time-series summaries including tails/counts.
- [aligned_5s_assumed_midpoint.csv](artifacts/011/aligned_5s_assumed_midpoint.csv): explicit assumed-midpoint correlations; not exact synchronization.

Tabular time-series artifacts/table are used instead of installing plotting packages. No raw telemetry/frame rows, screenshots, shader data, binaries or assets are committed.

[analyze_recording.py](../tools/ally-profiler/analyze_recording.py) is an independent standard-library offline analyzer, not a change to `ally_profiler.py`. It requires explicit source paths and alignment endpoints, strict ms/ns MangoHud schema, rejects malformed inputs, retains missing sensor values, separates thread lifetimes, never uses GPU utilization and never reads live `/proc`/sysfs or launches anything. Outputs are confined to the source repository's `reports/artifacts/011`, reject symlinked output ancestry and use exclusive creation. Reproduction into the current checked-in artifact names intentionally fails rather than overwrites them; archive derived outputs separately before regeneration. The operator must supply the approved inputs; it does not discover game files.

Reproduction command (offline only; output names must be absent):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/analyze_recording.py \
 --frames "$HOME/nhl-ally-profiles/mangohud-pilot-20261020T161457Z/nhllegacy_2026-10-20_09-43-18.csv" \
 --comparison "$HOME/nhl-ally-profiles/mangohud-pilot-20261020T161457Z/nhllegacy_2026-10-20_09-31-34.csv" \
 --telemetry "$HOME/nhl-ally-profiles/20261020T164316Z-wi4msjfl/telemetry.jsonl" \
 --metadata "$HOME/nhl-ally-profiles/20261020T164316Z-wi4msjfl/metadata.json" \
 --summary "$HOME/nhl-ally-profiles/mangohud-pilot-20261020T161457Z/nhllegacy_2026-10-20_09-43-18_summary.csv" \
 --offset-min 1.631850 --offset-max 2.631850
```

## Files changed and validation

Added this report, four derived artifacts above, `tools/ally-profiler/analyze_recording.py` and its synthetic tests; updated report index only. No collector/application/SDK/renderer source changed. Raw input identities were checked, primary metrics independently cross-checked with the existing importer, Python syntax and documentation links validated, and staged-file allowlist/whitespace checked before commit.

**32 synthetic tests pass**: existing 22 plus ten for ms/ns cadence, malformed/missing/repeated headers/nonmonotonic time, threshold interpolation, window boundaries, consecutive versus gapped clusters, sensor errors/ambiguity, TID reuse/context-switch rates, offset selection and missing/constant correlation. An initial exact-zero floating-point test assertion failed at ~3.6e−15 and was corrected to numerical tolerance; production calculations were unchanged by that test correction. No real performance experiment was run. No raw files were changed/copied into Git, and no playable/system state was touched. Publish to origin's investigation branch only and stop for further instructions.
