# Final307 bounded continuation (QA only)

This harness packages an already-built, exact `c7952d68e6a61da74b1e26485293cb7b5d881c7b` native307. It never builds a guest, recompiles the native product, reruns the accepted real-disk migration, publishes, or submits a worker job.

Run `run.py --spec /absolute/private/spec.json --preflight-only` for read-only candidate/ref/feed checks. Parent submits the normal command to the durable Thales worker. `workerLease: inherited` is an assertion that the parent worker owns the shared lease, not a second lock request. Keep all data under `/Volumes/ThalesMedia`; the one isolated native app is under `/Applications`.

## Scope and evidence layers

1. Verify exact candidate App/Host hashes, signed bundle, source pins, accepted 17-gate headless report hash and cleanup. Refuse build307 if feed already advertises it or either immutable object exists; non-404 object probes also refuse.
2. Compile only a small test fixture against the **entire unchanged production WizardUpdater.swift**. Its collaborators are explicit adapters. Exercise real AppKit `NSAlert`/`NSButton` cancellation, positive consent, post-consent activity race and capture/foreign-Host policy. This is not a physical user or installed-app test. Real migration is forbidden in adapters.
3. Clone the exact candidate without re-signing or rebuilding. Generate signed Sparkle archive/feed and DMG. Verify signatures, DMG integrity, mounted App/Host executable parity. Stage exactly three public files; private receipt and fixture material remain outside the public directory. The approved publisher accepts a **flat** input directory and adds `mac/307/` itself.
4. Use one direct-launch App306 in an isolated no-VM data home, a loopback backend and a signed private appcast referencing the **same ZIP**. Exercise real Sparkle306→307 replacement and relaunch; require build, changed PID, transaction and exact executable hashes.
5. Attempt exact307 real recorder lifecycle into a local discard-only fixture, then test the changed legacy-admission refusal while capture is active. No TCC writes, unlock requests, permission resets, or security weakening. Failure remains a failed gate; historical306 cannot masquerade as exact307 capture.
6. Exercise exact installed307 native consent through already-granted AX, using deliberately invalid tiny boot files: cancellation and authenticated rejection with unchanged dummy disk. There is no VM or real-disk migration in this path.
7. Separately direct-launch the exact307 Host with no OS, confirm `notInstalled`, send the production `HostControl.send` body through real DistributedNotificationCenter and require Host exit. **This does not certify the production NSWorkspace launch path**; the known locked-console external-file transport is not retried.
8. Restore the shared MVP preferences semantically, stop only owned no-VM processes, retain the foreign Host, and report exact cleanup. Every wait is bounded. Failed assertions exit nonzero even when packaging succeeded.

The job deliberately leaves `readyForPublication=false`: parent must reconcile the still-distinct production NSWorkspace Host launch gate. The user prohibited unlock/screensharing requests and security workarounds. A direct inherited-worker Host success would provide new diagnostic evidence, not a renamed pass for that production path.

## Fast checks

`PYTHONDONTWRITEBYTECODE=1 python3 next/mac/Tests/Final307/test_contract.py -v`

These verify harness contracts only. A staged or type-checked fixture is not native acceptance. The private release handoff names the actual spec, hashes and Thales argv; no owner-specific deployment paths or signing material belong in this repository.
