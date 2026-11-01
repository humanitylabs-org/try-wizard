# Uninstall Wizard and Start Fresh (native Mac app)

This applies to the split app in `next/mac`, not the old QEMU prototype.
No guest image, release feed or guest rebuild is changed by this feature.

## What the menu does

The **Wizard** menu has **Uninstall Wizard…** and **Start Fresh…** beside
**Bring My Hermes into Wizard…**. The first sheet shows allocated sizes and the
actual data path, including a `DataHome` on another volume. Sizes are estimates
of allocated bytes, not the sparse disk's advertised capacity or guaranteed
reclaimed APFS space.

- **Keep my Wizard data** is the default for Uninstall. Only the app goes to
  Trash. The data, preferences (including the external `DataHome` pointer),
  web storage and permissions remain so a reinstall resumes the same Wizard.
- **Delete my Wizard data** needs a second, explicit confirmation. It removes
  the selected data home (VM disk, chats, sign-ins, installed apps and logs),
  both apps' preferences, caches and web storage, and resets their privacy
  permissions. It then moves the app to Trash and quits.
- **Start Fresh** uses the same second confirmation but keeps the app and
  returns to the native first-run chooser. It remembers the *location* of an
  external data home, not any prior Wizard state. Remote connection bookmarks
  are cleared, but no remote Wizard is erased.
- Start Fresh offers an APFS clone backup by default. Choose a **new** backup
  folder on the same APFS volume, outside the data home and Files folder.
  `clonefile` is used for `disk.img`; its sibling boot/manifest files are copied.
  There is no slow/full-copy fallback. A failed backup stops the operation
  before deletion. This is an unencrypted disk backup containing sign-ins;
  store it privately. It does not back up your separately retained Files folder.

The configured **Files folder is never deleted**. The default
`~/Documents/Wizard Files` is protected too. A Files folder inside, equal to, or
surrounding the app/data/settings paths is refused, including symlink aliases.
Move the Files folder somewhere separate and choose it in Wizard first.
Unreadable Files settings and redirected removal paths are also refused.
The selected external data home is authoritative; an unrelated old default
support folder is not silently deleted as well.

### Stop and failure rules

The app freezes new capture/launch work, refuses active installation, recording,
backup or update work, and reuses Host's authenticated `prepare-update` request
and nonce response. No deletion is allowed before that request says `stopped`,
Host has exited and the app owns the existing disk lock. It never kills Host.
The stopped VM's existing manifest/boot files are reused for the backup.

The stopped data home is renamed to a unique sibling before recursive deletion,
while its old disk-owner lock is still held. A new install at the old path is
never recursively swept up. If that cleanup fails, the error names the retained
(partly removed) sibling folder; inspect it before retrying.

Cleanup is retryable but is **not one atomic filesystem transaction**. An error
stops further work and says earlier steps may have completed. In particular,
macOS privacy reset or Trash permissions can fail after data was removed.
Keep never clears the preferences needed for an external-data reinstall.

Host watches the app's **original installation path** every five seconds. If
Finder removes it, Host requests a clean stop with a 45-second wait, then exits.
It does not force-stop to manufacture a 60-second pass. A stuck guest or an
in-progress guarded update may prevent the one-minute target; that is a failed
acceptance check, not permission to kill Host or delete a live disk.

## Manual removal for older builds

1. **Choose what to keep before doing anything.** Open Wizard's Files folder
   from its menu and note that exact path. Never move or delete that folder.
   Read `defaults read org.humanitylabs.wizard.mvp DataHome` in Terminal. If the
   key is absent, the data home is `~/Library/Application Support/Wizard`.
   If it is present, that external/custom folder, not the default, holds the VM.
2. In the **Wizard Host** menu, stop Wizard OS and wait for it to say stopped;
   then quit Host and Wizard. Do not force-quit Host or remove a running disk.
   If Host cannot stop cleanly, stop here and ask for help.
3. To keep your Wizard for reinstall, move **only Wizard.app** to Trash. Leave
   the support folder and all settings below alone.
4. To delete data too, first make a stopped-disk backup if needed. In Finder,
   remove only the identified data home, and only after checking the Files
   folder is neither inside it nor the same folder. Do not delete a parent
   folder or another application's data.
5. For each of `org.humanitylabs.wizard.mvp` and
   `org.humanitylabs.wizard.mvp.host`, remove its exact item under
   `~/Library/Preferences` (`<id>.plist`), `~/Library/Caches/<id>`,
   `~/Library/WebKit/<id>` and `~/Library/HTTPStorages/<id>`.
   Use `defaults delete <id>` as well so the preferences daemon does not restore
   the plist. Do not delete the parent Preferences/Caches/WebKit/HTTPStorages
   folders. Reset privacy with `tccutil reset All <id>` for each identifier.
6. Move Wizard.app to Trash. In System Settings → General → Login Items, remove
   an old Wizard Host entry if one is registered. Keep the Files folder.

These bundle identifiers are verified in the build-308 lineage and the
in-flight 0.7.2 build source. Actual installed build-309 bundle metadata was
not inspected while the native worker was unreachable; check it before
applying these instructions to a differently packaged app.

## Developer checks and evidence

`Shared/RemovalContract.swift` has no ambient Wizard paths or OS runner.
`Tests/RemovalTests.swift` injects a fake home/library, fake preference domains
and a fake runner. Its fixture snapshots list all nine data/settings paths,
plus the app, Files folder and disk, before/after Keep, Delete and Start Fresh.
The test's backup copy and marker reinstall are **contract fixtures**, not
real APFS-clone/guest-boot acceptance.

On the native worker, stage a task-owned checkout and use the durable Mac
worker to run `bash tools/qa-removal-native.sh` from `next/mac`, with
`REMOVAL_EVIDENCE` set to a new task-owned directory, verified `SPARKLE_DIR`
and `SPARKLE_PUBLIC_KEY`, and a QA-only `BUILD`. It runs `wd-heal.sh`, reports
free space, builds both native binaries ad hoc, and compiles/runs the injected
contract suite. It never launches a normal Wizard or mutates real preferences.
Record the source commit and hash the log, binaries and snapshot files.
Do not call this build/contract script full real-app acceptance.

### Remaining real-app acceptance — test state only

Use a **disposable macOS test account**, a task-owned app copy and a disposable
`--wizard-data-home` containing a stopped QA VM clone. Never use James's or the
normal Thales user's preferences/data. The app and Host use per-user defaults,
so do not run these clicks in the real owner's macOS account. Preserve outputs
under the task-owned evidence directory, not in the production data home.

1. Record the exact app/Host hashes, bundle IDs, data home and selected Files
   path. Put a known file in Files and a recognizable chat/state marker in the
   disposable guest. List **every path in the issue's table** before each run.
   Confirm the native sheets show the right paths/sizes, Keep is the default,
   Cancel leaves every path unchanged, and Delete needs the second confirmation.
2. Choose Uninstall → Keep. Observe the nonce `stopped` response and Host exit;
   list paths afterward. Only the app should be in Trash. Reinstall the exact
   built app, open the same disposable DataHome and confirm the *guest* marker
   and retained Files bytes, not only that the host disk file exists.
3. Repeat with a new disposable clone and Uninstall → Delete. Confirm the app
   is in Trash, data/preferences/cache/WebKit/HTTPStorages are gone for both
   identifiers, privacy grants have been reset, and Files is unchanged.
4. Repeat with a new disposable clone and Start Fresh, accepting the APFS
   backup. Confirm the app stays and displays **Where should Wizard live?**.
   List the removed paths and retained Files. Stop everything; restore the
   backup's contents to `<disposable DataHome>/os/`, launch with that data home,
   and confirm the guest marker. Do not restore over a running VM.
5. Repeat with an external disposable DataHome, and verify Files overlap
   refusals (Files inside/equal to/around DataHome) leave all paths unchanged.
6. On one more disposable VM, leave Host running and hand-trash only the
   task-owned app. Record monotonic elapsed time and the Host/VM stop log.
   Require clean VM stop and Host exit within 60 seconds; no force-stop/kill.

**Not yet run:** native build/contracts and all six real-app checks. The Mac
worker could not be reached after Wake-on-LAN; do not merge or ship based on
source inspection alone. The native-dialog part of checks 1–5 needs a human;
no dialog clicks or real-VM results are claimed by the filesystem unit tests.
