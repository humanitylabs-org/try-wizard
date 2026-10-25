# Issue #18 — self-update review and evidence ledger

## Scope and status

Native Mac updater only, for the unsigned/ad-hoc launch path. No merge, release,
tag, public appcast edit, production signing, live install replacement, or guest
rebuild is authorized by this PR. QA uses disposable Ed25519 keys and ad-hoc
Apple signatures; it is not Developer ID/notarization evidence.

Historical **r4 passed 19/19** at `80396517efbfb64c712c47937e9d06e219ea98cc`
(Thales job `heavy_f07571cd80204a03a8a3b2bd17874a26`). That does **not** validate
this revision. The independent Opus review of that head returned **CHANGES
REQUIRED**. This revision needs a new independent review and a complete r5 run.

## Pinned Sparkle source: important correction to the requested premise

Inspected tag **2.10.0**, commit `eef1a539a373c1f1a320624b1130fc5de7b2e100`.
An installer that completed stage 1 **can install on host exit even if the app
never explicitly resumed stage 2**:

- [`Autoupdate/AppInstaller.m:404–410`](https://github.com/sparkle-project/Sparkle/blob/eef1a539a373c1f1a320624b1130fc5de7b2e100/Autoupdate/AppInstaller.m#L404-L410)
  observes host termination and calls `finishInstallationAfterHostTermination`.
- [`AppInstaller.m:731–743`](https://github.com/sparkle-project/Sparkle/blob/eef1a539a373c1f1a320624b1130fc5de7b2e100/Autoupdate/AppInstaller.m#L731-L743)
  marks stage 1 complete and also takes this path if the host already died.
- [`AppInstaller.m:789–800`](https://github.com/sparkle-project/Sparkle/blob/eef1a539a373c1f1a320624b1130fc5de7b2e100/Autoupdate/AppInstaller.m#L789-L800)
  runs stage 2 itself when necessary, then performs final installation.
- [`AppInstaller.m:692`](https://github.com/sparkle-project/Sparkle/blob/eef1a539a373c1f1a320624b1130fc5de7b2e100/Autoupdate/AppInstaller.m#L690-L692)
  sets `_willCompleteInstallation` before stage 1; the connection-invalidation
  cleanup at lines 204–210 is therefore not an install-on-crash guarantee.

Consequently, “SIGKILL an actual Sparkle stage-1 installer and require unchanged
build” is not a valid regression expectation for this pinned engine. Nor is
“terminate after 45 seconds while such an unadmitted installer is still armed”
a safe fix. This premise is **refuted**, not waved through as a passing test.

**Source fix:** ordinary Ready now means a private SHA-checked archive with a
signed-feed item, not a Sparkle installer. Only explicit Update and restart,
after the existing Host/capture/lease admission, calls Sparkle `.install` and
allows extraction/stage 1. Sparkle's ready callback installs immediately only
for that admitted restart; an unexpected unadmitted stage is discarded. Archive
Ed25519 verification still runs before extraction. SHA-256 is an early-failure
check, not a replacement integrity gate.

## Opus findings and responses

1. **P1 resumed stage admission:** fixed for newly created stages by moving
   Sparkle installer creation behind restart admission. Existing `.downloaded`
   and `.installing` callbacks still fail closed through `.skip`, never `.install`.
   r5 kills the actual app at its new Ready, relaunches, requires `discarded`, no
   owned helper, unchanged build, stale-file removal and a fresh reoffer. A
   fabricated legacy stage-1 SIGKILL/unchanged-build pass is explicitly not
   claimed; pinned Sparkle makes that expectation invalid as documented above.
2. **P2 indefinite Quit / shutdown:** visible `quit-deferring`, a real 45-second
   deadline (`quit-timeout`), and `quit-dismissed` phase history. Production
   pre-restart staging has no installer to finish on this bounded exit.
   `NSWorkspace.willPowerOffNotification` requests teardown and bypasses ordinary
   Quit deferral. r5 tests missing-dismissal acknowledgement at the real deadline
   and the workspace power-off notification, not an actual machine shutdown.
   The older real extraction-Quit case remains, deliberately enabled only in QA;
   it must show deferral then dismissal, no app/copied helper, and unchanged build
   after another 30 seconds. Do not ship if that native assertion fails.
3. **P2 large downloads / disk:** removed the app's 3600-second resource deadline;
   retain URLSession's platform resource default and a 60-second request stall
   timeout. The signed size cap is unchanged. Before creating a download, free
   space must be known and at least three times the signed archive length.
   Insufficient/unknown space fails closed with a clear message. Swift tests
   exercise the threshold, unknown capacity, zero and multiplication overflow;
   r5 exercises the real precheck failure. A real multi-hour WAN transfer has not
   been run and is not claimed.
4. **P2 negative oracles:** `ui.json.errors` records the NSError domain/code
   chain. Bad archive Ed25519 must include `SUSparkleErrorDomain/3002` with outer
   `4005`; invalid signed feeds require outer `1000` plus `3002`. See pinned
   `Sparkle/SUErrors.h:40,56,64`, `SUAppcastDriver.m:133–166` and
   `SPUInstallerDriver.m:90–104`. r5 adds feed edited after signing, wrong-key
   signed feed, signed downgrade, oversize response and 302-to-HTTP redirect.
   Archive signature validation now occurs after explicit restart admission,
   rather than incorrectly equating private Ready with Sparkle stage-1 Ready.
5. **P2 QA identity / late installs:** assert actual `git rev-parse HEAD` equals
   `--source-head` and an empty porcelain status, recording both at start and end.
   Log full `ps` at Ready. Cleanup recognizes the copied Sparkle progress Updater
   by its exact host-bundle argument; it never signals a different installation.
   Extraction-Quit also observes any Autoupdate for the bundle id, and checks
   the installed version again after 30 seconds. No previous assertion removed.
6. **P3 persistent skip restoration:** cancellation snapshots are written to
   `WizardUpdate.dir` before `.skip`, restored on startup as well as dismissal,
   and removed after restoration. r5 includes recovery from a persisted snapshot
   with a previous older skipped version.
7. **P3 abandoned files:** startup sweeps only `download-*` in the private update
   directory. Swift tests preserve unrelated transaction files; crash/relaunch
   QA checks the actual discarded staging directory.
8. **P3 production QA exposure:** loopback HTTP artifact/feed admission and the
   distributed-notification QA hooks require compile-time `WIZARD_UPDATE_QA`.
   The harness builds with that flag; normal builds do not. The fallback URL is
   `wizard-unverified-update-refused:archive`, not routable loopback HTTP. Native
   unit tests compile both flag configurations and assert their differing policy.
9. **P3 wording:** Ed25519 is the integrity gate. SHA-256 is an early-failure check
   over raw ZIP bytes; it is not Mach-O canonicalization or substitute signing.
10. **P3 item binding:** bind relay URL to both version and original archive URL;
    reject delta-bearing items and delta requests rather than exposing unrelated
    verified bytes to a changed/fallback item.
11. **P3 relay lifetime:** remove cancelled/failed NWConnections from the owned
    list; four is a concurrent cap, not a lifetime request limit. The native
    fixture requires twelve successive real relay downloads.
12. **P3 QA hygiene:** removed dead `SUValidateBeforeExtraction` (the real
    `SUVerifyUpdateBeforeExtraction` remains). Finally removes disposable signing
    keys and backup preference plists. A distinct QA bundle id is deferred:
    App/Host identifiers and notification/lease paths are coupled; changing them
    is not a cheap, safe test-only edit. The harness retains refusal to run beside
    any active Wizard/Host, exact preference restoration and isolated local data.

## Evidence and remaining gates

- Linux: focused Python tests, Python compilation and shell syntax/whitespace
  checks run locally. `make test-contracts` is invoked locally but its existing
  `test_cold_boot_wait.py` requires Darwin. Supplemental component runs also
  identify the existing network-identity fixture dependency on `/usr/bin/lockf`,
  absent on Linux; the r5 worker must run the full target on Thales, not bypass it.
- Both production and QA complete native source-set Swift typechecks are run
  directly on Thales only as quick checks, without taking shared build locks.
  The r5 receipt binds their logs to the final source manifest/head.
- Full r5 is staged under the operator's `$QA_ROOT` (`mac-self-update-launch/r5`),
  with a clean Git source checkout, tracked-file SHA-256 manifest and runner. The
  worker runs `make test-contracts` then the full app-only two-hop harness.
- A current-head pass requires `evidence/complete.json` with `pass: true`, actual
  source identity, every result, three build/signing reports, both replacements,
  rejection/quit/crash cases, preference restoration and no forced cleanup.
  **Staging or a typecheck is not native runtime acceptance.**

The r4 filesystem issue remains relevant: only the small disposable installed
app and DataHome live in a unique local Library/Caches directory. Builds, feeds
and evidence stay under the external QA root. Native launch uses `open` /
LaunchServices. This is not removable-volume consent, a real Host/guest restart,
or daily-install upgrade coverage. Guest/update regression, CI, independent
follow-up review and James's clean-install acceptance remain merge gates.

## Public 306 versus testers 307

Repository release notes distinguish the unchanged **public 306** from **307
candidates**: `Tests/HeadlessCold/README.md:15–19` pins production source
`c7952d68e6a61da74b1e26485293cb7b5d881c7b` for 307 while leaving public 306
untouched. The owner reports testers already on 307; that is not a claim that
public 306 and the tester installation are the same. This PR publishes neither.
The first bootstrap containing these fixes must have an increasing build newer
than every tester's installed build (at least >307); a subsequent SHA-bearing,
Ed25519-signed feed/archive exercises its successor. Existing testers do not gain
this new updater merely because the PR merges. Feed publication/readback and any
manual bootstrap are separate approved release operations; re-check the actual
public/tester builds at that time.
