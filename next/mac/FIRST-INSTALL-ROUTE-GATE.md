# Automatic first-install download: route gate, not a repaired release

## Decision

Use a **visible, isolated native GitHub sign-in followed by WebKit's own automatic download** of the pinned private release asset. This is the narrowest candidate found: no hosting change, OAuth application registration, shared secret, gh prerequisite or ordinary manual-file step. **Do not promote it yet:** a repository-authorized human must complete GitHub sign-in in the native view once so the actual private-asset redirect/download can be verified. No such session was available to the isolated native probe; engineering gh authentication was deliberately not copied into it.

This is a human-authentication validation gate, not a request to make anything public or approve a new provider. The interaction already falls within the user's allowed scope. Parent owns coordinating that one human step and subsequent production implementation/release. No product-code repair or ready DMG is claimed by this checkpoint.

## What is established

- Base includes folder repair8b79596349f36ce39724939f3cc3e33cbbe8a0ae on isolated branch `fix/mac-mvp-first-install-download`.
- The actual private prerelease `mac-mvp-0.6.0` has11 assets, including `wizard-os-0.3.0.tar.xz` (1,269,879,876 bytes), and no `latest.json`. Read through `/opt/homebrew/bin/gh release view` on Thales for engineering discovery only.
- The production source's `mac-mvp-20261013/latest.json` and recovery release page target a nonexistent release. Private asset unauthenticated HTTP read also returns404. Replacing the tag and publishing a private feed cannot, by themselves, repair native unauthenticated URLSession access.
- History:69ef7ed replaced the prior R2 feed with unauthenticated GitHub `releases/latest/download/latest.json`. The MVP later pinned the incorrect tag. Automatic first install was not removed from the downloader code; its distribution/authentication contract was broken and the manual recovery path became the ordinary path.
- Existing native source contains no GitHub OAuth client, WKDownload integration or supported GitHub-auth bridge to reuse.

## Executed proof (Thales)

Remote root: `/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-first-install-download/spike/`.

`lockf -k -t 60 /Volumes/ThalesMedia/AndroidBuilds/worker.lock perl -e 'alarm 180; exec @ARGV' bash <root>/run.sh` compiled the disposable Swift/AppKit/WebKit probe and returned:

```
NATIVE_SESSION_DOWNLOAD_FIXTURE_PASS
ROUTE_SPIKE_FINISHED
```

The local HTTP fixture explicitly tests WebKit session semantics, not GitHub access: HttpOnly SameSite=Strict cookie established through navigation; protected release and asset return200; native download finishes31744 bytes with SHA256 `4126eadad73994576803d75416ab12ba1cabba60efa2f6e5f246d693768a4232`. No cookie is read by Swift. A direct `startDownload(using:)` attempt did **not** preserve this fixture's strict-cookie behavior (403); normal WebKit navigation converted with `.download` did. This is why the spike uses native navigation/download delegate handoff rather than assuming cookies attach to arbitrary download requests.

The genuine native GitHub request returns200 `/login`, title `Sign in to GitHub · GitHub`. Inspected screenshot shows the real empty username/password form, no unsupported-browser warning. With no human sign-in, receipt ends `human-sign-in-required`, `downloadStarted:false`. No real GitHub private asset was downloaded by this native session. Current spike deliberately does not capture screenshots or page contents during sign-in.

Receipts: `<root>/evidence/fixture/receipt.json`, `<root>/evidence/github/receipt.json`, `<root>/evidence/github/unauthenticated.txt`. Small source-side copies are under `Tests/PrivateDownloadSpike/evidence-record/`. Initial empty-login screenshot remains on Thales only (the final probe has no screenshot-capture code).

## Single remaining route check

When James or another authorized tester is at Thales, parent launches `human-check.sh` under the shared bounded lock (1800-second outer deadline). It opens the visible native GitHub sign-in for up to15 minutes; the person signs in directly, not in chat. The probe automatically navigates to the exact tar asset after the release page returns200, downloads without a file picker, and checks the frozen length/SHA. It prints `REAL_PRIVATE_GITHUB_NATIVE_DOWNLOAD_PASS` only on that result. Output is under a newly created external-volume `evidence/human-<timestamp>/`; no VM boots, existing data changes or preference changes occur.

If this real route passes: implement the same bounded view in the installer, pin release/tag/length/SHA in this internal native build instead of the nonexistent feed, check capacity before downloading, keep download path app-owned, verify SHA before extraction, connect to the existing install/VM-start continuation, and cover cancellation/error/retry/data-preservation. Keep manual selection recovery-only. Independent review + exact-DMG download/install acceptance still required. Current spike is **not** production hardened and is not compiled into Wizard.

If GitHub's authentication flow cannot complete in WebKit (SSO/passkey or browser policy), stop with that exact failure. A first-party GitHub App/device flow would then require app registration/permission approval; do not borrow gh's client identity, steal browser cookies or silently substitute hosting.

Guest SHA stays `f2bbbbb18800d369925b95ba3d5be7c0ea11820a967b2ce3c6f2e0f6a2ec4d0e`. No guest or release assets were modified. No app was published. Daily Wizard host/processes and MVP preferences were untouched; probe and fixture processes exit after their bounded runs.
