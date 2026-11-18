# Public downloads: downloads.aiwizards.com

Wizard's Mac app, its in-app updates and the WizardOS image are served publicly from Cloudflare R2:

- Bucket `aiwizards-downloads` (Humanity Labs Cloudflare account), custom domain `https://downloads.aiwizards.com`.
- GitHub (`humanitylabs-org/try-wizard`) remains the home for source and release notes. Downloads no longer depend on
  the repository being public or on a GitHub login.

## Layout

| Path | What | Cache |
|---|---|---|
| `mac/appcast.xml` | Sparkle feed, signed (`SURequireSignedFeed`). Built-in default `SPARKLE_FEED` in `build.sh`. | never cached at the edge |
| `mac/<build>/Wizard-<build>.zip` | Sparkle update archive named by the appcast | cached at the edge (30 days) |
| `mac/<build>/Wizard-<version>.dmg` | First-install DMG (the landing page links the newest) | cached at the edge |
| `os/latest.json` | WizardOS feed the app reads on first install (`Store.osFeedURL`) | never cached at the edge |
| `os/<version>/wizard-os-<version>.tar.xz.partNN` | WizardOS image in parts, URLs relative to `latest.json`'s folder or absolute | cached at the edge |
| `index.html` | Plain landing page the app opens when the feed is unreachable | never cached at the edge |

Rules: versioned paths are immutable (never overwrite a published file; publish a new version path). Only
`latest.json`, `appcast.xml` and `index.html` change, and they are served uncached so a new release is visible at once.

## Why parts of 240 MiB

Cloudflare's edge only caches files under 512 MB on our plan, so a whole ~1 GB image would always come from the bucket's
single region (APAC). Parts under that size are cached in the Cloudflare location nearest each user. The Cloudflare R2
object API also accepts about 250 MiB per request, so `split-release.sh` defaults to 240 MiB parts. The app downloads
parts in order, checks each part's SHA-256 and the whole archive's SHA-256.

Write `latest.json` with part URLs relative to `os/latest.json`, for example `0.3.1/wizard-os-0.3.1.tar.xz.part00`:

    split-release.sh wizard-os-0.3.1.tar.xz out/ 240 0.3.1/

## Publishing

The Mac app is released by GitHub Actions only (`.github/workflows/release.yml`, try-wizard#102): no personal machine
is involved. To cut a release, merge a PR that raises `next/mac/release/version.json` (`version`, and a `build` higher
than the live appcast's). The workflow then:

1. **build** (macos-15, no secrets): `next/mac/build.sh`, ad-hoc signed until the Apple Developer ID exists, then
   `next/mac/tools/stage-release.py` (Sparkle zip, DMG, appcast with the archive signature left open, landing page).
2. **sign** (environment `mac-sign`, `main` only, secret `SPARKLE_ED_PRIVATE_KEY`): Sparkle's checksum-pinned
   `sign_update` signs the archive and the complete appcast and checks both against the public key built into the app
   (`next/mac/release/sparkle-public-key.txt`). It runs no project code.
3. **publish** (environment `mac-publish`, `main` only, secrets `R2_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`): uploads the
   versioned zip and DMG first, verifies them byte for byte through `https://downloads.aiwizards.com` with a unique query
   string, refuses to overwrite a different file at a versioned path, then uploads `mac/appcast.xml` and `index.html`.
4. **tag**: tags the released commit `v<version>` and writes a GitHub release with the links.

"Run workflow" on `main` runs the same pipeline as a dry run by default: it publishes to `mac-dryrun/` only and never
touches `mac/appcast.xml` or `index.html`. Until the Sparkle key is in `mac-sign`, a run builds and stops before signing.

The WizardOS image (`os/`) is still published by the operator helper (`aiwizards_downloads_publish.py os <feed dir>
<version>`), which follows the same order: versioned files first, verified through the public URL, `os/latest.json` last.

Verified 15 Oct 2026: a 300 MB two-part test image published, reassembled by the app's Swift URL resolution and matched
its SHA-256; repeat downloads were edge HITs; feeds and 404s are never edge-cached.
