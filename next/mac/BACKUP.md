# Native Wizard backup transport (v1)

The native Mac app speaks to the guest front door on loopback/vsock. The archive is the **unchanged**
`wam backup` `.wizardbackup` format, not a Mac-specific wrapper. The engine's contract is
`wizard-app-manager/docs/BACKUP.md`; it owns encryption, capture, verification, restore, undo,
per-machine wiring, and paused-until-activated state. This transport does not modify stock Hermes.

## Owner flow

The Wizard app menu contains **Back Up This Wizard…**, **Restore a Wizard Backup…**,
**Undo Last Restore**, and **Make This My Active Wizard…**. These apply only to the selected local
Mac, never a connected remote backend. A capability probe disables the menu when either the new
front door or `wam backup` is absent and shows **Backup needs WizardOS update**.

Export uses a save panel, a recovery key shown once (Copy / I Saved It), or a confirmed passphrase.
Optional Keychain storage is opt-in; entries are generic passwords under the `Wizard Backup` service
in Keychain Access. No key is put in preferences, URLs, logs or process arguments. The engine keeps
its own recovery key; a later export can use it without exposing it again. If that first display is lost,
use a passphrase rather than silently rotating the key and making earlier files inaccessible.

Restore streams the encrypted file, verifies it, shows agents/apps/file totals and the engine's plan,
then requires a separate confirmation before import. WAM's offline verify plan lists the backup's apps
without probing the running app manager; the dialog therefore says “restore apps (install if needed)”
rather than claiming they are all new installs. The engine rechecks the target immediately before import.
Messaging and cron remain paused. Activation
requires an explicit confirmation that the original Wizard is off. Undo also warns that the previous
Wizard's active state will return. Long operations use a job ID, phase text and an indeterminate spinner;
there is no invented percentage or unsafe cancellation during a restore.

The engine may deliberately return exit **3** for a partial import when an app in the backup is newer than this
box. The front door preserves `ok:false, partial:true` and projects only bounded app IDs and version labels,
never raw engine messages. The Mac shows **Partly restored — kept paused**, names the refused apps, explains
that their data here was left unchanged, and asks the owner to update this box before restoring again. It does
not show the all-apps-arrived success text or offer immediate activation. Verification also displays known
newer-app refusals. Other nonzero exit codes, and exit 3 for any operation other than import, remain failures.

## HTTP contract

**Every** route, including reads, requires `X-Wizard-Backup: wizardbackup-v1`, refuses the presence
of *any* `Origin` header (including empty/null/same-origin), rejects browser cross-site Fetch Metadata,
and accepts no query string. No CORS opt-in or preflight can authorize these routes. This mirrors the
native-only boundary of Bring My Hermes (`X-Wizard-Import: hermes-backup`); it is not authentication
against another local native process, and the front door must remain loopback-only. Access logging is
disabled by the server entrypoint. Never enable body/query logging in an intermediary.

| Method /api/backup/… | Body / behavior |
|---|---|
| GET `capabilities` | version 1 only when `wam backup key show-id --json` succeeds; name, stored-key presence, busy flag |
| POST `key/new` | `{}`; returns recovery_key **once**, no receipt/history entry; refuses replacement of an existing key |
| POST `export` | `{}` for stored key, or `{"secret":"…"}` for a passphrase/recovery key; 202 job |
| POST `upload` | raw encrypted file, Content-Length required, no content encoding, max 64 GiB; streams and returns uploaded job |
| POST `jobs/{id}/verify` | `{"secret":"…"}`; 202 job; all entries verified before exposing a projected summary and plan |
| POST `jobs/{id}/import` | `{"secret":"…","confirm":true}`; only a verified upload; 202 job |
| GET `jobs/{id}` | state/phase, byte counts where known, safe result; no key or raw engine stderr |
| GET `jobs/{id}/download` | completed export only; streams with byte count and SHA-256; deletes guest copy after successful stream; HEAD refused |
| DELETE `jobs/{id}` | discard an inactive staged upload/export; an active job cannot be deleted |
| POST `undo` | `{"confirm":true}`; 202 job; a nonmatching undo digest is **not** reported as success |
| POST `activate` | `{"old_is_off":true}`; literal boolean required; 202 job |
| GET `status` | engine last-restore metadata plus transport jobs |

Keys are written with exclusive create and mode 0600 in a 0700 job folder, passed as `--key-file`,
then deleted in `finally` on success, failure, cancellation and timeout. The subprocess receives no
inherited backup-key environment. Engine stderr is discarded, not forwarded verbatim; errors are
curated. Key-new stdout is returned directly without entering the job store. Upload/export bundles
are staged only under `/var/lib/wizard/backup-transfer`, **not** in Runtipi media, `.wizard-os`, or shared
Files. This stays on the guest disk when media is a host-mounted `wizard-files` share.

Operations are serialized while executing. Staging is bounded to 128 receipts/jobs and inactive data
expires after an hour. Restart removes orphaned bundles/keys and marks surviving receipt IDs interrupted;
it does not blindly retry a possibly partially completed import. Consult `wam backup status` and use
undo before retrying an interrupted restore. The native app does not yet automatically resume a job
across app termination. Completed downloads are checked for size and SHA-256 before an atomic
replacement at the chosen save path. HTTP redirects are refused so a body/key cannot leave loopback.

## Guest update without rebuilding the disk image

A guest with an installed WAM checkout can gain the engine **in place**: fetch an approved WAM revision
containing `backup`, switch the existing checkout to that pinned revision, and confirm `wam backup --help`
and `wam backup key show-id --json` as the WizardOS service user. `~/.local/bin/wam` is a launcher into
that checkout (`python3 -m wam`), not a copied binary. There is no `wam self-update` command in this line.
WAM's installer documents that rerunning its installation command updates the install; `os.sh` can also
refresh the stack, but a full installer/stack rerun is unnecessary for these endpoint changes and has
broader effects. Do not rotate keys during an update.

Install **both** `next/guest/overlay/opt/wizard/setup/server.py` and its adjacent `backup_frontdoor.py`
into `/opt/wizard/setup/` using the normal approved guest patch mechanism, then restart
`wizard-setup.service`. Existing `wizard-env` provides the Runtipi root, service-user home and WAM
launcher. Python aiohttp/PyYAML and system OpenSSL are already part of the shipped stack; the backup
engine can use system libcrypto without a pip-installed crypto dependency. Probe capabilities through
the front door after restart. The new native app alone deliberately does not mutate/update an old guest.
Pin the WAM and front-door revisions together in a release. No guest image rebuild is part of this lane.

## Verification

- Install the HTTP test dependency in an isolated virtualenv with `python3 -m pip install -r next/guest/tests/requirements.txt`; CI does this before running the worker-locked suite.
- `make test-backup` runs Swift contract tests and guest endpoint tests. The main `make test` delegates
  to `test-all`, which includes this target. It is separate from the legacy macOS helper's test target.
- `python3 -m unittest discover -s next/guest/tests -v` includes real HTTP and controlled-subprocess
  tests: all-route Origin/header refusal, literal confirmations, streaming over the JSON body limit,
  0600 keys and cleanup, no secret in argv/env/logs/receipts, one-shot key response, download deletion,
  busy exclusion, missing-engine capability, and restart cleanup.
- Build the native app only with `DMG=0 bash next/mac/build.sh` on the Mac build worker. Do not rebuild
  or publish a guest archive. Keep SDK/module caches and output on the designated external work volume.
- Real portability proof must use disposable guests, the actual front door, stock Hermes reads inside
  containers, byte digests and undo results. Unit fixtures alone are not migration proof. Record native
  GUI proof separately; a successful compile or HTTP proof does not prove the menu was clicked.
