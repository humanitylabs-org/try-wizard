# Legacy 0.6.1 bootstrap: admission stop checkpoint

**Not implemented / not release acceptance.** This branch adds a bounded diagnostic
and regression checks, not build307 and not a migration that bypasses admission.
The frozen public306 production sources and payload are unchanged.

## Exact obstruction in frozen source

1. `App/WizardUpdater.swift:179–203` recovers only an existing DataHome-bound
   `installing` transaction. Replacing the 0.6.1 DMG does not create one. An empty
   transaction therefore returns before activating the bundled guest payload.
2. `Shared/Shared.swift:19–30` enables the payload only for a validated,
   DataHome-bound `guest-activating` transaction. Writing that transaction would
   enable the private vsock transport, but would **not** establish idle admission.
3. `Host/main.swift:481–501` reacquires the maintenance lease before running the
   fixed migration. `Shared/UpdateContract.swift:125–147` requires a real HTTP201
   and `ok=true` from `/wizard/v1/maintenance`. The original guest has no such
   route. HTTP404, a health sample or user consent cannot substitute for it.
4. `Host/main.swift:523–524` permits an already stopped VM to stop without a
   lease, but the next ordinary maintenance boot starts the original services.
   It subsequently hits the missing-lease problem in step3. A stopped-disk
   snapshot alone does not fence agent launch during that boot.
5. `next/guest/STACK-UPGRADE.md` is a manually supervised maintenance recipe, not
   an atomic bootstrap-admission protocol. The previous manual migration primed
   the guest before private305→306 acceptance. Repeating it from a native button
   would automate the same unsafe missing prerequisite, not close the gap.

The packaged newer managed-maintenance implementation additionally rejects a
running unmanaged stock engine. Installing just its HTTP endpoint onto the old
service would not safely admit that runtime. Launch admission must be established
before *any* legacy engine can start, or the old live runtime must provide an
independently verified all-runtime retirement protocol.

## Smallest route worth implementing next

A dedicated **cold bootstrap**, not an HTTP404 fallback:

- Before `controller.begin()` starts the selected local VM, detect an unprimed
  disk and obtain explicit native consent. Refuse another Host, capture or active
  work. Retain DataHome, backend selection and the files-folder record.
- Hold a single-owner disk lock, take the existing stopped-disk APFS snapshot,
  and durably record the authenticated app/payload, disk identity and phase.
- Boot the same disk in a dedicated maintenance mode that cannot start the old
  Docker/user engines. The existing private vsock transport can carry a fixed
  helper. **Unresolved safety seam:** prove startup inhibition remains effective
  while the migration loads Docker images/reconfigures Runtipi, until the new
  managed admission fence is installed. Merely masking Docker at initial boot is
  insufficient because starting it later restores old containers.
- Once that fence exists, run the sealed migration, reuse normal activation,
  stopped-disk rollback and post-release health verification. Never mutate the
  existing factory archive or core Hermes.
- Only then build307 and run the real original0.6.1/guest0.3.0→307 success,
  post-apply rollback, active/capture refusal and repeat-launch no-op matrix.
  Parent owns review and promotion; no successor feed is published here.

## Runnable focused checks

`Tests/LegacyAdmission/main.swift` links the unchanged production
`Shared/UpdateContract.swift` and intercepts only URL transport. It checks legacy
missing-route, busy/unknown/malformed responses and modern success, plus active,
queued, unknown-liveness and known-idle health. These are transport-fixture
regressions, not evidence that the original guest can migrate.

`Tests/legacy061_probe.py` boots only an APFS clone of the original used baseline
with the original0.6.1 app, gracefully stops it, and launches exact public306
against that same unprimed clone. It does not enable dev-shell, seed a transaction,
POST maintenance, invoke the migration or use private305. It records the missing
runtime-activity route and absent transaction; this deliberately reproduces the
blocker. It restores defaults, verifies original native bytes/baseline stat, and
refuses foreign Hosts/occupied ports/locked console. It is **not** a full account
or chat preservation test and cannot certify build307 acceptance.

`Tests/run_legacy061_checks.py --spec <absolute-spec.json>` is the durable-worker
entrypoint. Its spec requires `source`, `evidenceRoot`, `baselineDisk`, `bootDir`,
`oldApp`, `oldLaunchApp`, `newApp`, and `quitHelper`. `oldLaunchApp` is a new owned
Applications bundle, removed after graceful cleanup. All work/evidence is on ThalesMedia;
submit through `wizard_heavy_submit`, never run sustained checks on the control
host. It compiles/runs the production admission regression and existing isolated
activation/rollback check before the VM diagnostic. It does not acquire a second
worker lock: the durable worker owns the lease. A successful diagnostic still
writes `upgradeAccepted:false`.

Retain the already accepted exact-e4 modern updater/rollback/native-control and
capture lifecycle evidence. Physical-microphone speech and end-to-end meeting
upload remain untested; this diagnostic does not change those limits.
