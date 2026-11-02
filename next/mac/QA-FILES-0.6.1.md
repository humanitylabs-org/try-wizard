# Mac MVP 0.6.1 — shared-files onboarding repair

## Request and scope
James reported a clipped onboarding sentence, rejected Inbox/Exports as file types, and asked for a Finder-visible user folder. Bounded native-only repair from mac-mvp-0.6.0/source697a49d; guest0.3.0 unchanged. Internal testing release only; no production/default-branch promotion.

- New-install suggestion: `~/Documents/Wizard MVP`.
- Copy names documents, images, audio, videos and transcripts saved in the shared folder.
- Multi-line text has no four-line cap; constrained wrapping and a scrollable container accommodate narrow windows/download notes.
- Existing `files-folder.json` stays authoritative. No automatic movement or migration of existing files; VM/logs/databases stay in Application Support.
- During onboarding, Choose Folder… selects an alternative location. Selecting a folder does not migrate files from an earlier location.

## Verification
All Swift compilation, AppKit tests and DMG work ran on Thales under `/Volumes/ThalesMedia/AndroidBuilds/worker.lock`. Working tree mirrored at `/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-files-onboarding`.

Commands: `bash next/mac/build.sh`; `python3 next/mac/Tests/qa-files-folder.py`; `hdiutil verify next/mac/dist/Wizard-0.6.1.dmg`.

Passed: `FILES_FOLDER_DEFAULT_AND_EXISTING_SELECTION_PASS`, `FILES_ONBOARDING_NATIVE_LAYOUT_AND_PRESERVATION_PASS`, strict nested codesign and DMG integrity.

Real AppKit sizes:900×660,640×460,380×538,380×538 with download note. Full text height compared with cell's measured height; all action buttons visible within scroll document; actual Back button click retained app/onboarding. Default points to Documents; existing legacy/custom choices and sentinel document preserved across launch. Per-run QA state is isolated; previous MVP preferences restored.

Evidence: remote `evidence-files/receipt.json`; PNGs render native text via AppKit PDF in the headless session (layer-backed button/background pixels are omitted; button visibility/bounds and actual Back click checked separately). Screenshots do not establish human macOS permission-prompt behavior. No VM rebuild, download or user disk reset is needed.

## Delivery
App-only `Wizard-0.6.1.dmg` (~2.2MB); retains guest0.3.0. Quit Wizard MVP, stop its test VM if running, replace Wizard MVP.app and reopen. Existing folders remain selected. First-time testers use the existing guest archive from mac-mvp-0.6.0. No Jan contact, public release, protected-main merge, or daily installation change.
