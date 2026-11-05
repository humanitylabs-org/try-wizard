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
- Preserve saved shares byte-for-byte and keep them connected on normal relaunch.
  Never silently clear, move or migrate user files. Legacy default URL remains
  solely for compatibility/removal protection, not a startup suggestion.
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
UI/Host; `--source-root <d22 next/mac> --expect-baseline` must demonstrate old
behavior assertions fail before the patched pass. These fixtures do **not** prove
real TCC denial, GUI choice/order, guest startup, runtime mount or file uploads.
Those remain explicit final installed-app acceptance units; do not relabel them
as native fixture passes. No owner defaults/TCC or disk reset is part of the test.
