# Issue #18 — review and evidence ledger

## Scope

Native app updater only. No published release, tag, public appcast edit, live install replacement, or guest rebuild. The three QA bundles use a disposable update-signing key and ad-hoc Apple signatures; that is the pre-enrollment path, not Developer ID/notarization evidence.

## Independent review

A separate GPT-6.1 reviewer inspected supplied source read-only. Initial findings and responses:

- **P1: resumed Sparkle stages can bypass the fresh-download/ready callback.** Reject `.downloaded`/`.installing` in `showUpdateFound`, discard the cached installer, and require another fresh verified download. Force Sparkle silent automatic downloads off so the custom SHA-verification path cannot be bypassed. Runtime resumed-stage coverage is still required before calling this gate proved.
- **P2: ordinary Quit incorrectly means “skip this version.”** Fresh-download cancellation uses `.dismiss`. An already staged installer still needs Sparkle's `.skip` teardown; the dismissal callback removes only that cancellation's version marker, using keys verified against pinned Sparkle 2.10 source. The native QA requires an automatic reoffer after ordinary Quit, not a manual check that ignores skipped versions.
- **P2: negative-feed mutations can change namespace prefixes and reject for an unrelated reason.** Register both namespaces in the QA process, wait for a fresh feed/archive request, and assert the intended SHA/validation failure message.
- Review requested explicit signing/feed configuration inspection: QA now runs `codesign --verify --deep --strict`, records `Signature=adhoc`, and asserts the pinned public key, required signed feed, and verification-before-extraction settings on all three apps.

Follow-up review confirmed those initial fixes and identified two further P2 issues: the extraction/setup window lacked a cancellation closure, and cancelling a new release could erase an older skip preference. Both are now addressed in source: an active-cycle flag defers Quit until the installer can be torn down; skip preferences are snapshotted and conditionally restored rather than blindly removed. Native QA now forces ordinary Quit at the real extraction callback and starts with a pre-existing older skipped version. Sparkle has no simple public "deny install-on-quit" Boolean; the app must not terminate during an un-torn-down installation cycle. Final targeted review confirmed both P2 source fixes and reported no new findings within that scope. Runtime proof remains pending, including resumed downloaded/installing-stage behavior with Host/capture blocking restart; no runtime pass is inferred from source review.

## Verified so far

- Thales Apple Silicon/macOS native `swiftc -typecheck` of the complete app source set, including Sparkle delegate signatures and new Network/CryptoKit transport: exit 0.
- Python compile checks for both feed/QA scripts: exit 0.
- Shell parse and git whitespace checks: exit 0.

## Durable native QA gate

Run on Thales under the shared resource queue, never on the VPS:

```sh
python3 next/mac/tools/self-update-launch-qa.py \
  --root "$QA_ROOT" --sparkle "$SPARKLE_DIR" --source-head "$SOURCE_HEAD"
```

A passing run must have `evidence/complete.json` with `pass: true`, individual `results.json` checks, three build logs, three code-signature reports, preferences restoration, both actual replacement/relaunch hops, failure cases and download cleanup. Without that file, the two-hop result is **not verified**. The page is an explicitly labelled local protocol fixture; no real guest inference or shutdown coverage is claimed.

Remaining merge/release gates: independent follow-up review, successful native QA, existing full guest-update regression when a release carries guest changes, CI and James's clean-install acceptance. Publishing a monotonically newer SHA-bearing signed appcast remains a separately approved release operation. The unchanged public feed currently pointing at 306 is not this PR's proof.
