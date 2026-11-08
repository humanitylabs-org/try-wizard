# Mac onboarding and host-file consent policy

REUSE native hosting chooser, boot-time optional virtio-fs, guest-disk Files,
WebKit file upload picker and existing restart-idle admission. EXTEND routing
and explicit consent. NEW no parallel sharing pipeline or guest rebuild.

- Fresh native setup asks **Where should Wizard live?** before any local download,
  guest setup or host-folder access. Selecting On this Mac is the local setup
  commitment; cancelling remote address entry or going Back is not.
- Preserve normal configured local (installed disk) and remote relaunch selection.
  Old local preferences with no installed disk and no explicit local confirmation
  return to the hosting question instead of resuming an abandoned download.
- After actual Start Fresh completes stopped-disk cleanup, explicitly clear native
  backend selection in-process and return to the hosting question. Merely replacing
  the app is not Start Fresh. Never infer a completed reset from guest onboarding.
- No Mac folder is required at setup/startup. Nil files-folder.json is supported:
  VM/internal data remain in Application Support and Files on the guest disk.
  Do not probe/create Documents, show a share picker, or advise granting folder
  permission during onboarding. This supersedes older first-run/default-Documents
  guidance only for this native onboarding/share-consent scope.
- Ask for host-file access only at an explicit user sharing action. WebKit upload
  continues to ask for selected files, without a persistent folder grant. The
  existing Show Wizard Files in Finder action offers optional folder sharing when
  unset. Folder selection shares only that exact subtree read/write, not its
  parent; choosing Documents itself would expose all of Documents.
- Preserve saved shares byte-for-byte; never silently clear, move, rewrite or
  migrate `files-folder.json` or user files. Keep an **explicit** share connected on
  normal relaunch. Explicit means the file carries `"explicit": true`, written only by
  `setFilesFolder` from a user sharing action (build 312+).
- **Legacy auto shares are not consent.** Builds up to 311 auto-selected and saved
  `~/Documents/Wizard MVP` into `files-folder.json` at startup (pretty JSON
  `{"path": ".../Documents/Wizard MVP"}`, no marker) and build 311 still mounted it at
  every VM boot, so an upgrade showed the macOS Documents prompt over "Waking up your
  Wizard...". A saved path equal to that default with no marker is a *legacy,
  non-explicit* share: it is not created, opened, statted or mounted at boot, and Finder
  does not open it. The guest uses its own disk, the file and the folder stay untouched,
  and the sharing prompt says it is no longer connected. Any other path, or the same path
  with the marker, stays connected. The comparison is string-only (no stat, no symlink
  resolution) so deciding cannot itself trigger TCC.
- One accessor decides: `WizardShared.activeSharedFolder` (Host boot
  `addFilesShare(to:)`, Show Wizard Files in Finder, folder-blocked message). Raw
  `WizardShared.filesFolder` is display/removal protection only.
- Returning installs resume: a saved This Mac choice plus an installed disk goes straight
  to "Waking up your Wizard..." (no hosting chooser). That is the normal-relaunch rule
  above, not a defect. The chooser appears only for fresh/abandoned/Start Fresh state.

### Startup Documents-access audit (build 312)

| Path | Disposition |
| --- | --- |
| Host `addFilesShare` (VM boot: createDirectory + VZSharedDirectory) | Only `activeSharedFolder`; legacy auto share skipped, no access |
| App `showFilesFolder` (menu, user action) | `activeSharedFolder`; legacy share offers the explicit prompt instead of opening |
| App `showFolderBlocked` (error screen) | `activeSharedFolder ?? default` path text only; no access |
| App `begin()` / `connectLocal()` / chooser / install | Never read the share |
| `WizardShared.defaultFilesFolder` | Path computation only (`urls(for:)`), no disk; used for the string compare and removal protection |
| QA `state` JSON (`defaultFilesFolder`, `selectedFilesFolder`) | Path strings only, QA hooks only |
| `WizardRemoval.makePlan/validate` | User action (Uninstall/Start Fresh) only; keeps raw share + default for protection, may stat there by design |
| Status JSON / host-status.json / updater / backup / guest activation | Do not read the share |

## Upgrade-state rule for every onboarding/privacy fix

Test against the PRIOR build's persisted state, not only fresh state: its
`files-folder.json` auto-default, saved backend choice and installed disk. Fresh-state
tests passed for 311 while the real upgrade still prompted for Documents. A legacy
auto-created share is never explicit consent.
- Sharing a folder later uses the existing boot-time virtio-fs + restart path,
  not hot attach. Before persisting, disclose scope/restart and obtain confirmation
  plus the existing native/trusted-document idle admission. Busy/unknown/stale
  callbacks and picker/confirmation cancellation must write nothing and not restart.
  The guest's wizard-media bindfs view hides (does not erase) prior guest-disk media
  while a share is mounted; explain this before consent. No automatic copy/move.

## Focused verification

`Tests/test_onboarding_privacy.py` checks source wiring. On an admitted macOS
worker, `Tests/run_onboarding_privacy_checks.py` compiles/exercises extracted
production routing, consent, persistence and Host optional-share code with mocked
UI/Host; `--source-root <baseline next/mac> --expect-baseline` (d22dcd5) or
`--expect-fail NAME ...` (any later baseline: it must compile, run and fail exactly the
named behaviours) must demonstrate the failures before the patched pass. The runner seeds
`files-folder.json` with the prior build's own writer
(`Tests/fixtures/legacy-d22dcd5-Shared.swift`), drives the real Host boot decision, and
proves no create/stat/open/mount of the legacy folder with a FileManager/VZSharedDirectory
spy plus a fixture HOME whose `Documents/Wizard MVP` must still not exist afterwards. These fixtures do **not** prove
real TCC denial, GUI choice/order, guest startup, runtime mount or file uploads.
Those remain explicit final installed-app acceptance units; do not relabel them
as native fixture passes. No owner defaults/TCC or disk reset is part of the test.
