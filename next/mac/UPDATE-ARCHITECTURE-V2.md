# Mac update architecture v2 — publisher / verification notes

This branch is source-only. No artifact, feed, appcast or website publication is authorized.

REUSE: existing signed Sparkle bundle, OSInstaller hashes, stopped-disk APFS clone, maintenance lease and guest applier.
EXTEND: shared update contract, manifest admission, fresh activation, ABI index selection and payload ownership.
NEW: offline index assembler and a worker-locked test-matrix driver; no new updater service or Hermes fork.

## Immutable OS feed contract

- `os/latest.json` stays at 0.4.0 for old 0.7.0 apps, forever.
- `os/p1/latest.json` stays at 0.4.1 for 0.7.1 apps, forever.
- ABI-aware clients read `os/index.json`: `{ "schema": 1, "images": [...] }`.
- Each image retains the existing feed fields (`version`, `sha256`, `bytes`, `installBytes`, `background`, `parts`) and adds integer `guestABI` and numeric-sortable `imageBuild`.
- Every part has `url`, `bytes`, `sha256`. URLs are absolute HTTPS `https://downloads.aiwizards.com/os/<version>/<file>`; no mutable aliases, queries or fragments. One archive can be represented as one part.
- Select newest imageBuild in the app's supported ABI range. Unknown ABI is never inferred from a display version. Fallback to the frozen p1 feed only for index HTTP 404/410, not invalid JSON, incompatible images, TLS errors or HTTP 500.
- Generate candidates offline with `python3 next/guest/build-os-index.py <versioned-feed.json> [...] --output <staging>/index.json`. Validate all image blobs and hashes before any separately approved upload. The existing `os` publisher switches latest.json: do **not** use it for v2 without extending it to target index.json exclusively.
- Future approved publication order: immutable blobs -> read-back/hash all blobs -> ABI index -> signed appcast -> landing page. Short TTL/purge for mutable index/appcast, never overwrite or delete published parts.

## Factory / payload metadata

Factory manifests add integer `guestABI`, `imageBuild`, and baked `payloadID` (null if no payload was baked). `build-image.sh` remains the ABI-0 legacy recipe; ABI-1 remasters must explicitly supply `GUEST_ABI=1` and the sealed `BAKED_PAYLOAD_ID`. Never relabel old image versions. In-guest modern factories should retain `/etc/wizard-platform.json` with the same ABI; old images have no marker and use the Host's exact legacy inference.

The signed app release declares `supportedGuestABI: {min: 0, max: 1}`. Sealed payload BOM declares its own guestABI range and a SHA-256 payloadID covering the final BOM (excluding payloadID), including all component file digests. Fresh install compares that ID only after journaling and cloning the stopped factory disk. Missing IDs always apply; exact equality skips apply and writes a disk-bound receipt. Legacy ABI-0 fresh installs use the existing cold bootstrap; ABI-1 uses the existing maintenance lease and apply path. Neither display version nor Service image ID substitutes for payload identity.

## Ownership and apps

`systemOwner: "host-payload"` is written in the disk-bound Host receipt and guest owner marker. An explicit different owner refuses apply; absence is the legacy host-owned migration case. A lower payload build also refuses to overwrite a newer receipt. Stock Hermes' existing `.managed` marker is the configuration switch used to disable self-update (verified in the pinned f97608f source); it is written for the main home and existing profiles, and `HERMES_MANAGED=host-payload` in the owned managed-image configuration covers future profiles, without editing Hermes core or overwriting user YAML, memories or authentication.

System applies use the existing PID1/cold maintenance machinery for both modern and legacy disks. Completed cold evidence is archived before another apply; interrupted state is never guessed complete. Original app restart policies are temporarily fenced offline, then restored on the next normal boot. The Docker daemon version/config are validated, not upgraded. No app container/image/volume is recreated, pruned or deleted. A read-only before/after guard verifies app identities/config/mounts while apps stay stopped. App lifecycle services are not restarted during apply. The fixed private vsock shell is available to the Host for read-only inventory, but its Mac TCP bridge remains explicitly QA-only.

The new Host captures `appsBefore` before clean shutdown and cloning. After normal boot, a nonce-bound health receipt must confirm each previously running container ID is running on the same image. Missing pre-update inventory from an N-1 Host is **not** silently called healthy: that transition needs the matrix to establish the bootstrap path. Fresh factory and explicit legacy-cold migrations have no prior running-app inventory; their stopped-factory assertions still apply.

## Remaining release gates

No Swift compilation, macOS execution, Sparkle interaction, APFS clone, guest boot, aged-disk run, interrupt or rollback has been verified on this Linux control plane. Run the committed Thales matrix under worker.lock before promotion. A successful Python/source contract suite is not VM evidence. Keep the PR draft until N-1/N app x image, old published DMG, legacy ABI-0, aged disk, interrupt and rollback gates pass.
