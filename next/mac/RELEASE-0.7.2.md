# Native 0.7.2 / build 309 candidate

## Source and scope

- REUSE the entire shipped native 0.7.1 source at `84720ac1230456e99feffe324ce7beaa3d49c5ce` (`release/mac-0.7.1-308`), not trunk or the frozen factory native snapshot. Before edits, both `App/main.swift` and `Shared/Shared.swift` matched the saved live files byte-for-byte.
- EXTEND the production manifest validator and precomposed bootstrap classifier with **0.5.0**, retaining the previous admitted versions and every hash, disk identity, receipt, activation and unknown-version refusal.
- EXTEND the default image feed to `https://downloads.aiwizards.com/os/p2/latest.json`. No old feed is repointed by this source change.
- REUSE the shipped build 308 `GuestUpdate` payload **unchanged** in the successor native bundle. Factory 0.5.0 is separately downloaded for first install. This is not a guest software rebuild or an existing-used-disk upgrade test.
- NEW test-only production-Swift fixture and isolated final-release fresh-install driver. No new product implementation, core Hermes change or UI redesign.

## Updater integration disclosure

PR #40 head `b2bcc10a0d9b79977be3cee5507247062d7adeba` has an unrelated backup feature in its ancestry. A whole-branch merge was therefore **not** used. Its reviewable PR-only delta (parent of first PR commit `256bd9f72f7adf027c9fd4a4adeb0d5e202e20a2` through the head) was ported.

The updater implementation, new artifact validator, app launch coordination, feed signer and tests applied cleanly. Two textual conflicts in `Makefile` and `build.sh` were initially resolved narrowly against 0.7.1. **The successor now also restores the tested native backup/restore feature from `43c7d9b4677b3f54a17e5ca3ffb68ec549acbf6b`**, including its menu, busy-quit guard, contracts, tests, docs, guest snapshot helper and factory-admission fixture; the build source/framework lists are the union, not a replacement. Thus this is **not an unqualified clean merge** of PR #40. The earlier real-Mac 36-case updater receipt proves PR #40's original head, not this integrated successor binary.

## Verification

Run on a Mac worker:

```sh
python3 tests/test-mac-factory-admission.py --native
python3 tests/test-mac-fresh-install-qa.py
python3 tests/test-self-update-qa.py
make test-swift
make test-contracts
```

The native admission fixture extracts and executes the actual production validator, streaming digest function, bootstrap property, disk-identity receipt code and default feed property. It accepts 0.5.0, retains 0.4.1/0.4.0/0.3.0, refuses unknown versions/corrupt hashes/missing files/path traversal/empty file lists, and checks p2.

## Fresh final-artifact acceptance

`tools/fresh-install-release-qa.py` runs the unmodified release app, with QA hooks off, an initially empty isolated DataHome and only test-owned file-share/dev-shell configuration. It must download the split 0.5.0 factory from a loopback-only `/os/p2/latest.json`, record every part request, verify the installed manifest, prove the PID/command/DataHome ownership of its Host and reach both onboarding and agent health. It does not import a tar or patch a booted guest.

Unlike `qa-fresh.sh`, the driver refuses to proceed if any Wizard/Host or required port is already in use. It never wipes real data or kills a process by name. Because the production app's backend list lives in its persistent preference domain, the driver requires explicit `--allow-temporary-preferences-overlay`: it snapshots the original domain privately, overlays only test settings, and restores/verifies the original domain in `finally`. It also compares the real disk/config inode/size/mtime before and after. Before launching Wizard.app, it directly executes and retains that installed bundle's Host child with the isolated DataHome, avoiding LaunchServices' independent removable-volume privacy attribution on the headless worker. It requires Host status within 180 seconds, samples a blocked Host with a privacy-consent diagnostic, and verifies the app reuses that exact PID. Cleanup targets only retained owned children; any Host signal fallback is reported and fails acceptance. Interruption enters cleanup. No identity/signature is changed and no QA bundle is passed off as the release app. This launch context does not prove Finder consent; `hostLaunchedByHarness` is explicitly recorded.

Pass a new output path below an explicit `--work-root`. Never use the owner's live DataHome. A platform consent denial or locked desktop is an honest failed/blocked acceptance, not a reason to weaken TCC or modify the binary. Retain the private preference backup until restoration is verified; do not publish it.

## Release status

Build **309** is reserved by this candidate after a read-only R2 `mac/` inventory showed only released builds 306–308 and the release plan had no later reservation. Re-read reservations immediately before a parent-owned build/promotion. No DMG, ZIP, feed publication, appcast change, merge, Developer ID signature or notarization is claimed by this source PR. The build and exact-artifact fresh-install runs are separate ordered worker jobs.
