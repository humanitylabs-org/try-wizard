# Public downloads: downloads.aiwizards.com

Wizard's Mac app, its in-app updates and the Wizard OS image are served publicly from Cloudflare R2:

- Bucket `aiwizards-downloads` (Humanity Labs Cloudflare account), custom domain `https://downloads.aiwizards.com`.
- GitHub (`humanitylabs-org/try-wizard`) remains the home for source and release notes. Downloads no longer depend on
  the repository being public or on a GitHub login.

## Layout

| Path | What | Cache |
|---|---|---|
| `mac/appcast.xml` | Sparkle feed, signed (`SURequireSignedFeed`). Built-in default `SPARKLE_FEED` in `build.sh`. | never cached at the edge |
| `mac/<build>/Wizard-<build>.zip` | Sparkle update archive named by the appcast | cached at the edge (30 days) |
| `mac/<version>/Wizard-<version>.dmg` | First-install DMG | cached at the edge |
| `os/latest.json` | Wizard OS feed the app reads on first install (`Store.osFeedURL`) | never cached at the edge |
| `os/<version>/wizard-os-<version>.tar.xz.partNN` | Wizard OS image in parts, URLs relative to `latest.json`'s folder or absolute | cached at the edge |
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

Upload the versioned files first, verify them byte-for-byte through `https://downloads.aiwizards.com`, then upload
`os/latest.json` and `mac/appcast.xml` last. The Cloudflare credential stays on the operator's control host; the build
machine never holds it.

The operator publish helper (`aiwizards_downloads_publish.py os|mac <feed dir on the build Mac> <version>`) enforces
this order, skips identical files, refuses to overwrite a different file at a versioned path, and verifies every file
through the public URL with a unique query string before switching the feed.

Verified 15 Oct 2026: a 300 MB two-part test image published, reassembled by the app's Swift URL resolution and matched
its SHA-256; repeat downloads were edge HITs; feeds and 404s are never edge-cached.
