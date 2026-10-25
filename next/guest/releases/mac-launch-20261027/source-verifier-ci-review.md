# Source verifier v5: CI environment repair and source blocker

## Outcome

Environmental failures are resolved without changing frozen source trees or tests.
Job 01 is **not green**: optional round-trip YAML coverage exposes one genuine WAM
source bug affecting four existing test cases at commit
`7a1f0fdc3507e69f1144424c6d3dc0f566a46fd7`. Do not manufacture a pass by removing
ruamel.yaml or changing test selection. Source fixes and repinning need the release
owner; this change only repairs the verifier.

## Environment contract

Read the frozen repositories' workflows, notably Service `quality.yml`, WAM
`test.yml`, and UX `responsive-features.yml`.

- Keep the existing digest-pinned Node 22/bookworm image (observed Node 22.23.4).
- Supplement `/usr/local` from official Python 3.11/bookworm, index digest
  `sha256:18d373e126e39c29c6d38e71e2f19ca66636568318fc95c7849c462b7f9d3d64`,
  anonymously mirrored and arm64-selected. Observed Python 3.11.17, matching WAM
  setup-python's 3.11 line, including tar extraction filters absent from 3.11.2.
- Use unprivileged uid 1000 (`node`) for ordinary Service/UX/WAM suites, with
  CI-like sudo and the existing Docker group. Keep managed root recovery as root.
- Own copied checkouts as the CI user; create actual commits and configure Git
  identity at system scope because fixtures replace HOME. Avoid broad safe.directory.
- Install system PyYAML for tests whose deliberately restricted PATH selects
  `/usr/bin/python3`, not just the venv interpreter.
- Use ordinary `npm ci`, fetch the exact archived Service rollback object specified
  by CI, set `WIZARD_IMPORT_PYTHON` and `REQUIRE_ROLLBACK_REHEARSAL=1`, and include
  all components of Service's npm test script plus the original maintenance suite.
- Retain full WAM pytest and UX node globs, with standalone WAM portability and
  runtipi-open checks. Install pinned optional ruamel/crypto backends to exercise
  existing tests rather than leave them dependency-skipped. Debian restic remains
  below the tests' minimum and its existing skips remain visible.
- No daemon socket, credentials, host services, test edits, deselection or assertion
  changes. The original final trees remain read-only; all test changes are disposable.

## Direct Thales results

Evidence is in the freeze's `source-environment-diagnostics/`; this is direct
Linux-container evidence, not a new durable job-01 receipt. No heavy job was submitted.

| Suite | Result |
| --- | --- |
| Service Vitest | 1322 passed, 110 files, zero skipped |
| Service maintenance/lifecycle/adapters | 22 passed |
| Service managed root recovery | 5 passed |
| Service importer package runner | 88 run, 1 existing skip |
| Service package node unit checks | 20 passed, 1 existing skip |
| Service chat photo reader | 6 passed |
| Service standard chats relay | 7 passed |
| Service agent parity | 146 passed |
| UX node unit checks | 776 passed |
| WAM full pytest | 1110 passed, 4 failed, 16 existing skips, 7 subtests passed (203.06 s) |
| WAM original failing files rerun | 151 passed, 7 subtests passed |
| WAM portability standalone | 5 passed |
| WAM runtipi-open node | 4 passed |
| WAM isolated builder bundle module | 27 passed, same 4 failed (2.03 s) |
| Verifier control-plane regression contracts | 6 passed |

The original Service sandboxed MEDIA failure was root bypassing mode 000; it now
passes unprivileged. All original WAM failures (Docker group, old tarfile API,
Git ownership, root-vs-user behavior, missing system YAML) pass in the corrected
container.

## Genuine source defect (do not patch frozen sources)

`wizard-cli/wizard:1034-1038` does:

```python
local = Path(ns.plugin_source or '').expanduser()
if local.is_dir():
    if not (local / '__init__.py').is_file():
        raise Fail('usage', 'local plugin source has no __init__.py')
```

With the default `plugin_source=None`, `Path('')` means the current directory.
It is a directory, so default remote-plugin installation is incorrectly treated
as a local plugin, then rejected because the working directory has no plugin
`__init__.py`. This is a production `wizard link` defect, not container semantics.
Installing ruamel.yaml exposes previously skipped tests; the failure also
reproduces with only the existing builder-bundle test module.

Affected existing tests in `tests/test_builder_bundle.py`:

- `test_link_repeat_refresh_unlink_and_owner_edits`
- `test_modified_plugin_refresh_is_refused`
- `test_legacy_link_migrates_explicit_plugin_pin[True]`
- `test_legacy_link_migrates_explicit_plugin_pin[False]`

Proposed source fix: construct a local Path only for an explicitly supplied,
nonempty `ns.plugin_source`; otherwise take the existing `run_hermes` remote
installation branch. Keep local-plugin validation, rollback and all assertions.
No such source fix was made here. The release owner must authorize a source
change/new pin before job 01 can honestly pass with this coverage.
