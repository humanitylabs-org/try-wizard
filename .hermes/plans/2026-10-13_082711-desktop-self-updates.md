# Try Wizard — self-updates build brief

**Status:** Proposed execution plan only. No builders dispatched, product changes made, release published, or live update feed activated.

**Outcome:** An installed Try Wizard keeps its native Mac app and local Wizard VM software current without terminal commands, replacement VMs, or repeated manual downloads, preserving the owner's working state.

**Recommended ownership:** One parent/integration owner and two implementation owners, in isolated worktrees: A = Mac app/Host updater; B = VM software updater. Establish and prove the shared boundary before parallel implementation. All builds, VM runs and sustained QA run on Thales under `/Volumes/ThalesMedia/Projects/wizard-desktop/`; Telos does source inspection, edits and orchestration. Require exact remote commands and artifact evidence from both workers.

## Acceptance

1. An existing installation discovers a staged approved release, downloads it, applies both native and guest updates through the real update path, and reports the actual installed versions. No terminal or replacement VM is required after the bootstrap installation.
2. Chats, credentials, installed apps, files and local settings survive. An existing guest receives a visible software change; unchanged disk identity alone is insufficient proof.
3. Active recording/chat/tool execution delays disruptive activation. After interruption or relaunch, update state remains truthful and recoverable. Host/guest updates never run competing stop/start operations.
4. Tampered or incompatible releases are rejected; offline, insufficient-space and failed-health-check cases leave a usable installed version or demonstrably restore the previous compatible software and data state.
5. Native-only and guest-only updates both work independently. Normal software updates do not download the full factory disk. The intended recipient can fetch feeds and artifacts through the selected distribution route.

## Verified starting points

Inspected Try Wizard `41525f8510d2649076ac8533ce2a270c1b1770fa` on `feature/wizard-os-020-guest`.

- Current product is `next/`: AppKit/WKWebView frontend and Virtualization.framework Host. Legacy QEMU updater documentation in `docs/app-updates.md` is background, not the current implementation target.
- `next/mac/App/main.swift`: factory feed/download/integrity handling and `HostControl`. `Installer.finish` retains the disk for a matching stack; this does not migrate guest overlay software. It is not the desired in-place software updater.
- `next/mac/Host/main.swift`: VM lifecycle, readiness and disk-space protection. Host lives inside the app bundle; replacing the bundle requires an explicit Host lifecycle handshake.
- `next/guest/overlay/opt/wizard/bin/wizard-apps`: factory setup, first-launch voice provisioning and app-manager integration, including Hermes/voice image overrides with `pull_policy: missing`.
- Existing App Manager `/home/telos/workspace/wizard-app-manager/README.md` documents `wam app update`, `available-updates`, backup/restore and manager update commands. Reuse and exercise these rather than building a second app installer. Their coordinated unattended-update semantics are not yet proven.
- `next/README.md` and `next/QA-SLIM-0.2.2.md`: same-stack state-preservation evidence, ad-hoc signing and unresolved Developer ID/notarization gate. Public automatic access to private GitHub releases is also unresolved; a local or signed draft transport test does not prove recipient availability.

## 1 — Prove the common release path (parent owns)

Freeze only a compact interface: separate native/guest versions, release identity, architecture/OS and minimum-compatible peer versions, immutable artifact references/digests, signed release metadata, channel, and required restart/migration flags. A release may change either or both layers. Keep native Sparkle appcast and guest metadata linked by release identity; use their appropriate verification mechanisms rather than inventing one universal installer.

Specify durable states: available → downloading → ready → waiting for idle → applying → healthy, plus recoverable failure/rollback. Keep one coordination lease for disruptive local updates and a host-visible guest version/health/idle interface. The updater must survive restarting the services it updates, including Hermes and App Manager. Remote-connected Wizard instances retain their own administration boundary.

First executable spike on an isolated Thales VM: serve two staged guest releases, invoke an actual existing WAM update for one reversible component, observe a visible version change, preserve a seeded chat/file, and restore the prior version. Exercise the proposed guest status/control seam from the native side. This validates the management primitives before assigning broad build work. Establish native framework/build compatibility in the same preflight; defer release credentials to a concrete gate if unavailable.

**Stop trigger:** If this cannot demonstrate a real update and restore, repair or simplify the seam before fan-out. Do not spend more than one bounded investigation cycle adding design prose without a new runnable result.

## 2 — Mac updater (worker A)

**Owns:** Native update module, App/Host lifecycle handshake, native build integration, native updater tests and signing/package preparation in the isolated Try Wizard worktree. Parent owns shared schemas; worker B does not edit native sources.

Integrate Sparkle 2 for native signed updates, automatic checks/downloads, manual Check for Updates, pending/install/failure UI and relaunch. Coordinate with the embedded Host: hold launches during replacement, request orderly guest shutdown when required, verify the Host stopped, replace the bundle, relaunch Host/UI and reconnect to the existing guest. A cancelled/failed stop keeps the update pending.

Prove build N → N+1 using the actual updater on Thales, with installed state retained. Exercise running and stopped Host, local and remote-connected frontend, interrupted download, invalid signature, incompatible macOS and relaunch. Keep developer-test signatures clearly separate from production Developer ID/notarized evidence.

## 3 — VM software updater (worker B, parallel after slice 1)

**Owns:** Guest update service/journal, guest packaging/migrations, narrow necessary App Manager integration and guest tests in isolated worktrees. Parent approves cross-repository changes and shared interfaces.

Implement in-place updates through existing WAM/Runtipi lifecycle operations for shell/service, installed apps and the packaged stock-Hermes image. Preserve user-config overrides, SSH execution access, credentials, voice runtime/model and optional-app choices. Update only eligible installed components; keep the current factory install path for new users.

Add explicit versioned guest-overlay migrations and separate reboot-required base-system/kernel maintenance from ordinary app updates. Keep boot files, kernel and disk modules compatible; do not run an unbounded distro upgrade or claim that app updates solve base-OS maintenance. If the base-system path needs a separate tranche, record the exact coverage before release rather than reporting the VM fully updated.

Stage pinned artifacts, perform capacity checks, persist a transaction journal, activate compatible components in order, then verify actual readiness. Retain previous software and the matching data recovery point when schemas change; software rollback alone cannot reverse an irreversible database migration. Update scheduling must remain functional across service restarts.

Prove guest N → N+1 on an existing VM, including a real overlay change, app update, health failure/rollback, restart mid-transaction and preservation of custom app settings. No core Hermes modifications.

## 4 — Integrated update experience (parent owns)

Combine both branches and provide one user-facing update status with separately inspectable Mac and local-Wizard versions. Recommended initial behavior: checks and downloads automatic; compatible non-disruptive updates apply when idle; disruptive updates wait for an idle restart opportunity and expose Update now / Later. Define idle from real recording/run state; do not infer it only from a closed window.

Exercise native-only, guest-only and coordinated updates with a deliberately incompatible combination. Determine ordering from the compatibility manifest, not a permanent assumption that one side always goes first. Run the acceptance checks against the exact packaged artifacts, including recipient-accessible feed/artifact requests. One fresh consequential-change review covers release authenticity, lifecycle coordination and migration/rollback; parent fixes blockers and verifies the actual outcome.

## 5 — Bootstrap and release

Ship one manually installed updater-enabled Mac build. It must also detect an existing supported VM without an updater and install the authenticated guest updater in place through a tested bootstrap path, preserving its data. New VMs include it by default. Inventory supported installed stack versions first; legacy 0.1 cross-stack migration is a separately named path rather than silently reseeding a disk.

Production gates: available Apple Developer signing/notarization credentials; working authenticated/private or approved public distribution; James's explicit merge/publish/feed-activation authority. Keep GitHub as the selected route; switching hosts requires approval. Before release, prove the bootstrap plus two subsequent updates on Thales. Deliver exact hashes, tested source versions, logs and remaining gates to the parent. Publishing success requires reading back the exact release/feed targets.

**Deferred:** Windows/Intel ports, cross-stack 0.1 migration, delta compression and fleet rollout dashboards. These do not block self-updates on the supported current Mac/VM stack.

**Next execution handoff:** Start with slice 1 in this plan; after its real update/restore and interface proof, dispatch A and B in separate worktrees. Parent remains responsible for integration, acceptance and any release approval gate. Do not launch builders during this planning turn.
