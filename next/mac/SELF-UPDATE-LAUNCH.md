# Mac self-update launch — issue #18

Outcome: the next native Mac build updates in-app to its successor, whose own updater remains usable; unsigned/ad-hoc builds work before Apple enrollment. Do not publish a release or change the public feed in this PR.

REUSE: Sparkle 2.10 signed feeds, Ed25519 archive signatures, release contract, native update bar, deliberate-restart/maintenance-lease path.
EXTEND: feed generator includes whole-ZIP SHA-256; native updater verifies it before Sparkle extraction; disposable Thales native QA covers two consecutive hops and rejection paths.
NEW: private native artifact transport (`App/UpdateArtifact.swift`), not a second UI or Wizard web capability. No applicable web/core module exists for Sparkle's native download callback. The shared Wizard web COMPONENTS registry was checked; no shell changes.

Implementation: Sparkle's public delegate exposes no archive path. Download once to a mode-0700 staging directory, verify raw SHA-256 and signed byte size, expose those exact immutable bytes at an unguessable loopback-only endpoint, and redirect only Sparkle's mutable download request. The authenticated appcast item stays unchanged; Sparkle still validates Ed25519 signatures and bundles. Network traffic is one ZIP; loopback performs a second local read. Do not use Mach-O canonicalization for archive hashing.

Verification lane: Thales native Swift build and disposable AppKit/Sparkle test. Three ad-hoc Apple-signed app bundles (no Developer ID; no production update-key access), ephemeral Ed25519 key, private loopback feed, isolated data root, exact preferences backup/restore, no guest boot/rebuild. Two explicit restart hops, Later, busy defer, ordinary Quit, missing/wrong digest, corrupt ZIP, cleanup. Native UI uses existing update bar unchanged. Full real-guest shutdown/activation regression is outside this app-only proof and remains its existing separate gate.

Release operator gate: merge only by PR after review/CI and James's clean-install acceptance. Build/package with an explicit increasing `BUILD`. Stage the ZIP with `make-update-feed.py`, verify SHA/signatures and storage readback, then separately approve publishing immutable archive + signed appcast (feed last). Existing public build 306 feed must not be mistaken for launch readiness. A build introducing SHA enforcement needs a subsequent feed generated with SHA metadata. Developer ID signing/notarization becomes an additional packaging gate after enrollment, not an updater transport rewrite.
