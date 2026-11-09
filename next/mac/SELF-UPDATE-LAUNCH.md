# Mac self-update launch — issue #18

Outcome: an unsigned/ad-hoc native Mac build updates in-app to its successor,
whose updater remains usable. No release or public feed is published by this PR.

REUSE: Sparkle 2.10 Ed25519 signed-feed/archive validation, release contract,
existing native update bar and explicit restart/Host maintenance lease.
EXTEND: signed feed includes raw-ZIP SHA-256, private staging/relay, crash-safe
cancellation and a disposable native two-hop QA suite.
NEW: native artifact transport only; no web/shell capability or replacement UI.

**Ed25519 is the integrity gate. SHA-256 is an early-failure check.** Download
once into mode-0700 private staging, check the signed length and raw ZIP digest,
and serve those bytes through an unguessable loopback endpoint. Bind that endpoint
to the exact appcast version and source URL; reject delta-bearing items. Keep the
authenticated item unchanged and retain Sparkle's Ed25519-before-extraction and
bundle checks. No app-imposed one-hour resource deadline; URLSession's platform
default remains, with a 60-second request stall timer and signed size cap. Unknown
or insufficient free space (<3× signed length) refuses the download.

**Ready is private staging, not an armed Sparkle installer.** Pinned Sparkle
2.10.0 can finish stage 1 on host death without a stage-2 resume. Therefore only
explicit Update and restart, after Host/capture/lease admission, starts Sparkle
extraction/installation. A crash at ordinary Ready discards stale staging on the
next launch and requires a fresh download. Ordinary Quit requests cancellation
with visible deferral bounded to 45 seconds; workspace power-off/logout requests
teardown without waiting for that deadline. See `SELF-UPDATE-REVIEW.md` for the
pinned source evidence and why an actual stage-1 SIGKILL/unchanged-build oracle
would be false.

Verification: production and QA-flag native typechecks, portable cleanup/source
identity regressions, and a new hash-bound r5 on Thales. r4's 19/19 applies only
to `8039651`, not this revision. r5 must run full `make test-contracts`, compiled
artifact unit fixtures in both flag configurations, three disposable ad-hoc
bundles, two actual replacement/relaunch hops, quit/later/busy/crash/reoffer
cases, precise Ed25519 failure codes, signed-feed tampering/downgrade, oversize,
HTTP redirect, disk precheck, cleanup and exact preference restoration. The
harness alone enables `WIZARD_UPDATE_QA`; production rejects HTTP distribution
and omits notification QA hooks. No real guest is booted or rebuilt. Keys and
backup preference plists are deleted at harness exit.

Release gate: PR review/CI, fresh native acceptance and James's clean-install
acceptance before merge. Repo notes describe **public 306** and separate **307
candidates** (`Tests/HeadlessCold/README.md:15–19`); the owner reports testers on
307. Do not confuse those populations or claim this PR changes either one.
Bootstrap a newer build containing these fixes (> every installed tester build,
at least >307), then stage a monotonically newer successor with the SHA-bearing
Ed25519-signed appcast. Re-check actual public/tester builds before publishing.
Use `make-update-feed.py`, verify stored bytes/signatures and obtain separate
publication approval (immutable archive first, feed last). Developer ID signing
and notarization remain additional packaging gates after Apple enrollment.
