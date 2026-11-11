# Wizard MVP in-app updater — staged integration

This lane is not a release. Parent owns cohort integration, installation and publication. See the round's `UPDATER-LIVE.md` and Thales `updater/evidence/` for actual executed results; do not infer success from scripts or this document.

## Scope

- Sparkle **2.10.0**, supported `SPUUpdater` + custom `SPUUserDriver`: automatic check/download, native top notice, progress, Later, explicit **Update and restart**, menu **Check for Updates…**.
- A downloaded archive and its complete appcast must both have Ed25519 signatures. `SURequireSignedFeed` and `SUVerifyUpdateBeforeExtraction` are enabled. No GitHub login, token or credential feature. Current private GitHub feed errors are visible; no URL is represented as anonymously usable until tested.
- Release manifest binds positive monotonic build, release ID, arm64, minimum macOS, protocol/minimum peer, native App/Host code and named guest payload files. Native executable digests cover the Mach-O `__text` section, avoiding a self-referential whole-executable signature/manifest hash. Sparkle authenticates the **entire archive**; Apple codesign seals the complete bundle/resources.
- Existing DataHome, backend preferences, persistent os directory, disk, stable MAC, selected files folder and native recording spool are retained. Native installation never seeds/replaces a factory disk.
- Local Host activity uses existing `/wizard/health` queue truth (`active`, `queued`, `liveness_available`). Unknown activity/starting VM/recording/dictation defers. No remote-server admin call or mutation. A remote connected backend continues running while this Mac updates.
- Only an explicit restart choice acquires the local lease, retains the prior app, sends a nonce/expiry/peer/path-bound Host prepare request, waits for **clean** VM shutdown and actual Host exit, then releases Sparkle installation. This path does not force-stop a live VM on timeout. Ordinary Quit cancels a prepared installation before terminating, rather than silently installing on quit.

## Build (Thales, inside worker.lock)

The verified upstream distribution archive is `Sparkle-2.10.0.tar.xz`, SHA256 `c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c`. Framework and signing tools stay outside the repository on Thales.

Required build environment:

- `SPARKLE_DIR`: verified extracted distribution.
- `SPARKLE_PUBLIC_KEY`: **public** base64 Ed25519 key. No private key is bundled/committed.
- `BUILD`: new positive monotonic release number (never reuse for a newer artifact).
- `RELEASE_ID`: exact source/cohort identity; native QA uses explicitly labeled local-stage identity.
- `SPARKLE_FEED`: HTTPS public appcast, or loopback HTTP for developer QA only. Default: `https://downloads.aiwizards.com/mac/appcast.xml` (Cloudflare R2, see `next/mac/DOWNLOADS.md`).
- Optional `SIGN_IDENTITY`: defaults to ad hoc `-` for developer QA. Actual Developer ID + notarization remain separate external gates.
- Optional `GUEST_UPDATE_PAYLOAD`: exact assembled bounded runtime migration payload below, not a factory disk.

Run the existing `next/mac/build.sh` under the shared `$WIZARD_WORK_ROOT/AndroidBuilds/worker.lock`. It signs explicit nested Sparkle helpers/framework inside-out, embeds Host, signs the app and verifies strict/deep. Only ad hoc developer builds carry disabled library validation. There is **no** downloaded-bundle re-signing or quarantine-clearing updater step.

## Stage the feed (do not publish)

`next/mac/tools/make-update-feed.py <Wizard.app> <output-directory> --base-url <approved-GitHub-release-download-base-or-loopback> --sign-tool <Sparkle-dir>/bin/sign_update --key-file <restricted-private-key-on-Thales>`

The script archives with ditto, signs the archive, writes a contract-bearing appcast, signs the **complete** appcast and runs the Sparkle verification tool for both. It writes byte/SHA/build receipts. Verify actual receipts, not the script's existence. Keep the private key directory0700/file0600; the developer QA key generator prints only a public key. Developer QA keys are not production signing authority.

Distribution steps owned by parent: install an updater-enabled bootstrap once, then upload archive + signed appcast to the approved GitHub release channel. Existing non-updater0.6.1 cannot learn this protocol without that bootstrap. Current private-recipient access is pending, not fixed by embedding login. Changing repository visibility/publication is unapproved here.

## Bounded guest activation

Reuse the **stack owner's tested current** `mac-stack-v1` payload, not a generic OS updater:

```
wam/wam/
source/next/guest/upgrade-mvp-stack.py
source/next/guest/stack-preservation.py
overlay/opt/wizard/local-proxy.conf
overlay/opt/wizard/product-plugin/{__init__.py,plugin.yaml}
overlay/opt/wizard/bin/wizard-product-configure
overlay/opt/wizard/setup/hermes_brain.py
wizard-shell.tar
```

The new app validates the payload digests, after the prior app cloned the **stopped same owner's disk** into DataHome/updates using APFS clonefile. Unsupported cloning fails before native replacement. An authenticated installed payload is shared read-only under `wizard-update`; only the durable `guest-activating` transaction enables the existing guest maintenance vsock service. The App sends a nonce/expiry/path-bound private command to the Host, which executes a **fixed** patch command directly over its own VM's vsock connection. It does not expose a Mac TCP root shell; the old `dev-shell` TCP bridge stays opt-in QA-only. The bounded script applies supported WAM/Runtipi operations and returns a scrubbed receipt proving exact Service image + SOUL/env/account identity/credentials preservation. No factory trim, account login, disk reset or Hermes core patch.

After migration the new Host stops cleanly, journal disables maintenance, normal Host restarts and front-door/UX health must answer. On migration failure or interrupted activation, stop the guest and atomically restore its own pre-activation clone. Never restore over a running disk. Failed clean shutdown keeps rollback material and explicitly does not claim recovery. Host request files, previous app and disk are private local recovery material; no guest credentials are added to feed artifacts.

Retiring the rollback clone (issue #31, on for everyone): the app deletes `updates/previous-disk.img` once the journal says `guest-activated`, the live disk identity matches the journal (and `legacy-complete.json` for a legacy-cold upgrade), at least 24 hours have passed since activation (the journal's modification time), and the local Wizard is running normally with no maintenance lease. It never deletes it in any other phase. The bytes freed go to `logs/host.log`. Installs that already finished an update clean up on their next launch under the same rule. The rule is `Shared/RollbackRetirement.swift`, tested by `swift test --package-path next/mac`.

**Acceptance still required:** actual existing guest receives changed Service/UX/WAM code via the native update route; before/after account identity, chat rows, app/file selection and VM identity; real agent work/recording deferral; failed migration/normal restart/interruption recovery. The native-only probe does not establish these. The final payload must include the stack owner's corrected preservation helper/schema, not the earlier blanket auth.json-byte check.

## Evidence / QA

All compilation, Sparkle, native/VM/browser and sustained QA stays on Thales under the shared lock. Root:
`$WIZARD_WORK_ROOT/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater`.

`tools/update-remote-qa.sh` obtains verified Sparkle if necessary and runs `tools/update-native-qa.py`. The latter builds a real bootstrap101, signed102/103 archives, installs101 in an owned external directory, exercises real check/download/Update button/relaunch, Later and busy guard, tampered archive/feed, authentic incompatible peer and offline errors, launches the retained prior bundle, and restores original preferences from a private snapshot. It writes receipts/screenshots/logs. The busy injection is explicitly a native guard test, not proof of an active real engine or physical microphone recording.

A queued job is not a build or install proof. A completed native-only receipt is not guest, public-feed or Apple-signing proof. Parent must also re-run main.swift native trusted-origin/titlebar-drag acceptance after combining the separate native owner patch with these minimal updater additions.
