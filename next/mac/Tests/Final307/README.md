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
7. Separately direct-launch the exact307 Host with no OS, confirm `notInstalled`, send the production `HostControl.send` body through real DistributedNotificationCenter and require Host exit. **This does not certify the production NSWorkspace launch path.** Only if this new external-IO/IPC witness succeeds, remove the dummy OS from the isolated data home, relaunch the exact307 App, and make one bounded `update-host-start` call into its production `HostControl.ensureRunning`/NSWorkspace path. Require exact Host PID/build/data home, real external-volume status and clean IPC exit. No VM is started. If the new witness fails, do not retry the previously stalled transport.
8. Restore the shared MVP preferences semantically, stop only owned no-VM processes, retain the foreign Host, and report exact cleanup. Every wait is bounded. Failed assertions exit nonzero even when packaging succeeded.

The job deliberately leaves `readyForPublication=false` and computes `readyForParentReview` from executed gates and cleanup. Parent must reconcile the distinct production NSWorkspace result with the already accepted real headless migration. The user prohibited unlock/screensharing requests and security workarounds. Direct inherited-worker Host success provides new diagnostic evidence, not a renamed pass for the production path; the conditional production launch is separately reported.

## Installed307 recovery mode

`continueInstalled: true` preserves the already Sparkle-replaced307 app and its
failed transaction. The private spec pins the prior report, transaction and
accepted AppKit fixture hashes. Reuse those and the accepted package; do not
recompile, remigrate, or rebuild. Capture/AX consent and direct Host IPC run
**before** any retry of the blocked relaunch, so one blocker does not erase the
remaining evidence. No-VM Host homes need empty `os`, `logs`, and `Files` folders:
`open(os/disk-owner.lock, O_CREAT)` failing ENOENT is not proof of a foreign owner.
Boot material (including dangling symlinks) is forbidden before Host launch.

After direct native entry, one bounded LaunchServices launch tests app-attributed
external IO with a new, scoped intervention: a bounded AX helper can press the
single `Allow` button **only within a window naming the exact owned QA app and
asking for removable-volume access**, after verifying the requesting PID and
executable hash. It requires a private-spec prior-authorization reference and
`allowOwnedRemovable: true`; it does not authorize anything else. Default helper
mode is read-only. No prompt or an inaccessible console is a failed gate, never
permission to change macOS settings. AX action success alone is not an IO pass.

Only fresh app-attributed QA IO permits one real Sparkle retry, in a **new**
owned306 app/data home. Require an actual Sparkle-launched307 live PID, matching
App/Host bytes, and a real `native-activated` transaction. Direct307 and manual
LaunchServices success are explicitly not Sparkle success. The old installed307,
prior report and original failed journal remain hash-pinned before/after. Neither
production NSWorkspace Host transport nor packaged relaunch inherits a pass from
the direct entry. A SIGTERM/SIGINT cleanup hook restores preferences and stops
only owned no-VM processes; hard SIGKILL still requires parent cleanup inspection.

## Fast checks

`PYTHONDONTWRITEBYTECODE=1 python3 next/mac/Tests/Final307/test_contract.py -v`

These verify harness contracts only. A staged or type-checked fixture is not native acceptance. The private release handoff names the actual spec, hashes and Thales argv; no owner-specific deployment paths or signing material belong in this repository.
