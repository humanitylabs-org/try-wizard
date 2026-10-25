# Mac launch guest rebuild — 27 October 2026

**Prepared inputs, not an admitted rebuild. Nothing here publishes a release.**

`pins.json` freezes immutable source inputs and the current approved Wizard OS
stable manifest. `finalPins` are intentionally null wherever no tested integrated
source exists. Do not substitute `main` for a protected Mac source, silently use
old compatibility pins, or set the status to admitted to get past a gate.

## v6 local-only image transport (supersedes GHCR packaging in older notes)

- Build against Colima's **default** daemon with an explicit host socket. This
  preparation uses the endpoint-selected `default` Docker-driver buildx builder;
  it does not change the global Docker context or the existing Colima VMs.
- Export each of the 3 core and 14 derived security images with `type=oci`.
  Keep the archive on external media. Record its SHA-256, OCI index JSON hash,
  selected manifest/config digests, revision/base identity and the real local
  `docker load`/digest inspection result. `loadVerified` is **not** a registry pull.
- Resolve Docker Hub bases only through `mirror.gcr.io`, then
  `public.ecr.aws/docker`; enforce unchanged pinned digests and record all tag
  resolutions. Fail closed if neither mirror serves the selected content.
  Anonymous pulls of existing GHCR upstreams are still required; pushing is not.
- Colima's default VM does not expose the external freeze path. Verify a source
  sentinel before trusting any bind. Source verification copies `final/` into a
  unique named volume when needed and reads its exact source stamp back.
  Security packaging likewise copies probe scripts into daemon-owned volumes.
- The assembly guest imports all 17 byte-verified archives, then inspects each
  exact `ref@digest` before any installer/configuration writer. It never pulls
  these unpublished outputs. A guest daemon unable to preserve imported OCI
  digest references fails closed. Inside the disposable clone only, `guest-apply.py`
  merges `features.containerd-snapshotter=true` into the daemon configuration,
  restarts Docker and verifies `io.containerd.snapshotter.v1` before any load.
  Switching hides classic containers too: capture immutable image identities first,
  write security overrides and bootstrap the manager/DB/queue/proxy without pulls.
  Recreate inherited app services via WAM; verify effective compose images and
  every running/stopped container ref and ID again after final writers and at seal.
  Keep all selected images, including optional services, for offline recreation.
  Hidden classic layer/container data is deliberately retained (size and guest
  filesystem before/after recorded); no raw layer deletion or switch-back is safe.
  The clone's sparse disk grows from 16 to 48 GiB before boot (`resize2fs` inside
  the guest). All 17 imports plus hidden classic data exceeded the original 16
  GiB filesystem in the Thales smoke; the retained base bytes/hash are unchanged.
- Stage a **new** freeze and inventory. Never rewrite a v5 input underneath a
  source-verification job. Keep source verification first, then 17 packaging
  jobs, 05 security closure, 06 resolve, and finally 07 admission/rebuild.
  Completed packaging can be reused only after archive, source and daemon
  identity are reverified; failed partial directories require explicit recovery.
- These are local launch inputs, not public release artifacts. Publishing images
  happens **after launch**, through reviewed PR merge and normal Actions only.
  No macOS `docker login`, GHCR push, main merge, channel change or guest rebuild
  is part of packaging preparation.

## Findings

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
