# Updater execution repair checkpoint

Base: `cdec846ad2a9a7a563d7131453e9685b23f81f08`.
Repair branch: `repair/mac-updater-execution-20261014`.
Native App, Host, manifest, migration and release implementation remain unchanged.

## Observed facts

Thales evidence root:
`$WIZARD_WORK_ROOT/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater/evidence-repair`.

- `sparkle-historical.log`: real Autoupdate49102 verifies feed/archive successfully and extracts the candidate. Installed101 process49098 exits at18:44:50 (Mac log-local time). There is no successful installation receipt in this capture. Frozen native readback remains101.
- `installer-privacy-historical.log`: requests526.4241 (Updater49103),526.4244 (Autoupdate49102) and526.4245 use `kTCCServiceSystemPolicyAllFiles`, attributed to `org.humanitylabs.wizard.mvp`; preflight authValue0 replies promptly. This is **not** sufficient evidence for a privacy hang.
- `privacy-historical.log` plus the original Host42746 sample establish a real Foundation/createDirectory/mkdirat initializer stall. Request526.3793 attributes access to the MVP Host. A separate18:17:59 sandboxd error concerns RemovableVolumes and a missing auth_value. Correlation does not prove the exact stall cause.
- Read-only user/system TCC queries returned no rows for MVP identities. SSH Python can list the external-volume project. `kernel.log` has no external-volume EINTR/watchdog signature. Accordingly **no sandboxd reset, TCC reset/edit, volume remount, or broad platform repair was justified or performed**.

## Bounded probe

`tools/update-repair-probe.py` is a real native probe, not a mock and not shipping acceptance. It must execute on Thales, inside this updater root, under shared `lockf -k worker.lock`.

It verifies the existing archive and complete appcast using official Sparkle2.10 tooling without exposing the restricted developer key, bootstraps installed101, observes Host initialization for8s, captures exact owned current samples on a stall, and observes the approved native installation/relaunch for25s. Success requires native QA build102, installed CFBundleVersion102, a live replacement PID, and strict/deep codesign readback. It retains unified logs and a read-only sandboxd sample, then restores the exact original MVP preference dictionary. It never force-kills an app or VM. Only sampled, owned pre-VM initializer processes and owned Sparkle auxiliaries may be retired; no daily service is targeted.

Run with a unique `PROBE_ID` (evidence directories are not overwritten):

```sh
ROOT=$WIZARD_WORK_ROOT/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater
lockf -k -t 2700 $WIZARD_WORK_ROOT/AndroidBuilds/worker.lock \
  env UPDATER_ROOT="$ROOT" PROBE_ID=probe1 \
  /usr/bin/python3 -u "$ROOT/source/next/mac/tools/update-repair-probe.py"
```

`tools/update-diagnose.sh` records the original historical Sparkle/Host privacy windows and kernel output without changing platform state. Its historical collection was executed on Thales. Local validation covers shell syntax and Python AST only; it does not substitute for native execution.

## Acceptance status

The new probe queued at2026-10-14T12:37:55Z never acquired the shared lock. After2700s, `lockf` returned75 / `already locked`; `probe1/` does not exist. `evidence-repair/bounded-receipt.json`, read back at2026-10-14T13:23:43Z, independently records installed build101, preferences exactly matching the original handoff, zero new native retries, no recovery attempt, and no replacement/relaunch or guest proof. `queue-final-processes.txt` retains the remaining shared-lock callers, including stack parent57048; none were interrupted.

**External execution gate: the shared Thales native worker slot was unavailable throughout the bounded queue.** Recovery of either original runtime blocker could not be tested. Resume with a new finite queue only after that slot becomes available; use the bounded probe first and diagnose its actual current samples before choosing a repair. Do not infer a TCC repair from historical preflight denials.

Native replacement/relaunch and the guest transaction remain unproved. No new public release, DMG, GitHub authentication feature, Apple enrollment, or production cutover was made.
