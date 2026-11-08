# Try Wizard slim candidate — guest 0.2.2 / Mac 0.2.4 build 8

Staged, unmerged, unpublished. Owner: Archimedes, WizardOS · Release status #2. Daily Wizard/Voxtral and other owners' source trees remain unchanged. Android code 37 / 0.9.13 stays reserved for the background-audio owner; these Mac versions are independent.

## Exact artifacts

- Guest implementation source: `0f5a57b` (complete SHA in the archive manifest); pinned stock Hermes source and prior wizard2 rollback remain intact.
- Native build 8 implementation: `20afb41da79dd4c2a2f188269fd1762cc8f27307`.
- `wizard-os-0.2.2.tar.xz`: **1,251,391,340 bytes**, SHA-256 `0ab604255db721c93d21fd6d1fde63ccc02984dcd70e63cfe4a01d5445730fcc`.
- `Wizard-0.2.4-build8.dmg`: **1,969,373 bytes**, SHA-256 `e2a65eda5b9ef35748cd83e74a11d516d56c28157a662e17d3d1ce9b1a640a50`.
- Current candidate assets are in the existing **private draft** `try-wizard-0.2.4-candidate`; use build8 plus `feed-0.2.2.json`. Earlier DMGs/build7 and guest0.2.1 are historical checkpoints, not the candidate recommendation. The draft's older `latest.json` is deliberately not a promoted release feed.
- Guest archive is below GitHub's per-asset limit; **56.5% smaller** than 2,878,433,116-byte original. No R2 provisioning/promotion occurred.
- Factory filesystem: 7,936,483,328 logical bytes; manifest installed used-block estimate 5,737,443,602 bytes. Preinstall disclosure adds about 705 MB of background voice download and 790 MB installed voice, for about **6.53 GB** initial total installed footprint. Sparse logical capacity is not actual Mac disk consumption.

## Verified evidence

All build/VM/native campaigns ran on Thales under `/Volumes/ThalesMedia/AndroidBuilds/worker.lock`. Evidence root: `/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/evidence/slim022/`.

- `fresh-github/qa-fresh.log`: real private GitHub release-asset download → checksum verification → unpack → boot → free starter brain → first chat, **221.6 seconds** from accepting the files location. Manifest metadata was served locally with a short-lived signed GitHub asset redirect; this is not anonymous/public-release acceptance or worldwide-speed evidence. Fresh sequence used Mac build7; build8 changes only bounded installer buffers and capacity rejection ordering and was subsequently exercised on the same final archive through production update installation.
- `slim.out`: local Parakeet via Wizard Agent Service → Transcriber → local engine; compressed WebM, >30-second WAV, no-speech rejection; shared-VM stock SSH backend; real agent-created/running Python app independently read/curl-checked in VM; explicit manual Browser/AI Accounts install; bundled headless Chromium render and Claude CLI presence. **Manual install is not automatic first-use proof.**
- `native-voice8.out`: actual build8 native status visible after onboarding, preparation distinct from readiness, retry recovers, remote backend clears status/polling, local return restores it, cross-origin retry rejected.
- `voice-recovery.out`: installed-but-unavailable engine, stale old marker, interrupted service, real partially downloaded pinned `vocab.txt`, then matching restored bytes and healthy selected model. Status JSON is atomic; each boot/retry rechecks actual health plus model list.
- `update-native8/qa-update.log`: **UPDATE_KEEPS_DISK_OK**. Device/inode/size stayed `16777244:6649050:68719476736`; exact session IDs, apps and onboarding unchanged. Session: `wizard_1791836834124_326e562ee10c`. Same-stack archive updates retain the old guest disk; they do not migrate guest overlay fixes into an existing disk.
- `hash-memory/result.log`: production hash function ran twice across the actual ~8 GB factory image with matching SHA; peak RSS **18,939,904 bytes**. Regression threshold 256 MiB.
- `capacity/qa-capacity.log`: actual low-space volume (345,419,776 available bytes), production file installer rejected before modifying disk **or existing staging**.
- `resources-auth.out`: actual stock ChatGPT device-login start/cancel left selected free brain unchanged; no device code/token printed; human OAuth completion remains untested.
- `draft-readback/Wizard-0.2.4-build8.dmg`: downloaded back from draft and byte-compared to the built DMG; SHA above verified.
- Focused source tests: 5 voice recovery tests, 15 preparation/backend/auth tests, 7 frontend race tests; native Swift status-presentation assertions passed.

## Measured RAM and disk

`resources.txt` measures the same installed guest with optional Browser/Accounts processes stopped in both samples, cached data retained:

- Voice engine stopped: **1,421,279,232 bytes** guest RAM used.
- Voice model ready, before a new inference: **2,694,205,440 bytes** guest RAM used.
- Following transcription and optional app tests: **3,048 MiB** used in a 5,924 MiB guest; filesystem used **6,769,377,280 bytes** including installed optional apps and test state.

These are guest `free`/filesystem measurements, not Mac host RSS or a cold factory-only baseline.

## Failures found and repaired

- Installed Transcriber previously short-circuited to ready; stale completion marker could suppress recovery. Removed marker gating; installed/running state now never substitutes for model readiness. Package-wheel stages are visible before engine HTTP starts.
- ChatGPT cancel/start/poll races: attempt IDs and serialized transitions; attempt-scoped container-process cancellation; stale completions rejected. Stock auth itself remains unchanged.
- Final build7 update exposed autoreleased FileHandle buffers retaining multi-GB input. Sample recorded 7.5 GB peak footprint; shared internal swap volume filled. Stopped only this lane's app/host/test, retained the guest, added per-chunk autorelease pools, and verified build8 update plus bounded-memory regression. Failed attempt is retained in `update/` and `update-app-sample.txt`.
- Stronger low-space fixture exposed deletion of prior staging before the guard. Build8 checks capacity first; regression preserves both disk and staging.
- Earlier stopped `wos-stockint` relocation was fully reversed: byte-identical disk, recursive file comparison, recognized by Lima at original path. Original external recovery copy is preserved. No other lane VM was moved or stopped by this continuation.
- External-volume QA used explicit SSH-origin launches to retain removable-volume permission. This does **not** prove a fresh human Finder/TCC permission interaction. QA's persistent WebKit selection referenced an earlier erased test session; selecting the exact retained Meet Merlin session rendered its messages successfully. Generic old QA selection is not data-loss evidence.

## Acceptance still open — release remains held

1. **App installation lane:** current embedded gateway/tool discovery still absent in first chat. Consume its reviewed fresh-agent pins; verify a real Browser action / Connect Claude action installs a missing optional app and makes its tools immediately usable. No parallel WAM/gateway was invented here.
2. **Wizard UX / Modular shell owner:** recording-retention, initial mic-readiness transition and dictation failure fixes reported passing 51 checks in its separate candidate; exact integrated artifact/release acceptance still belongs to that owner and must be consumed before this package claims it.
3. **Human account/device acceptance:** complete ChatGPT and Claude subscription login → real reply → restart/update persistence, and real WebKit microphone permission/recording/reload recovery. CLI versions, synthetic uploads and auth cancellation do not close these gates. Guided Claude connection is not yet a proven Try Wizard onboarding path.
4. **James:** Apple Developer enrollment for Developer ID/notarization, then separate merge/public-release/production-feed authority. Ad-hoc signatures are only candidate evidence. No release request is being inferred from the earlier slimming approval.

Keep issue15 open and PR16 draft. The slim packaging result is verified; WizardOS release is still integration plus acceptance, not QA-only.
