# Native Mac identity (candidate, not a published release)

The native builder now emits **WizardOS.app**, with both `CFBundleName` and
`CFBundleDisplayName` equal to **WizardOS**. The DMG contains exactly that name
and the Applications link. DMG/archive filenames (`Wizard-<version>.dmg` and
`Wizard-<build>.zip`) stay compatible; this change does not publish either.

## REUSE / EXTEND

EXTEND the existing `assets/build-icon.py` ICNS compositor/packer with a mandatory
native `--dark` selection. No second icon drawing implementation. Keep the old
PWA/guest assets and semantic/menu-bar marks untouched. The default packing mode
still produces its original purple ICNS bytes, for legacy consumers.

`assets/brand/dark/originals/` retains the exact canonical Wizard UX icon,
compositor, transparent mark and provenance document. Source:
`humanitylabs-org/wizard-ux` revision
`8ee53f3aca865e356d760a82bd43b2cc5b940d06`, `web/icon-512.png`, introduced by
`70d16116c387553461692d3b8951206badb555f3` ("Opinionated: darker Void PWA icon").
The icon was visually compared to the old purple Mac tile: approved raster has
Void `#0B0A10` corners, faint dots, ultraviolet glow and a white-to-ultraviolet
supplied hat. This is not an inferred color swap or redrawn hat.

Canonical PNG SHA-256:
`228489a32e0c6e0d7e668e7cbe752fbfd6bfc9c8de23b45552325ab23bc91481`.
Decoded RGBA SHA-256:
`1951b6b320126cd7294f32c36e8099a9d0a107d0eb478088ed503832b9e10a44`.
The 512 representation retains the exact PNG bytes. Other sizes are proportional
Pillow 12.3.0 RGBA/LANCZOS resizes of that original, including a disclosed 1024
upscale, not newly rendered artwork. All original/generated/pixel hashes are in
the native provenance manifest. No guest image or web compositor was changed.

## Inspected continuity boundaries

- App ID `org.humanitylabs.wizard.mvp`, Host ID
  `org.humanitylabs.wizard.mvp.host`, executable names `Wizard`/`Wizard Host`,
  updater peer protocol and embedded `Contents/Library/LoginItems/Wizard Host.app`
  path are intentionally unchanged. Embedded Host display/name is WizardOS Host.
  Existing released manifest validators require those executable/Host paths.
- `Shared/Shared.swift` still honors saved `DataHome`, defaults suites, existing
  `Application Support/Wizard MVP` and default `Documents/Wizard MVP`; these
  persisted path names are compatibility storage, not the app's display identity.
  No Files selection, saved state, bundle-ID keyed TCC record or data is moved.
- `App/main.swift` launches the existing relative embedded Host. The Host's
  original-app watchdog derives its exact enclosing outer bundle by walking
  four parents; it does not search `/Applications/Wizard.app`. Both Host relaunch
  paths use that same enclosing path. Rename does not broaden the watch scope.
- `App/WizardUpdater.swift` passes the running `Bundle.main.bundleURL` to Sparkle,
  stores its actual path in the journal and backs up to `updates/previous.app`.
  `UpdateArtifact.swift` uses a private `Wizard.zip` scratch filename, not an app
  folder expectation. `Shared/UpdateContract.swift` validates IDs and hashes,
  not an outer bundle filename. Sparkle's old-install/new-archive rename behavior
  still requires real old-to-new acceptance before release; static checks are
  not proof that an old installation's outer folder gets renamed by Sparkle.
- Uninstall plans use `Bundle.main.bundleURL`, explicit DataHome/Files and the
  unchanged bundle IDs. They do not target a literal old app path. Fresh reset
  and removal controllers/contracts were preserved.
- Current native build/fixture/update QA defaults and docs now use WizardOS.app.
  Generic launch helper accepts either outer name by absolute path and unchanged
  ID. Historical version-pinned 0.2–0.6 QA/benchmark scripts and released notes
  intentionally retain their historical paths; do not run them against this
  candidate. Root `macos/` QEMU packaging remains a separate historical pipeline,
  not a second new WizardOS product, and was not renamed.
- `REMOVAL.md` is deliberately not edited in this branch because another helper
  owns its pending real-test update. Parent must reconcile its two old app-name
  examples to WizardOS.app after that helper returns, preserving its evidence.

No shell CSS, Appearance v1 `--wz-*` tokens, live skins, dark fallback, semantic
icons or floating-panel structure/styles changed. Only native identity copy
and bundle/icon resources changed; no two-skin shell acceptance is claimed.

## Regression and pending acceptance

Run `python3 -m unittest discover -s next/mac/Tests -p test_native_identity.py -v`
and `python3 next/mac/Tests/test-branding.py -v`. New regressions execute the real
plist recipe in an empty fixture, check final build/DMG names, stable IDs/storage
and path-derived watchdog, every source/pixel/ICNS representation, required
resources and rejection of a stale purple ICNS. These are source/fixture checks.

After a real native build, run
`python3 tools/verify-native-identity.py dist/WizardOS.app` and repeat against
**the mounted DMG's WizardOS.app**. Require exact frontend and embedded Host
ICNS PNG chunk/pixel provenance, executable/manifest/resource equality, and
strict deep codesign verification. Preserve signature type honestly (ad-hoc is
not Developer ID/notarization). Finder launch/icon cache, genuine old-to-new
update, uninstall and user-session acceptance remain separate gates.
