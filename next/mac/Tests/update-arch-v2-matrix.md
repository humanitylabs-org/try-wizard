# Thales update architecture matrix (not run on Linux)

`python3 next/mac/Tests/update_arch_v2_matrix.py --plan` prints the required rows without touching a VM. Execution is deliberately separate:

```sh
python3 next/mac/Tests/update_arch_v2_matrix.py --spec /Volumes/ThalesMedia/WizardQA/v2/spec.json --execute
```

The runner wraps the **whole** suite in `/usr/bin/lockf -k /Volumes/ThalesMedia/AndroidBuilds/worker.lock`. Do not nest another lock around it. It launches no build. Do not execute from the active release rig or the owner's macOS account. No publication commands are used.

## Rig / fixture spec

All large files, QA support data and evidence belong under an external `workRoot` such as `/Volumes/ThalesMedia/WizardQA/v2`. Use a dedicated disposable macOS QA login, put its username in `qaUser`, and write that same username into `<workRoot>/.wizard-update-matrix`. Its `~/Library/Application Support/Wizard` must resolve (via symlink) to the spec's `dataHome`. Existing `qa-fresh.sh` deliberately resets that QA account's Wizard preferences and support data. It is not safe on a real owner's account.

The JSON spec has these explicit fields (no passwords, credentials or signing keys):

- `source`: full pushed source commit SHA, matching the staged checkout.
- `qaUser`, `workRoot`, `dataHome`, `evidenceRoot` (new immutable directory), `timeoutSeconds` (per-row bound, default 2400).
- `apps`: keys `N-1` and `N`, each `{ "dmg": "<existing signed app DMG>" }`.
- `images`: keys `N-1` and `N`, each `{ "archive": "<existing image archive>", "feedURL": "<fixture feed URL>" }`. N must have the exact bundled payloadID; N-1 must differ or omit it. Keep parts immutable. An ABI-aware index fixture must name actual immutable HTTPS versioned parts.
- `publishedDMGs`: **every published DMG**, at least the 0.7.0 and 0.7.1 legacy feeds, each `{ "id": "0.7.0", "dmg": "<original signed DMG>", "archive": "<matching cached archive>", "feedURL": "https://downloads.aiwizards.com/os/latest.json" }` (0.7.1 uses `os/p1/latest.json`). Obtain the full inventory before running; the runner cannot discover privately held tester DMGs.
- `retainedCommands`: keys `aged-disk`, `interrupt-mid-apply`, `rollback`, each an **argv array** for the prepared rig's existing native/retained acceptance driver. The runner appends `--evidence <new row evidence dir>`. Supply concrete drivers and checkpoints; missing entries fail, never skip. Do not use `qa-update.sh` as a payload driver: that script tests archive replacement, not payload activation.

## Required retained driver behaviour

These adapters are rig inputs, not implemented or executed by this Linux change. They must exercise the actual signed app, Host, maintenance guest and shared activation path, rather than manufacture receipts. Start with a stopped APFS clone of an aged owned disk, with at least one real third-party App Manager app running before capture. The new Host must capture `appsBefore` before clone. Use a separately signed fixture appcast for the N-1 -> N transition; never repoint public feeds/appcasts.

For `aged-disk`: preserve sessions/auth/config/user data; apply N; boot normally. The runner reads the actual nonce-bound transaction, `host-status.json`, `guest-receipt.json` and `apps-health.json` directly from `dataHome`. It rejects missing `appsBefore`, a non-host owner, missing payloadID, non-running Host or unmatched health nonce.

For `interrupt-mid-apply`: wait until actual journal `phase=guest-activating`, save that JSON as `<evidence>/interrupted.json`, interrupt the owned test Host mid-apply, and relaunch the candidate to exercise recovery. Never kill an unrelated Host or share the release rig. For `rollback`: inject a payload apply failure only in a separately signed QA fixture and exercise the same stopped-disk recovery. Before either mutation, hash the stopped fixture disk into `<evidence>/before-disk.sha256`. Before normal boot, capture an APFS clone of the restored disk as `<evidence>/restored-stopped.img` and write `<evidence>/restored-proof.json` with `diskIdentity: "<st_dev>:<st_ino>"` of the actual restored disk. Normal boot changes logs and journal bytes; do not hash a running disk against the stopped baseline. Finish with a normal running rollback guest on the same inode. The runner independently checks the inode binding and hashes that stopped restoration witness and requires `guest-rolled-back`, rather than trusting the driver's exit status alone.

Missing N-1 inventory/bootstrap proof, unknown ABI, foreign owner refusal, actual app restoration and factory-rollback UI must remain release blockers. The runner stops on the first failed row; `result.json` never marks an incomplete matrix complete. Do not mistake `--plan`, fixture generation, source contracts or driver existence for VM evidence.

## Light Mac prerequisites (separate from matrix)

Run direct Swift ABI/digest checks with `python3 next/mac/Tests/test_os_manifest_contract.py <external-work-dir>`. On Linux `--emit-only` only generates the actual extracted Swift fixture; it does not compile. The discovery suite skips this direct Mac CLI fixture rather than argparse-failing. Existing `GuestActivation`/`UpdateShutdown` I/O mocks are extended for the new policy calls; actual Swift compilation and APFS runtime checks remain Mac gates.
