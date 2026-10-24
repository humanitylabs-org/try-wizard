# Update architecture v2 — source verification only

## Base comparison

Base commit: `84720ac1230456e99feffe324ce7beaa3d49c5ce`.

- Base required command `python3 -m unittest discover -s next/mac/Tests -p 'test_*.py'`: **22 tests, 1 error**. The pre-existing direct `test_os_manifest_contract.py` CLI ran argparse on import. It requires a work-directory argument and macOS xcrun. Other base discovery tests passed.
- That CLI is now import-safe: discovery skips it; direct invocation still generates/compiles/runs actual production Swift on a Mac. `--emit-only` generates the actual Swift fixture on Linux without claiming compilation.
- Additional base guest discovery under bare Python: **30 tests, 3 errors**: missing PyYAML, hard-coded macOS `/opt/homebrew/bin/nginx`, and missing test-relative `hermes_brain.py`. The same errors occurred before these changes. Do not present them as new update-architecture failures.

## Source checks exercised

- Required Mac Python discovery after all source changes: **44 tests, OK, 1 intentional Mac-only skip** (43 executed passes).
- Cold maintenance/config tests with an existing PyYAML-capable interpreter: **15 tests, OK**. The cleanup-policy test was deliberately tightened to reject unnamed/third-party volumes/networks.
- New ABI cases: exact legacy inference 0.3.0 -> 0, 0.4.0/0.4.1 -> 1; explicit ABI with arbitrary display version; unknown, boolean, string, float and negative ABI refusal; payload ABI range refusal; unchanged installer integrity loop compared byte-for-byte to the base.
- New fresh cases: equal payloadID skips, missing/different IDs apply, journal before clone, clone before compare, reuse of activation/rollback, visible installer failure path, payload identity included in release metadata.
- New feed cases: numeric newest-compatible selection, unknown-only index refusal, required immutable absolute HTTPS parts/sizes/digests, absent-only fallback, shared resolution for size/download/manual browser paths.
- New ownership/app cases: foreign owner refusal, downgrade refusal source gate, app container/image/config/mount invariants, stopped-app refusal, running-app resumption, restricted cold authorization, persistent App Manager/Runtipi state fingerprints, stock Hermes managed-install configuration marker/environment (including future profiles). The real applier preflight prefix is executed against disposable fixture paths and an empty read-only Docker inventory; this caught and fixed guard-initialization ordering before VM execution.
- Matrix planning/guards: four N-1/N app x image combinations, every supplied published DMG, aged disk, interruption and rollback; nine planned rows with the two legacy DMGs. Actual execution requires a worker-locked disposable Mac rig and concrete retained drivers/checkpoints.
- `bash -n` for modified packaging scripts; Python compile checks for changed guest policy/applier helpers; `git diff --check`: passed.
- Tree-sitter Swift parsing of all ten changed Swift source/fixture files: no syntax errors (same parser had none on their base versions). **This is not Swift compilation or typechecking.**

## Explicitly unverified / pending Thales

No Swift compiler, Sparkle runtime, macOS app interaction, APFS clone execution, real VM, Docker daemon, factory boot, live feed change, signed artifact build or publication was performed. No Thales lock was acquired and no heavy job was submitted.

Run the real matrix only after staging signed app/image fixtures and the concrete aged/fault rig adapters described in `update-arch-v2-matrix.md`. N-1 Host inventory/bootstrap admission, fresh equal/different payload integration, every legacy published feed, modern repeat cold apply, aged user app restoration, crash/rollback, foreign-owner UI and Sparkle-before-download all remain Mac acceptance gates. Keep the PR draft; source contracts alone do not establish release safety.
