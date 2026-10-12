# Try Wizard 0.2.2 candidate acceptance

**Candidate only: draft PR, no merge/publish/download-page/live cutover.**

## Artifacts and provenance

All paths below are on Thales under
`/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/`.

| Artifact | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Mac app | `src/next/mac/dist/Wizard-0.2.2.dmg` | 1932043 | `5134a9079b13b84251ebd3b790f513fc80548da9e0bbe2496878bee7813deca4` |
| Corrected guest | `out/wizard-os-0.2.0.tar.xz` | 2878433116 | `662d517880633fd5af8c0c4f7f1c8743ec81b048fe351f889968ecdf8dd6ef36` |

Archive implementation source and manifest `sourceCommit`:
`63e1cf67c7627e7677a8f27ec80f48ad2c4d172f`. Later commits change tests/docs only.
The parent rebuilt the DMG as build 2 after adding the production capacity guard.
Deep/strict codesign passed. Previous app-replacement/lifecycle checks apply to
build 1; no new full install is claimed for build 2 because internal storage
is below the required floor.
The factory image was reused, with an APFS clone preserved as
`work/build-before-recovered.img`. The corrected `wizard-media` was installed into
the **offline factory disk**, read back byte-for-byte, then repacked. The old
archive is preserved as `out/wizard-os-0.2.0-before-recovered.tar.xz`.

Filesystem checks did not hide failures: read-only fsck before/after injection;
copy repair accepted only return 0/1, then a clean read-only pass; final minimized
rootfs read-only fsck passed. Image check scanned 905 ELF files, zero mostly-zero
files. Rootfs SHA-256 is
`1e578fc79b7c04ced0317602fac7c88cf232f10c78f417db762977d742b457f2`;
logical size 13209874432 bytes, manifest allocated install bytes 10292510987.
`IMAGE_OK` and `RECOVERED_PACK_OK` were emitted after the actual build.

Build commands ran on Thales behind the shared worker lock. The wb Docker daemon
was healthy but the host socket/DNS path was not: a **build-local** wrapper used
`colima ssh -p wb -- docker` and explicit container DNS. No shared Colima restart,
global network change, other lane edit or local-VPS heavy build was performed.
The source now accepts optional `WIZARD_BUILD_ENV`, `W`, `COLIMA_PROFILE` and
`BUILD_SOURCE_SHA` instead of requiring another user's Thales environment file.

## Executed recovered QA

Evidence directory: `evidence/recovered/` (logs/state snapshots on Thales).

| Check | Result / actual evidence |
| --- | --- |
| Shell syntax / whitespace | `bash -n` on modified scripts and `git diff --check` passed |
| App replacement from DMG | `APP_REPLACEMENT_PRESERVES_DISK_AND_STATE_OK`; same disk device/inode/size and exact chats/apps/onboarding |
| Corrected archive, same-stack install | `UPDATE_KEEPS_DISK_OK`; disk `16777231:30187977:68719476736` unchanged; exact session IDs/apps/onboarding compared |
| Feed unavailable | `FEED_UNAVAILABLE_OK Get Wizard OS` |
| Corrupt per-file hash | `CORRUPT_HASH_REJECTED_OK`; no guest disk installed from bad archive |
| Fresh file install of final archive | `QA_OFFLINE_FINAL_ARCHIVE_OK`; guest health passed and installed `wizard-media` exactly matched committed corrected source |
| UID 1000 write | `FINAL_ARCHIVE_MEDIA_OK`; `recovered-uid1000.txt` bytes visible on Mac |
| Files container root write | `uid=0(root)` and `MAC_VISIBLE_WRITES_OK`; `recovered-files-root.txt` bytes visible on Mac |
| App data remains guest-local | app-data on `/dev/vda` ext4; Files `/database` binds guest app-data, `/srv` binds media; distinct filesystem devices asserted |
| On another computer | `ANOTHER_COMPUTER_LOCAL_QA_OK`, via `http://127.0.0.1:47823/wizard-ux/` pointing to the disposable QA guest, not a production agent |
| Restore prior QA state | `QA_STATE_RESTORED`, then exact sessions/apps/onboarding and disk identity checked again; `RECOVERED_QA_ALL_OK` |

Same-stack QA uses the `install-file` hook and explicitly reloads after installation;
this hook has no setup callback for an already installed guest. It verifies disk
retention, not a complete end-user OS-upgrade UX. First external-volume attempt
stalled in macOS `open()` before any extraction (sample retained at
`evidence/recovered/tar-sample.txt`) and was aborted. Successful file QA used a
SHA-verified identical archive in `/Users/thales/.cache/wizard-qa/` and guest files
shared from its isolated support directory. External-volume file-picker/permission
acceptance is not claimed.

Previous isolated evidence, **not rerun model calls**: `evidence/fresh/qa-fresh.log`
contains `QA_FRESH_OK`, first chat at 174.9 seconds; lifecycle retained chats/apps/
files; guest doctor passed and `hermes-frontend-3` installed. Fresh/lifecycle timings
and full-stack resource requirements are documented in `README.md`.

## State preserved

- Original pre-candidate Mac state:
  `backup-prior-wizard-state/` (unchanged).
- Prior QA checkpoints:
  `/Users/thales/Library/Application Support/Wizard-recovered-checkpoint-1791809039`
  and `.../Wizard-recovered-checkpoint-1791809809` (APFS clones, retained).
- Offline QA's saved directory was restored to the normal Wizard support path;
  preferences restored from `evidence/recovered/offline/preferences-before.plist`.
- Disposable fresh-archive state retained at
  `/Users/thales/Library/Application Support/Wizard-recovered-offline-1791810135`.
- Prior QA app retained in `evidence/recovered/Wizard-before.app`.

## Final repeated-update capacity failure

After `RECOVERED_QA_ALL_OK`, a repeat intended to exercise automatic QA-hook reload
exhausted internal storage during extraction (`No space left on device`); it did
**not** pass. Retained QA disks/checkpoints and new extraction coexisted. The
repeat was stopped, its task-owned incomplete `os-staging` (8305737728 allocated
bytes) removed, and the prior guest returned to health; no prior disk/checkpoint
was deleted. Internal free space returned to 7.9 GiB. Both QA scripts now reject
less than 16 GiB before mutation. The parent added a production file-install preflight before staging and raised
the download preflight to a 16-GiB minimum, with fail-closed capacity lookup.
The production installer regression ran on Thales using its real low-space
volume: `PRODUCTION_FILE_INSTALL_CAPACITY_OK`, 7612145664 bytes free, no disk or
staging mutation. Evidence: `evidence/parent-capacity/qa-capacity.log`; script
`next/mac/qa-capacity.sh` compiles the actual production installer. The app
rebuild emitted `BUILD_OK`. A fresh sufficient-capacity repeat remains unverified. No fully green final repeated-update result is claimed.
After recovery, exact chats/apps/onboarding and disk identity matched the saved
state and the native window loaded (`AFTER_ENOSPC_DISK_STATE_WINDOW_RECOVERY_OK`).
Both QA guards were executed and rejected 8448270336 free bytes before mutation
(`CAPACITY_GUARDS_VERIFIED`). No repeated heavy job remains queued by this lane.

## Blockers and deferred gates

- **Blocking app-agent integration:** fresh Hermes does not see installed app MCP
  tools; gateway bridge cannot fetch their MCP URLs. WAM doctor/install success
  does not close this blocker. The App installation lane owns it; no WAM/service
  edits and no revival of parked per-app PR #15.
- Bundled shell/service remains the baseline. PR #24 is Proposed, separate owner;
  no split implementation or stable promotion in this branch.
- Archive exceeds GitHub's 2 GiB per-asset limit. Distribution needs an approved
  alternative; current feed/release assets are not validated for this candidate.
- External-volume file installation remains unverified after its stalled attempt.
- **External published-artifact acceptance remains deferred until approval.**
  No assets were published and old `qa-e2e-published.sh` was not run against a live
  release. Physical keyboard/clipboard, human OAuth, teammate download acceptance,
  external-volume file-picker permissions and 0.1→0.2 state migration remain
  unverified. DMG is ad-hoc signed, not notarized.
