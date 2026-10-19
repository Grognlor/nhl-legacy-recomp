# 004 — Bazzite home-path fix

## Objective

Fix profiler startup on Bazzite 44 without weakening the dedicated output-directory boundary. User-verified environment: `HOME=/home/cody`, `/home -> var/home`, and canonical home `/var/home/cody`. The profiler reported `Error: Output base must not contain symlinks` for its normal `~/nhl-ally-profiles/` location.

Read [report 003](003-ally-profiler-implementation.md) and the [tool runbook](../tools/ally-profiler/README.md) before editing. Branch: `perf/ally-investigation`; starting commit: `ee19c73b70b7ec4b589ce3c7512697c32f85ab6c`. Date: 2026-10-19.

## Finding and implementation

Previously, `BASE` was constructed directly from `Path.home()`. `new_run()` rejected a path when `base.resolve() != base.absolute()`. That checked the entire home ancestry as well as the dedicated output directory, so a legitimate Bazzite home alias failed validation.

The fix in [`ally_profiler.py`](../tools/ally-profiler/ally_profiler.py) introduces `default_output_base()`:

1. Obtain the trusted home root from `Path.home()`.
2. Reject relative paths and explicit `..` traversal.
3. Resolve the home root strictly, requiring an existing directory other than filesystem root.
4. Append the fixed `nhl-ally-profiles` component **after** resolving home.
5. Pass that canonical base through the existing output symlink check and unique-directory creation.

`new_run()` now defaults to that helper. Both collection and CSV analysis use it. Explicit internal paths used by synthetic tests remain supported, with added absolute-path and traversal checks; the CLI still exposes no output-directory override. The canonical output path can now be `/var/home/cody/nhl-ally-profiles/` while remaining accessible through `~/nhl-ally-profiles/`.

Only the trusted home ancestry is allowed to resolve through symlinks. The dedicated output base is not blindly canonicalized: output-directory symlinks, dangling links and nested symlinks on a traversed output path still fail. Existing `tempfile.mkdtemp` uniqueness/private run directories and exclusive `open('x')` file creation are unchanged. No telemetry collection, CSV statistics, or game behavior was changed.

## Regression tests and validation

Added four synthetic regression tests in [`test_ally_profiler.py`](../tools/ally-profiler/test_ally_profiler.py):

- A temporary `/home -> var/home` layout creates two distinct run directories beneath the canonical home and preserves exclusive file creation.
- Output-base symlinks to an unintended directory and a nonexistent target are rejected through the Bazzite home alias; the targets receive no output.
- Nested output symlinks, `..` traversal and relative output paths are rejected.
- Filesystem-root, relative, traversing, missing and non-directory home roots fail before output creation.

Updated the existing mocked collector test to inject the default-base helper rather than the removed `BASE` constant. All earlier tests remain in the suite, including sensor permissions, CPU identities, CSV errors, numeric summaries and output protections.

Validation commands:

```bash
cd "$HOME/Projects/nhl-legacy-recomp" || exit 1
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/ally_profiler.py self-test
PYTHONDONTWRITEBYTECODE=1 python3 tools/ally-profiler/ally_profiler.py dry-run
python3 - <<'PY'
from pathlib import Path
for path in Path('tools/ally-profiler').glob('*.py'):
    compile(path.read_text(), str(path), 'exec')
    print('Syntax OK:', path)
PY
git diff --check
```

Results: **20 tests pass** in the complete synthetic suite and its dry-run alias; both Python files pass syntax checks. Local Markdown links and the staged-file allowlist were checked before commit. All output-creation validation uses temporary fixtures; no real home log directory or game telemetry is needed to reproduce the bug and fix.

## Files changed

- `tools/ally-profiler/ally_profiler.py` — canonical trusted home helper and retained output checks.
- `tools/ally-profiler/test_ally_profiler.py` — four regression tests and collector fixture adjustment.
- `tools/ally-profiler/README.md` — explain supported home alias and retained output protections.
- `reports/004-bazzite-home-path-fix.md` — this report.
- `reports/README.md` — index entry.

## Limitations and next steps

Home is a trusted root supplied by the execution environment; this does not authenticate an attacker-controlled `HOME`. The existing path-based checks are not redesigned into protection against concurrent filesystem replacement. This small compatibility fix preserves the prior creation model and safety checks rather than adding a new filesystem security architecture.

No game was launched or built. No playable installation, Steam configuration, Proton prefix, system settings, assets or application/SDK sources were modified. No packages were installed. No real-game performance results are claimed.

Next: the user can rerun the documented profiler workflow when gameplay testing is authorized. A canonical `/var/home/...` output path is expected on Bazzite. Wait for further instructions before running the game or changing configuration.
