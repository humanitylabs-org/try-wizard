# Legacy 0.6.1 cold-bootstrap candidate

**Production source implemented; native compilation and VM acceptance pending.**
This replaces the earlier diagnostic-only checkpoint. It does not claim build307
exists yet, change public306/factory0.4.0, or grant successor publication authority.
Parent retains independent review, actual VM acceptance and final publication.

## Implemented path

- `WizardWindowController.begin()` gates every selected-local boot (including a
  switch from remote) through native one-time upgrade consent. Remote selection
  is untouched. Existing/foreign Host, native capture or unknown boot hashes defer.
- The App takes a cooperating owner lock, validates the installed app/payload and
  original kernel/initrd pins, clones the stopped disk, and writes a DataHome,
  release and disk-inode-bound transaction. The Host takes the same disk-owner
  lock for its lifetime. No HTTP404-to-idle fallback was introduced.
- The Host boots `init=/bin/sh`, not the old systemd default target. Its private
  serial input invokes the authenticated read-only payload as PID1. Until that
  helper succeeds, no systemd, Docker, user manager or old agent is started.
- PID1 accepts only the inspected legacy Docker metadata format/packages/images.
  It refuses running/paused/restarting container metadata, unknown images,
  alternate runtimes, Swarm and unexpected daemon configuration. It saves all
  original restart policies and turns every one off **before Docker starts**.
- A fail-closed Docker AuthZ service is installed with readiness notification and
  a Docker dependency. Internal daemon restore is handled by the offline restart
  policy change, not falsely attributed to AuthZ. API start/restart/unpause/exec,
  stock-image recreation and restart-policy escalation are denied. Only pinned
  Runtipi infrastructure, its main socat companion, and the two BOM-pinned new
  images may be started; the managed state mount is required on engine creation.
- The existing managed executable lease is installed before these new images can
  run. Systemd enters a dedicated cold target, without old default user services.
  A real forbidden-start/restart/unpause/exec witness is required before migration;
  old-image recreation is tried again after image load and Runtipi refresh.
- The existing sealed migration gains `--cold-bootstrap`. It inspects the stopped
  legacy engine rather than pretending it was running. Its managed SSH key
  transform changes one YAML scalar and proves all other bytes/data unchanged;
  it never invokes old Hermes or edits stock implementation. Existing modern mode
  retains its CLI and user-service behavior.
- The existing activation/rollback code stops the maintenance guest before normal
  boot or restore. Cold rollback leaves the original disk **stopped**, rather than
  booting the old unmanaged services. Unconfirmed shutdown never restores over a
  live disk. The complete disk snapshot preserves original restart policies on
  every rollback. Normal-health failure retains that snapshot and reports failure.
- Successful migration verifies the new runtime and held lease, restores original
  restart policies for retained containers and the exact prior daemon config for
  normal boot. The normal managed admission release/health path is reused.
  Completion records make repeat local launch a no-op.

## Pin inspection actually performed

The original used baseline was inspected through a read-only bind of the disk
into the existing `wizard-os-base:0.3.0` debugfs reader. No baseline VM was booted
or changed by that inspection. Observed:

- Docker CE `5:29.9.0-1~debian.13~trixie`; containerd `2.4.1-2~debian.13~trixie`.
- `overlay2`, containerd snapshotter false, no configured alternate Docker root,
  runtime, authorization plugin or live-restore setting.
- Original Runtipi image ID
  `sha256:bd2554bc739578346d04698d768d6d50621372533d4971b0215020ccf6fa4e78`.
- The original stopped container service/image identities are explicit in
  `next/guest/cold-bootstrap.py`; all had `Running=false`, `Paused=false`,
  `Restarting=false`, `Pid=0` and `unless-stopped` policies. Stock main/transcriber
  share image `sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b`.
- Both existing managed/legacy SSH key copies were present and had equal digests;
  no key bytes were retained in the evidence/report.

The public Moby v29.9.0 source URLs returned404. Do not substitute the inspected
v28 restore source for evidence of the installed version. The exact installed
Docker behavior, PID1/initrd handoff, AuthZ route coverage and actual Runtipi
refresh remain load-bearing checks in the queued VM run. Fail closed on any
mismatch; do not weaken the policy to make the test pass.

## Checks / parent submission

`next/guest/tests/test_cold_bootstrap.py` runs fast no-daemon policy, metadata and
byte-preservation tests. `Tests/GuestActivation/main.swift` now includes modern
and cold post-apply rollback/normal reconnect fixture scenarios. These are not
VM acceptance.

`Tests/run_cold_bootstrap_checks.py --spec <absolute-spec.json>` is the new durable
worker entrypoint. It requires exact `source`, `evidenceRoot`, `python`, `uv`,
`frozenPayload`, `publicApp`, `sparkle`, `candidateApp`, `baselineDisk`, `bootDir`,
`oldApp`, `oldLaunchApp`, `quitHelper` fields. Every work/evidence path is external.
It creates an isolated QA Python environment, runs focused checks, APFS-clones the
frozen payload, replaces only three bounded migration source files and updates
their BOM hashes. Both large image archives are verified unchanged. It builds the
small native307 app without a DMG/factory rebuild and verifies codesigning.

The existing probe gains an explicit candidate mode. It boots only a clone with
original0.6.1, stops it, launches the new app with **no primed transaction or
manual migration**, clicks the native consent button, requires the cold witness,
checks retained chat rows/app-data directories/accounts/config/file selection,
and repeats launch without reapplying. It restores defaults and removes its
owned old-app copy. The unique candidate app remains for parent inspection.

The runner deliberately retains `upgradeAccepted:false` until the parent closes
actual-VM rollback, active-capture/foreign-Host UI refusal, independent review and
final user UI acceptance. A missing Accessibility/RemovableVolumes grant or
locked console is a concrete human boundary, not permission to bypass TCC.
No capture speech or meeting-upload acceptance is implied by this slice.
