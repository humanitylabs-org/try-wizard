# Mac launch guest rebuild — 27 October 2026

**Prepared inputs, not an admitted rebuild. Nothing here publishes a release.**

`pins.json` freezes immutable source inputs and the current approved Wizard OS
stable manifest. `finalPins` are intentionally null wherever no tested integrated
source exists. Do not substitute `main` for a protected Mac source, silently use
old compatibility pins, or set the status to admitted to get past a gate.

## Current factory contents: onboarding only

The factory now uses the immutable Wizard OS **0.3.68** Stable snapshot (read from
`humanitylabs-org/wizard-os/releases/stable`), not 0.3.39. The selected protected
Mac WAM/Service/UX source overlays remain explicit in `finalPins`; this is not a
claim that those older integrated candidates include every subsequent upstream
core fix. Their compatibility with the newer connection apps still needs real
candidate acceptance. The older `wizard-os-stable.json` is historical only.
The manifest records actual provenance as `baseRelease: 0.3.68`. Its existing
`stack` compatibility ID intentionally stays unchanged: the native installer
uses equality of that ID to preserve an existing owner's disk, not to pick
which release gets installed. Changing it would silently replace that disk.

| Component | Factory decision and reason |
|---|---|
| Base system, Setup, first chat, phone/Tailscale helpers | Keep: boot and onboarding require them. |
| WAM, Wizard UX, Agent Service | Keep: existing installation, sign-in and chat APIs. |
| Hermes app plus pinned stock/managed runtime | Keep: first reply and the existing managed runtime/rollback contract; shared Docker layers are not extra copies. |
| Transcriber, local model and voice Python environment | Keep and prepare before sealing: voice must work during onboarding, not download on first use. |
| Claude and ChatGPT connection apps | Keep: both offered sign-in paths must work. |
| Files | Keep for now: the pinned Agent Service declares `uses: files`, so dropping it breaks its installation dependency closure. Removing that dependency is separate upstream work. |
| Postgres | Keep: App Manager's database, not an optional user app. |
| RabbitMQ | Keep: App Manager's lifecycle/install queue. |
| Traefik | Keep: the existing App Manager routing stack; no replacement proxy. |
| Recorder | Defer: recording is not onboarding; same pinned app installs later through WAM. |
| Browser | Defer: onboarding sign-in uses the Mac's browser, not guest Chromium. |
| Notifications app | Defer: optional notifications delivery, not the first chat. |
| Secret Drop app | Defer: optional secret-sharing app; host runtime-secrets wiring stays. |
| Voice-service and connection-router apps | Defer: newer optional default apps; the selected Mac onboarding already uses local transcription and existing sign-in wiring. |
| helper-python/security helpers | Remove when unused: build/probe tooling is not an onboarding runtime. |

`factory-policy.py` derives a small bootstrap release and the **full pinned default
release** from one manifest. The installer receives only the former. The
never-onboarded clone removes inherited optional apps through WAM, discards their
empty factory data, then prunes unreferenced images and build caches. Running
infrastructure and the pinned stock/managed images are retained.

After `/var/lib/wizard/setup.json` says `done: true`, a low-priority systemd timer
invokes **the existing `wam bootstrap`** with the full release. WAM keeps ownership
of dependency resolution, installation, installed alternatives and retry logic.
The trigger restores that full release to WAM's canonical `release-pins.json`;
it does not create a second store, downloader or app installer. CLI exit zero is
not enough: per-app `failed` results remain retryable across boots. A completed
request is not repeated if the owner subsequently removes an app. There is no
optional-app wait or download in Setup's HTTP path. WAM's recommendation prefetch
only caches images, so it is deliberately not mistaken for app installation.

### Packed size and first-boot growth

The old external candidate had a 48-GiB disk. This source recipe no longer asks
the guest to grow during assembly, and **always shrinks the sealed copy offline**
with `e2fsck` / `resize2fs -M`, adds only 512 MiB headroom, and truncates to the
actual ext4 block count. It then inventories, zeroes and independently reads back
all free blocks, and checks the filesystem again before xz. The tiny ext4 test
also checks that a retained file survives compaction after a nonzero file is
deleted. `installBytes` reports the compact disk plus kernel/initrd, never a
48/64-GiB future capacity. Native extraction already sparsely grows the user's
disk to 64 GiB; `wizard-grow.service` resizes ext4 on that user's first boot.
Factory boots are explicitly excluded from that unit.

**Unmeasured budget:** the supplied retained-component sizes sum to about 4.132 GB
before shared-layer savings. Allow another net 1.2–2.0 GB for the OS, WAM/UX/API,
local model and voice wheels, and assume xz produces 40–50% of those bytes:
**roughly 2.1–3.1 GB download**, with a roughly 6–9 GB compact initial disk rather
than 48 GiB. These assumptions are not a built-artifact measurement. Near 2 GB is
a target, not a proven 1.9-GB result; further Hermes/layer/model packaging work may
be required. Deferred apps subsequently use normal disk/network space.

Run `make test-factory` for portable light checks. Full `make test-contracts`
also contains a macOS-only Swift check and cannot pass as a whole on Linux.
No image build, upload, release/feed change or merge is authorized by these edits.
All existing source/image/security/phone acceptance gates remain in force.

REUSE: WAM bootstrap/recursive installer and release pins; existing voice readiness;
existing native sparse-disk expansion.
EXTEND: factory selection, post-Setup trigger, offline ext4 compaction and input hashes.
NEW: no UI component, replacement install path or publication mechanism.

## Historical findings

- `try-wizard#22` is already merged (`13e20d9`). The front door alone is not the
  matching backup engine. Stable `0.3.38` WAM includes custody #164/#165 but not
  the subsequently merged backup #61/#127.
- Service #74 was closed in favor of **merged #138**, `ce01cc74b13e10aa7f62852307d53d9049f4157c`.
  The helper vendored in `try-wizard#32` is byte-identical to that successor:
  SHA-256 `128a8242460edd4465ddb95c875dee0bc616dfe10ecc0d2e59d83ae3f60f4f1c`.
  #32's existing native CI is green, but the PR is draft and is not release-ready:
  its final Service image and real phone enrollment/reset acceptance are missing.
- Service main and protected Mac recovery are divergent; #96 is on the Mac
  branch, #138 is on main. The merge preview conflicts in seven files. Preserve
  control-origin isolation, maintenance and owner authority while integrating.
- WAM main has 39 Mac-only commits absent by ancestry. Ancestry alone does not
  prove whether patches were independently ported; compatibility/custody must be
  verified before selecting a replacement. Never discard managed admission.
- Current UX main differs from the actual live shell in 41 of 210 compared
  tracked web files. Their histories diverge 247/111 commits. See the explicit
  live-shell comparison; a main-only freeze is not proof of live feature parity.
- `try-wizard#21` was refreshed onto current main. Its factory fixture now mocks
  the product connection required by current main: focused tests **3/3 pass**.
  Exact head `d786206c68c86d3e17d663c293114e1328fb5622`; Thales native Build and
  agent review passed. Full Tests failed in the existing closing-connection
  `PortForwardSocketTests.swift` case (one issue across 425 Swift tests); one
  failed-job rerun was requested. Green exact-head tests and non-author admin
  approval/merge remain required.
- Recorder source exists, but its product rename is not fully on UX main and no
  approved immutable arm64 Recorder image is selected. Use `wizard-recorder`,
  display `Recorder`, and do not migrate owner content as a packaging side effect.

## Admission and worker contract

Run `python3 audit.py` from any directory. It exits **2**, reports the real open
source/queue gates and never constructs a VM. This is deliberate, not a passed
build. The inventory retains every dated queue entry; source provenance is not
acceptance evidence. Local evidence paths from the private queue are omitted
from this portable source artifact. The original private queue is not cleared.

Stage all exact source archives under one ThalesMedia workspace. Keep the actual
heavy submission JSON outside this repo, with an absolute worker `cwd` and
`argv` pointing to this admission wrapper. It must use `lane=heavy` and a stable
idempotency key. No heavy job has been submitted. The wrapper verifies staged
file hashes, exact integrated source stamps, queue receipts, frozen payload-pin
consumers and an explicit complete assembly recipe before it can execute.

Resolve these in order:

1. Port/review the divergent Service, WAM and live/main UX inputs in separate PRs;
   select approved immutable images and run their exact-head checks.
2. Land #21 only after CI/review. Refresh #32 against the integrated runtime and
   finish actual phone acceptance before removing draft status. #22 is landed.
3. Complete Recorder source/image identity and the queued portable-app recipes;
   do not copy owner-local content, credentials or local app installations.
4. Wire the freeze into the factory's *first* provision, runtime payload builder
   and app-manager recursive resolver. Current provisioning first executes a
   mutable `os.sh`; later checkout does not make that first execution pinned.
5. Select the next factory manifest version and align both the native production
   validator and `legacyBootstrapNeeded`; never mislabel it as `0.4.0`. Add the
   exact reviewed complete assembly recipe and hashes. Bare `build-image.sh all`
   does not compose the queued split runtime and is not that recipe.
6. Verify queued CA/certifi/Node security requirements in the actual containers;
   do not assume the old compatibility base is safe.
7. Update each gate with credential-free hashed evidence and populate final pins.
   Re-inventory and stage the final sources, then submit **one** Thales heavy job.
   The job may build unsigned; retain the existing pluggable `SIGN_IDENTITY` step.
8. Preserve the acceptance gates listed in `pins.json`: native automatic first
   install, phone, same-origin isolation, stock builder/SSH, backup/move/Undo,
   Recorder/two skins, security and state-preserving upgrade/rollback. A packed
   image or a manually patched QA guest is not launch acceptance.

Do not land draft #30 or #20 as part of this task. Do not mutate release
channels, tags, appcasts or download pages. The approved `0.3.38` snapshot here
is immutable; `0.3.39` candidate/promotion PRs remain separate work.
