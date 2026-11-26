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
3. **publish** (environment `mac-publish`, `main` only, secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_SESSION_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`): temporary R2 S3 credentials scoped to bucket `aiwizards-downloads`,
   prefixes `mac/` and `mac-dryrun/` (and `mac-beta/` once release lanes are on), object read-write, valid 7 days at most (try-wizard#115). Archimedes mints fresh
   ones weekly and loads them into `mac-publish`; GitHub never holds an account-wide token. The job uploads with the
   runner's preinstalled `aws` CLI through `https://<account>.r2.cloudflarestorage.com`. It first checks that the
   credentials still work (expired ones fail with a clear error) and that a write outside `mac/` is refused, then uploads
   the versioned zip and DMG (a HEAD check first: the same bytes are skipped, different bytes fail), verifies each file
   byte for byte through `https://downloads.aiwizards.com` with a unique query string, and uploads `mac/appcast.xml`
   last (a real release writes the landing page to `mac/index.html` just before it; the bucket root is out of scope).
4. **tag**: tags the released commit `v<version>` and writes a GitHub release with the links.

### Tester and public lanes (off by default, wizard-os#720)

With the repository variable `WOS_RELEASE_LANES=on`, a merge that raises `version.json` is a **tester build**: the
same pipeline publishes it to `mac-beta/` (`mac-beta/<build>/Wizard-<build>.zip` and `Wizard-<version>.dmg`, its signed
feed and landing page kept immutable as `mac-beta/<build>/appcast.xml` and `index.html`, then `mac-beta/index.html` and
`mac-beta/appcast.xml`), never touches `mac/`, and tags `v<version>` as a GitHub prerelease. Installed apps read only
`mac/appcast.xml`, so nobody is offered a tester build automatically; testers install the DMG from `mac-beta/`.

A tester build becomes **public** through the release train, with no person approving it (Miguel, 21 Nov 2026), the
same rule as WizardOS For everyone. Every 6 hours `.github/workflows/promote.yml` runs
`next/mac/tools/release-train-pick.py`: it takes the newest tester build (GitHub prerelease) published **72 hours** or
more ago whose build is above the live `mac/appcast.xml` (younger ones wait their turn, older ones are skipped), and it
holds while any issue labelled `release-blocker` is open in the org. It then checks that `mac-beta/<build>/appcast.xml`
names exactly that version and build, that its archive and DMG are public, that the feed and archive signatures verify
against the app's public key and that the build is higher than the live `mac/appcast.xml`; then it copies that build's
landing page to `mac/index.html` and its signed feed to `mac/appcast.xml` (last) and reads both back byte for byte. No
rebuild and no new signature: the public feed points at the very archive testers ran, under `mac-beta/<build>/`. It
finally marks the GitHub release latest. To stop a tester build reaching everyone, open (or label) any org issue
`release-blocker`.
The temporary R2 credentials in `mac-publish` must include the `mac-beta/` prefix before the variable is switched on.

"Run workflow" on `main` runs the same pipeline as a dry run by default: it publishes to `mac-dryrun/` only and never
touches `mac/appcast.xml` or `index.html`. Until the Sparkle key is in `mac-sign`, a run builds and stops before signing.

**Upgrade test** (try-wizard#129, off by default). With repo variable `WOS_MAC_UPGRADE_TEST=on` (or the "upgrade
test" tick on Run workflow, for that run only) `publish` also waits for an `upgrade-test` job (macos-15, no secrets):

- `build` also builds a test-only **candidate + 1** (the same source and release ID, `BUILD+1`, sealed by `build.sh`
  like the candidate) and stages two loopback feeds (`http://127.0.0.1:48219/`): one for the candidate's own archive,
  one for candidate + 1. `sign` signs both with the same key and still runs no project code; neither is ever published.
- `upgrade-test` runs `next/mac/tools/upgrade-test.py run`: (1) the app the live `mac/appcast.xml` offers, installed
  in a temporary Applications folder, updates to the candidate; (2) the installed candidate updates itself to candidate
  + 1. Each app runs with a throwaway DataHome, QA hooks, automatic checks off, `SUFeedURL` pointed at the loopback
  feed and a stand-in "remote" Wizard page on the same server (voice idle), so no VM starts. Pass = the relaunched app
  reports the target build, the installed `CFBundleVersion` is the target, `codesign --verify --deep --strict` passes
  and `updates/transaction.json` says `native-activated`. The table lands in the run summary; on a failure the
  journals, `ui.json`, `qa.json`, the app log and the feed requests are uploaded as `mac-upgrade-test-evidence`, the
  run fails and `publish` never runs, so the live feed is untouched.
- Step 1 is skipped with a warning when the live build is older than 312 (the first build from this workflow, all with
  the QA control channel) or not older than the candidate (a dry run of a released version); step 2 still runs.

The WizardOS image (`os/`) is still published by the operator helper (`aiwizards_downloads_publish.py os <feed dir>
<version>`), which follows the same order: versioned files first, verified through the public URL, `os/latest.json` last.

Verified 15 Oct 2026: a 300 MB two-part test image published, reassembled by the app's Swift URL resolution and matched
its SHA-256; repeat downloads were edge HITs; feeds and 404s are never edge-cached.
