# Try Wizard 0.2.3 candidate (Wizard for Mac)

This is an **unreleased, bundled baseline candidate**, not a stable promotion. The
separate shell/service split (PR #24, Proposed) has another owner; this branch does
not implement it or change the App installation lane.

## What runs where

- **Wizard.app**: a native AppKit/WebKit window, about 2 MB to download. It contains
  no Linux disk. The embedded **Wizard Host** login item runs the local VM and keeps
  it alive after the window closes.
- **Wizard OS 0.2.0**: headless Debian 13 arm64, Docker/Runtipi and Wizard App Manager,
  with wizard-shell (currently both UX and Agent Service), Hermes Agent, Files,
  Browser, Transcriber, Secret Drop and AI Accounts. `os.sh` provisions these during
  the image build. WAM is pinned to `1eab0eb991e4031f3fd992c9745f0f9d9f4bfd7a`.
- **User files**: the chosen Mac folder (default `~/Wizard`) is shared by virtio-fs
  and presented as `/home/wizard/runtipi/media` through bindfs. UID 1000 and Files'
  capability-restricted root can write there. This folder is intentionally writable
  by the guest apps; it is not a per-app access-control boundary. Application data,
  databases, onboarding, credentials and chats stay on the guest disk.

On first launch choose **On this Mac**, then the files folder. The app downloads
and hashes the OS archive, or offers **Get Wizard OS → Choose Downloaded File…** if
its feed cannot be reached. **On another computer** connects to an existing
Wizard URL without installing a VM. Do not point acceptance tests at a production
agent. Free onboarding uses an anonymous Nous starter identity and `nous/welcome`,
not the owner's subscription; no API key is embedded in the image.

## Requirements and measurements

Apple Silicon, macOS **14 or later**. Build tools: Xcode command-line tools, Docker
(via Colima), Python 3 and `xz`. Use a Docker-shared build directory. A 16 GB Mac is
recommended for the complete local stack, especially alongside other applications.

Measured on Thales (M-series Mac mini, macOS 26); these supersede the earlier
270 MB / sub-GB-memory figures for the smaller bundled-Hermes prototype:

| Item | Full 0.2 stack candidate |
| --- | --- |
| App DMG | about 1.9 MB (ad-hoc signed; not notarized) |
| OS download | 2,878,433,116 bytes, published as two parts (1.99 GB + 0.89 GB) |
| Unpacked factory disk | Approximately 13.2 GB logical, 10.3 GB allocated including boot files |
| Installed disk | 64 GiB sparse maximum; actual allocation grows with use |
| VM allocation | 4 vCPUs, **6 GiB RAM** |
| Measured VM footprint | 3,276–3,568 MB; RSS 4,458–4,965 MB |
| Warm window open | 0.35–0.41 s |
| Cold open | 7.38–8.16 s |
| Fresh download → onboarding window | 126.4 s on the tested local feed |
| Fresh launch → first chat reply | 174.9 s, including scripted onboarding |

Reserve **at least 16 GiB free** for installation/update extraction, plus room
for future app/file growth. Downloading an archive separately also consumes its
approximately 2.9 GB; reserve that in addition (roughly **19 GiB total**).
Both install routes stream into tar rather than holding a second compressed copy,
and both refuse to start with less than 16 GiB free (or the manifest's install
bytes plus 1 GiB, whichever is larger), before anything is staged. A leftover
staging folder from an interrupted install is removed before that check. Updates
temporarily unpack a new factory disk even when retaining the existing disk, so
they need the same headroom.

## Distribution: parts under GitHub's 2 GiB limit

`guest/split-release.sh <archive> <out dir>` cuts the archive into ordered
`….tar.xz.partNN` files under 2 GiB and writes `latest.json` listing each part's
size and SHA-256 plus the whole archive's SHA-256. The app downloads the parts in
order into one tar stream, checks each part's hash as it ends and the whole hash at
the end, so the result is identical to the single archive. Upload every part and
`latest.json` to one release (or any static host) and point the feed at it.

People who download by hand select **every part at once** in Choose Downloaded
File…; the app sorts them, refuses a mix of a full archive and parts, a missing part,
or parts from two downloads, and streams them in. The app reads the files itself, so
a file on an external drive asks macOS's **Removable Volumes** permission for the
app; while macOS holds that read the window says so and how to allow it (network
drives name **Network Volumes**). Nothing on the current Wizard changes until the
new image has unpacked and checked.

## Updates and acceptance boundaries

Quit the QA app and its Host before replacing the app, then drag/replace and reopen.
App replacement retains the support directory and guest disk. Installing a
**same-stack** OS archive also retains the existing disk and changes only boot
files/manifest; **it does not migrate overlay fixes into an existing guest**.
A different-stack disk is kept as `disk-previous.img` instead; this is not a tested
0.1→0.2 state migration. The corrected media permissions are verified on a fresh
install of the final archive, not inferred from an older hotpatched test VM.

The acceptance scripts require explicit success markers, verify disk identity and
state, and isolate offline QA by saving/restoring the prior support folder and
preferences. Same-stack QA explicitly reloads after the installer move: `install-file`
is a QA hook with no setup callback for an already installed guest, not evidence of a
complete user-facing OS-update workflow. `qa-fresh.sh` (env `FEED_URL` / `FEED_DIR`),
`qa-file-parts.sh` and `qa-capacity.sh` are destructive to the local QA Wizard: back it
up first. Thales QA state is retained under
`/Volumes/ThalesMedia/Projects/wizard-desktop/wizard-os-020/backup-prior-wizard-state`
and `…/backup-qa-checkpoints-20261012`. See `QA-0.2.3.md` for what ran.

**Known blocker:** the fresh Hermes agent does not have the installed apps' MCP
tools, and the gateway bridge cannot fetch their MCP URLs. WAM doctor and app
installation succeed, but that is not proof the agent can use them. The owning
App installation lane must resolve this; no WAM/service or parked per-app PR #15
changes are included here. Previous isolated Nous welcome onboarding/first-chat
QA is evidence; no additional paid/live model run is required for packaging QA.

Not done here: notarization (needs the Apple Developer account), publishing the
parts to a release (needs James's go-ahead; the private repo's releases would also
need a token or a public host for strangers), physical keyboard/clipboard and human
OAuth, and 0.1→0.2 state migration.

## Build

```bash
# Apple Silicon Mac; Docker daemon must expose this checkout and W.
export W="$PWD/out/wizard-os-build"
# Optional machine-local environment (not required by the source):
# export WIZARD_BUILD_ENV=/path/to/your/docker-env.sh
# export COLIMA_PROFILE=wb
bash next/guest/build-image.sh           # base → provision → pack
bash next/mac/build.sh                   # Wizard.app, Wizard-0.2.3.dmg
bash next/guest/split-release.sh out/wizard-os-0.2.0.tar.xz out/feed   # parts + latest.json
# If building from a source export without .git, set BUILD_SOURCE_SHA explicitly.
```

No `wizard-runtime.tgz` input is required for this stack. Provisioning needs network
access to `aiwizards.com/os.sh`, the Wizard app index and container registries.
The build checks clean ext4 filesystems before packaging; the manifest records
per-file SHA-256, allocated install bytes and `sourceCommit`. `pack` can reuse an
offline provisioned disk, but changes to the overlay must be injected and checked
beforehand (or rebuild from base). Never accept a failed fsck through `|| true`.

All sustained build/VM acceptance work for this project runs on Thales, queued
behind `/Volumes/ThalesMedia/AndroidBuilds/worker.lock`; Telos is the source/control
plane. The measured timings are observations, not promises on another machine.

## Layout

| Path | Purpose |
| --- | --- |
| `mac/App/main.swift` | Native window, backend chooser, OS installer and WebKit bridge |
| `mac/Host/main.swift` | Virtualization.framework VM, loopback bridges, status and Host control |
| `mac/Shared/Shared.swift` | Shared paths/ports; UX 47823, onboarding 47830, QA dev shell 47900 |
| `mac/build.sh` | Swift build, ad-hoc signing and DMG |
| `guest/build-image.sh` | Base, in-VM provisioning, checked sparse-image packaging |
| `guest/overlay/` | Guest services, media mount, onboarding and setup |
| `mac/qa-update.sh` | Same-stack archive update with strict disk/state assertions |
| `mac/qa-offline-install.sh` | Opt-in, saved/restored file-install and local-remote QA |
| `guest/split-release.sh` | Parts under 2 GiB + `latest.json` feed |
| `mac/qa-file-parts.sh` | Parts file install: missing part refused, external-drive permission notice, internal install |
| `mac/qa-capacity.sh` | Low-space refusal by the real installer, no state touched |
| `mac/qa-lifecycle.sh`, `mac/qa-guest-checks.sh` | Lifecycle, memory, WAM and guest checks |

The always-on roadmap remains in
[docs/always-on-wizard-plan.md](../docs/always-on-wizard-plan.md).
