# Investigation and task reports

This directory is the permanent record of substantial investigation and implementation work.

For every future substantial task, create a new sequentially numbered Markdown report (`002-<topic>.md`, `003-<topic>.md`, and so on) and update this index. Each report must document its objective, findings, files changed, validation performed, limitations, and recommended next steps. Distinguish verified source behavior, historical measurements, and hypotheses requiring runtime evidence.

| Report | Objective | Status |
| --- | --- | --- |
| [001 — Initial performance investigation](001-initial-performance-investigation.md) | Investigate v0.6.0 rendering, synchronization, timing, and build constraints for an ASUS ROG Ally Z2A running Bazzite through Proton. | Source investigation complete; implementation and runtime profiling await instructions. |
| [002 — Ally profiling and Linux feasibility](002-ally-profiling-and-linux-feasibility.md) | Inventory existing profiling tools, design a gameplay benchmark, and assess native Linux support at the pinned SDK revision. | Documentation investigation complete; profiling and implementation await instructions. |
| [003 — Ally profiler implementation](003-ally-profiler-implementation.md) | Build read-only telemetry collection and explicit-provenance frame-log analysis with synthetic validation and separate Desktop/Gaming workflows. | Implemented; 16 synthetic tests pass. Gameplay collection and configuration changes await approval. |
| [004 — Bazzite home-path fix](004-bazzite-home-path-fix.md) | Support the trusted Bazzite home alias while preserving dedicated output-path protections. | Fixed; complete suite of 20 synthetic tests passes. No game execution. |
| [005 — Simulation versus live bottleneck investigation](005-simulation-vs-live-bottleneck-investigation.md) | Analyze two local captures, trace SDK thread/pacing behavior, reject invalid GPU utilization, and design a Desktop frame-log comparison. | Captures verified; bottleneck unconfirmed. Narrow profiler fix passes 22 synthetic tests; next gameplay pilot awaits approval. |
| [006 — Unleashed Recompiled architecture comparison](006-sonic-unleashed-architecture-comparison.md) | Compare pinned CPU/runtime/renderer sources and rank transferable techniques; clarify both prior workloads were rendered matches. | Research complete; frame-time baseline remains prerequisite. No source or runtime changes. |
