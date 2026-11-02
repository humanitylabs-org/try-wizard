# First-install download correction (candidate only)

Outcome: choosing On this Mac downloads and installs the frozen Wizard OS 0.3.0 automatically after visible GitHub sign-in, with no CLI, manually downloaded archive or shipped credentials.

Base: 8b79596349f36ce39724939f3cc3e33cbbe8a0ae, own branch fix/mac-mvp-first-install-download. Parent owns independent review and publication. Guest remains byte-identical.

Lane: consequential, narrow functional auth/download correction. Trigger: new visible authentication boundary. No redesign, hosting migration, OAuth app registration, account changes or production writes authorized.

Acceptance:
- Private repository and release remain private; auth is user-driven in an isolated, visible WebKit view without cookie/password extraction or injected scripts.
- Native WebKit downloads the exact published guest after authenticated release navigation; verifies pinned length/hash before handing it to existing installer. Cancel/error fail closed and preserve installed data.
- Normal first install does not use missing latest.json, gh, or the file picker. Existing-installed machines skip download.
- Remote build and real WebKit test evidence on Thales under shared lock. Explicitly separate fixture transport from actual human GitHub sign-in/private asset proof; do not call this repaired without that proof.

Discovery: published mac-mvp-0.6.0 contains wizard-os-0.3.0.tar.xz but no latest.json. Existing source has no GitHub OAuth/app/session integration. Commit69ef7ed replaced working R2 feed with unauthenticated GitHub latest/download; later MVP pinned a nonexistent mac-mvp-20261013 tag. Changing URLs alone cannot authenticate private assets. Apple WKWebView.startDownload and WKDownloadDelegate are supported native APIs (macOS11.3+) sharing the visible WebKit session; no OAuth client registration required.

Bounded route: spike native visible GitHub/WebKit download first. No engineering CLI credentials passed into native code. Human sign-in remains a real gate if no approved authenticated session is available. If GitHub/WebKit cannot be exercised safely, stop with route evidence rather than shipping a guessed authentication architecture.
