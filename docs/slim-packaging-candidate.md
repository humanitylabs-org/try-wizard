# Slim packaging — candidate only

## Scope and reuse

REUSE/EXTEND: `next/guest/releases/mac-launch-20261027/compact-ext4.py`, its frozen minimal-factory onboarding/dependency policy and WAM post-Setup bootstrap, the existing native `GuestUpdate` bundle, release BOM/hash validation, `docker load -i`, VM boundary and update/rollback transactions. No second app installer, optional-payload downloader, factory recipe or container-store cleaner.

This branch carries the existing PR39 minimal-factory work and merges freshly fetched main. It does not refresh or waive PR39's frozen companion/source/image/security/assembly gates. Main's phone-provisioning fixes are retained; PR53 uninstall work is not included. `COMPONENTS.md` was absent in both source repos; `AGENTS.md`, architecture and the existing package consumers govern reuse.

## Native payload

`tools/compress-guest-payload.py INPUT OUTPUT --receipt RECEIPT` copies a validated payload into a **fresh** output directory and deterministically gzips its Docker saves. Filenames deliberately stay `wizard-shell.tar` and `wizard-hermes-managed.tar`: Docker detects gzip by magic. Exact decompressed Docker archive hashes must match the original. No image layer/config/tag bytes are rebuilt or removed. Source pins, image IDs, full migration source and the managed-stock contract stay intact.

The inner BOM's transport hashes/byte counts are updated; the normal native release manifest subsequently hashes every bundled file. The original payload is untouched. Already-gzip inputs remain byte-identical. Corrupt inputs, links, unsafe BOM paths, nested or existing output fail closed. Compression runs in `next/mac/build.sh` before release hashing and signing. This does **not** make guest migration optional, alter the native updater, bypass existing-owner migration/rollback, or fix unrelated stale source pins.

The current public build-309 payload's BOM reports `upstream_commit_verified:false`. That pre-existing release/source gate remains unresolved; lossless packaging of those bytes is not permission to promote them. A candidate native build with that payload is a packaging diagnostic, not a new releasable software stack.

## Server/factory disk

The generic pack step calls the **same** existing factory compactor, with 512 MiB bounded packed headroom, free-block inventory/zero/readback and final read-only fsck. Only the sealed disposable copy is changed. It uses a conservative logical extraction floor in `installBytes`; no native real-space guard is weakened. Recipient sparse-disk growth remains after download, not in the shipped sealed image. Compatibility `stack` IDs stay unchanged.

`next/guest/tools/slim-offline-repack.py` is an admitted Linux-worker-only diagnostic/repack path for a frozen public feed. It verifies every part, total bytes and full archive SHA; rejects unexpected/duplicate/link/escaping archive members; verifies the source manifest; mounts original/candidate read-only with no journal replay; hashes every regular file plus ownership/mode/xattrs and symlink targets before/after; compacts only a sparse copy; demands exact filesystem closure equality; reads back archive members independently; and records actual compressed/logical/allocated bytes. If present, the original BOM is retained as `original-bom.json` rather than falsely rewritten as a current release BOM.

It records daemon configuration, last-recorded container image IDs/refs and compose image declarations before any future store decision. **It never starts a daemon/VM or deletes any Docker/containerd store/blob/image/app.** Offline `State.Running` is historical, not a live-daemon census. Containerd Bolt refs remain unparsed; no deletion conclusion is authorized. Original image bytes remain hash-verified unchanged. Both patched security images and any old store contents are retained.

Worker free-space guard: two maximum 52 GiB logical disks + 30 GiB archive/overhead + 80 GiB untouched reserve. The rootfs cap admits the measured public 0.5.0 geometry. Actual free space is rechecked immediately before allocation; insufficient space fails before downloads. Jobs may retain candidates on worker scratch for parent inspection; valuable retained outputs require separately authorized durable retention.

## Verification and remaining gates

Small source regressions:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 next/mac/Tests/test_slim_payload.py -v
PYTHONDONTWRITEBYTECODE=1 python3 next/guest/tests/test_slim_offline.py -v
bash -n next/mac/build.sh next/guest/build-image.sh
```

Full-source unittest/factory/ext4 tests, real public archive repack/measurement, native `make test`, ARM Swift compilation/signature/DMG and packaging measurements are external-worker steps, not claimed from source checks. A staged command is not an admitted/executed job. No VMs are started by these first specs. A real fresh-install and N-1 owner migration/rollback acceptance matrix is still mandatory, including stock Hermes, ready local STT/model, offered AI account sign-in, Setup/first chat/phone and the required Postgres/RabbitMQ/connection infrastructure. Required dependencies may not be dropped to hit a size budget. Deferred apps must retain the existing WAM/bootstrap immutable pins.

Do not infer a 1.9 GB server target or 100 MB native artifact from this change. Measure the actual results first. Optional/external guest payload semantics are intentionally **not implemented**: they require a separate security/updater decision and independent review.

No merge, release, feed change, publication, owner-state change, original-store removal or full-launch acceptance is authorized by this candidate.
