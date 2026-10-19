# Supplied Wizard hat — private MVP branding

Base: integrated private `mac-mvp-0.6.0` (`697a49d81497f838f47dac1956adc7bfe5436661`), not the older `feature/wizard-os-020-guest` or separately staged desktop-keys line. Origin refs were fetched before selection; no newer integrated MVP was present. Public/upstream line changes are not approval of a private integration and were not imported.

Designer originals and derived exact-byte hashes are in `brand/originals/` and `brand/provenance.json`. No invented vector or symbol is used. The supplied square JPEG composition is retained by the generated icon PNGs; transparent hat PNGs remove padding only.

## Consumers

- Current native frontend installer/connection overlay: `NSImageView` loads supplied purple transparent hat; old `✦` label removed.
- Current frontend menu bar: white supplied alpha template, contained within 18 × 18 points without stretching.
- Current embedded Host fallback menu: same helper/asset, existing single-icon visibility behavior retained.
- Current frontend + embedded Host app icons: deterministic ICNS embeds all ten exact supplied PNG scale/Retina representations. Icon generation/hash validation is mandatory at build, not an optional stale ICNS copy.
- DMG app contents: supplied icons and provenance in both bundles. Existing private identity and app naming preserved; native version `0.6.0` build `2`.
- Guest setup/onboarding build overlay: supplied white mark plus favicon, served by existing `/static` route. The ChatGPT provider-choice `✦` is semantic/provider imagery and preserved.
- Alternate staged QEMU packaging default (`macos/build-app.sh`): uses exact supplied 1024px PNG rather than old `WizardIcon.svg`. That alternate host is not the private MVP, was not activated and is not claimed built here. Unreferenced historical SVG retained for history; no active default reads it.

## Boundaries / gates

The DMG is a small native installer, not an embedded guest image. Existing immutable `wizard-os-0.3.0.tar.xz` remains unchanged; this native-only candidate does **not** claim its served onboarding/web assets have been remastered. The guest-overlay source change is ready for the next private guest assembly together with the parent's approved UX hat changes. Rebuilding the entire guest before that would duplicate a large archive and still ship the old integrated UX. Do not claim complete guest web branding from native ICNS evidence.

No core Hermes, shortcuts, quit/back contracts, file sharing, guest pins, daily identity, public publication, main merges, teammate contact or OS installer feed/version changes. Remote work uses `/Volumes/ThalesMedia/Projects/wizard-desktop/branding-hat-20261014` and the shared `/Volumes/ThalesMedia/AndroidBuilds/worker.lock`.

`next/mac/Tests/test-branding.py` binds original/derived hashes, exact ICNS representation bytes, mandatory native consumers, alternate packaging default, onboarding markup, and semantic provider-icon preservation. Real Swift builds, codesign/DMG contents and native AppKit runtime/readback are separately recorded in the delivery evidence directory.
