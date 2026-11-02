# Native source integration ledger

Branch: [integration/mac-release-native-20261015](https://github.com/humanitylabs-org/try-wizard/tree/integration/mac-release-native-20261015)
Exact base: `91f62f708902b9f6ffea38a6cf910577cbb1c50e`
Source/test head: `b07d8e85fe85745737a4ce1237001a2ebbb932d8`
Optimized native App + Host compile: `b495fb3e5e9f3032bab1b823ed4b5cf0a43f8829` (only subsequent change is import-boundary tests).

## Outcome
Source composition complete; **not a release or guest-update acceptance**. Added Bring My Hermes/SSH migration, cached VZ disk, supplied hat and approved R2 defaults. Reconciled native Home Option1 / app Option2–9 and move slots. Bluetooth avoidance remains explicitly unfinished, not falsely claimed integrated.

## Composition / commits
- [`b5a28963c2cb`](https://github.com/humanitylabs-org/try-wizard/commit/b5a28963c2cb56adfd1ecd29307054589dea852f) — Integrate Bring My Hermes and VM SSH migration from c851bea
- [`ed006178abfd`](https://github.com/humanitylabs-org/try-wizard/commit/ed006178abfde70057024f4a19422f145d7b4f8e) — Keep Linux guest disks from corrupting under host load
- [`de5bbca1efbc`](https://github.com/humanitylabs-org/try-wizard/commit/de5bbca1efbc42058f4599d380d3d0511c7f4b54) — Compose supplied hat branding with Sparkle candidate
- [`3cda1a7f4f9f`](https://github.com/humanitylabs-org/try-wizard/commit/3cda1a7f4f9fe8776950456e5050e17b8c74efe0) — feat(mac): serve downloads and updates from downloads.aiwizards.com (Cloudflare R2)
- [`b495fb3e5e9f`](https://github.com/humanitylabs-org/try-wizard/commit/b495fb3e5e9f3032bab1b823ed4b5cf0a43f8829) — Align native workspace slots and preserve explicit terminal routes
- [`b07d8e85fe85`](https://github.com/humanitylabs-org/try-wizard/commit/b07d8e85fe85745737a4ce1237001a2ebbb932d8) — Test native Hermes import origin and upload boundaries

Baseline is an ancestor; no unresolved entries; diff check clean. Critical updater/activation/transaction/capture files are byte-identical (blob proof in JSON). No old version/build defaults, preview bootstrap, QA fault injection, raw donor runtime output, shared repository edits, or private data imported.

## Tests / evidence
- **Thales optimized App and Host compilation:** pass; no warnings in either compiler log. `native-evidence/integration/thales-compile/receipt.json`
- **Python setup + import boundary + native contracts:** 32 passed (15 existing setup, 7 new import, 10 native contracts). `native-evidence/integration/python-discovery.log`
- **Supplied brand:** 4 passed; icon SHA256 0a775ba954a8a1fafcc3fef901fd6cafb4a3ff1256ad07a6e9a1368269f340cf. `native-evidence/integration/thales-compile/branding.log`
- **Stack preservation:** 24 passed. `native-evidence/integration/thales-compile/preservation.log`
- **Setup auth JS races:** 7 passed. `native-evidence/integration/thales-compile/setup-auth-js.log`
- **Native build shell syntax; changed Python AST; diff whitespace:** passed.

Remote evidence: `Thales:/Volumes/ThalesMedia/Projects/wizard-desktop/mac-release-20261015/native-source-qa/evidence`. No app launch, VM launch, codesigning, release manifest, final DMG or guest rebuild.

Approved hosting donor `ec8cbc8dc388ae6f094fa80d150646cc23548235` consumed. Donor already uses explicit `/index.html`; actual GET returned200. Root404 is not used as fallback. Default parts240MiB; every public object must remain strictly below250MiB. Final artifact/feeds are not published by this lane.

## Every audited feature

### native-disk-cache — integrated
26662e3 cherry-picked as ed00617; actual next/mac Host uses cached/full-sync storage attachment.
Source: `26662e305ccf8e46ed996608d51737021aa20083`.
Original audit notes (source resolutions above; runtime gates still apply): No final integrated Host boot/load/fsck acceptance found; commit rationale is not proof of corruption elimination.

### supplied-native-hat — integrated
4f94cdb + 12c884f + 95f8176 composed as de5bbca; Brand compile inputs unioned with Sparkle/updater/import, candidate version/build policy retained. b495fb3 adds existing-guest onboarding HTML/PNG migration.
Source: `95f81765d506e4bfa6a686c3264a7ea1534df4ec`.
Original audit notes (source resolutions above; runtime gates still apply): Merge shared Brand compile inputs into Sparkle build script without resetting release version/build; Rebuild guest with current queued UX, not obsolete hat.2 frozen UX; test update of existing onboarding assets.

### bring-my-hermes — integrated
108559e + c851bea ported as b5a2896; stale r5 output omitted. Menu remains opt-in, helper uses stock backup, guest importer suspends jobs/messaging and offers undo. This replaces MAIN, not a separate Agents entry.
Source: `c851bea023bc986ad39a5a241a5b649859dd3cec`.
Original audit notes (source resolutions above; runtime gates still apply): Final combined Swift build/menu action not accepted; owner notes inherited actor errors on earlier base; r8 imported_cli_chat_listed=false: search works but imported CLI chats do not appear in Chats list; Currently replaces MAIN agent, not separate Agents registry import; prior box threads disappear until undo; Retest archive validation, origin boundary, interruption and undo on exact selected guest; never import automatically during upgrade.

### agent-ssh-key — integrated
c851bea migration plus b495fb3 guard: migrate only Wizard-managed ssh/wizard-vm/wizard/22 route with old or new managed key. Explicit backend/host/user/port/key preserved; ambiguous engine/unreadable config fail closed. Final WAM must provide read-only /opt/agent-ssh mount.
Source: `c851bea023bc986ad39a5a241a5b649859dd3cec`; `a9d9be5080383f50b06c156d0ef327ecb2cb72d0`.
Original audit notes (source resolutions above; runtime gates still apply): Exercise fresh provision AND existing-install migration with final WAM pins; Preserve explicit terminal settings and verify rollback of key/config/compose changes.

### bluetooth-input — unfinished-native-port
5d65d9 is legacy macos/Sources/OmarchyVMHelper, not next/mac/App/MeetingCapture.swift. MVP MicSource has no explicit-device selection contract and always opens AVCaptureDevice.default(for:.audio); meeting Start/Tap/Choose re-use default. Cannot distinguish intentional system-selected Bluetooth from avoidable default without product choice. No donor cherry-pick or silent input override. Needed: MVP device UID/transport selection, explicit override precedence, per-session choice shared by all paths, actual format after start, device disconnect handling and physical music/TCC checks.
Source: `5d65d996014eb7c7dedb93b59a10a8815deba194`.
Original audit notes (source resolutions above; runtime gates still apply): Physical music/mic test outstanding; Cherry-picking donor alone cannot change MVP MicSource: need separately reviewed adaptation to actual MVP capture path; respect explicit mic selections.

### desktop-shortcuts — integrated
Existing command chat/focus/fullscreen/close/desktop-cycle shortcuts retained; b495fb3 adds native Home Option1, app workspace Option2-9, Shift-Option2-9 moves; no Home move target. Emits DigitN and altKey without metaKey; guest owns next-slot creation and inert missing slots. Command-number still selects backend.
Source: `ae1aa38829d1c37ae4e7299befcb877f05ceaf16`; `8c782e89bcaf52d5ff88b2906b7795d94cd6e76b`.
Original audit notes (source resolutions above; runtime gates still apply): Reconcile latest UX Home=Option1/apps=Option2–9 with native labels/dispatcher and shift-move slots; Physical keys, actual OS fullscreen and exact assembled guest acceptance outstanding.

### foreground-voice — preserved-baseline
MeetingUI/capture admission, foreground Right Command and opt-in background behavior unchanged from exact baseline.
Source: `a8c147171a2eaf578c296269e57360e9baf42093`.
Original audit notes (source resolutions above; runtime gates still apply): Physical right-command/mic/TCC on new binary; exact native Host+guest lifecycle remains open.

### drag-authority — preserved-baseline
Native drag and exact local main-origin bridge/navigation checks retained; App main diff is additive menus/branding/import and approved feed/fallback only.
Source: `342c0befa8fd53aaa8e8f89363172d5341d55b5a`.
Original audit notes (source resolutions above; runtime gates still apply): Physical title-bar/window chrome and native full-screen acceptance outstanding.

### sparkle-updater — preserved-baseline
Updater, release handshake, owned Host lifecycle, guest transaction command and guest activation Swift files byte-identical to baseline. No release build number, releaseID, signing key or artifact created. Approved hosting ec8cbc8 cherry-picked as 3cda1a7; fallback already uses /index.html (GET200).
Source: `cdec846ad2a9a7a563d7131453e9685b23f81f08`; `1372048f1acfe5b7bef595048be2f6117e5923d2`; `91f62f708902b9f6ffea38a6cf910577cbb1c50e`.
Original audit notes (source resolutions above; runtime gates still apply): 203→204 guest update never starts VM; Host PID3117 stalled mkdirat; do not touch under this audit; Guest transaction/rollback, existing state preservation through actual native update, unused-factory rollback unaccepted; Production signer/notarization, recipient-accessible signed feed, version/build and exact release provenance not established; 0.6.1 has no Sparkle updater: initial upgrade to enabled app is manual.

### stack-repairs — preserved-baseline
Baseline preserving stack transaction retained. Migration allowlist adds import/server/key tools and onboarding assets only; state-preservation library, backup/rollback, grants accounting unchanged. Parent/shared lane must preserve routes/model filters in pinned Service/WAM.
Source: `75d9d29d372216e6597930d7d244608c0fc38487`; `0f38625285d4fb78092e1d645299c0b03661ee2d`; `af9f4d6f5443194631be2cc84c0f928db9c21f0a`.
Original audit notes (source resolutions above; runtime gates still apply): Actual Host-dispatched guest installation/rollback still blocked; Any newer Service/WAM replacement must preserve route isolation, configured model filters, stock grant accounting and strict unchanged personal data.

### meeting-native — preserved-baseline
Native recorder, HUD, system audio, outbox, prompts and capture admission unchanged; no physical acceptance implied.
Source: `0dccf1b94dfc927e173eb78c6d9bc1b2888b0929`.
Original audit notes (source resolutions above; runtime gates still apply): Separate listen/think/late-permission meeting admission matrix still unexercised; Physical mic/system audio/device-change/TCC not established by fixture tests.

### meeting-package — parent-shared-dependency
No try-wizard native addition selected; parent/shared lane owns catalogue/registry/runtime/app-binding integration and acceptance.
Source: `4b339cd3394b498a78e33162e63fdf559e001f79`; `e81e47aa6690eaea5c8e390e9c5045ca6ca1cbcd`.
Original audit notes (source resolutions above; runtime gates still apply): Index write/publication issue, private-name integration, real installation/recording/hosted Back/gateway/retained-data tests open; Bound-agent recap needs Service Agents/app-bindings/runtime support; existing legacy /meetings route contract must survive.

### phone-setup — parent-shared-dependency
No private network enrollment or phone helper auto-enabled here; parent owns deliberate guest packaging and owner-ingress acceptance.
Source: `cffae868851653d8226137cff4f3357526c80945`; `e8b9e12eccb9fe0dff836cce6ba6251f92813539`.
Original audit notes (source resolutions above; runtime gates still apply): No final guest installation of helper/systemd/socket mounts/second listener or real owner phone enrollment proof found; Must enforce/test loopback-only owner ingress and separate Serve listener: never expose owner-header injection; Fresh image must contain no node state/auth keys; unpaired until explicit Connect; Previously deliberately excluded from fix round; new release owner must deliberately select and close gates.

### privacy-config — preserved-baseline
Existing local loopback authority unchanged; no owner-specific network defaults imported. Shared runtime config and phone settings remain parent/shared-lane work.
Source: `86b32da4fbb3ed9370314687a80af4dbd723d973`; `e8b9e12eccb9fe0dff836cce6ba6251f92813539`.
Original audit notes (source resolutions above; runtime gates still apply): Do not replace private Android build defaults or compile phone-only changes into Mac claims; Guest runtime network.base_url/aliases and owner.name must work without hardcoded endpoint; keep Mac loopback authority.

### tailscale-auth — parent-shared-dependency
No Tailscale auth activation here. Parent must close peer/header/forgery/direct/cross-origin gates before enabling in guest.
Source: `d8a1e29c5ebc93e5163a1e775612ba4131278fbd`.
Original audit notes (source resolutions above; runtime gates still apply): Actual Serve peer/header provenance, owner success and forged/missing/nonowner/Host/direct/cross-origin rejection remain gates.

### queue-home-resources — parent-shared-dependency
Native Home-first slots reconciled against shared UX workspace-navigation.js and desktop.js; actual current UX still needs parent guest pin/payload.
Source: `4a2371dc281104e58e6b16482a3164e74b77d869`; `90908f809c576e0d84c3a9d867ecedb948d86507`.
Original audit notes (source resolutions above; runtime gates still apply): Native Option mapping/labels must match new Home1/apps2–9 rule; General desktop retained-node soak fails equally on baseline and donor; do not hide it; Existing guest updater must deliver current UX alongside fresh image.

### queue-hat-sizing — parent-shared-dependency
Supplied native/setup hat included, not old hat.2 UX snapshot. Current shared web sizing/house/agent glyphs are parent UX pin.
Source: `4fbafd556ff1b33d4848b1fd2ad8bc606c3354cd`; `f4e5a7e0894f795233a392243cf2e29bfb3d78a7`.
Original audit notes (source resolutions above; runtime gates still apply): Guest image must include current icon meaning and sizing, not just native hat ICNS.

### queue-user-files — parent-shared-dependency
No local-only Files Browser UI copied; baseline Files routes retained; parent owns GitHub-backed shared Files API/source selection.
Source: `de9222cd97333149b4f20591508550f42c42d932`.
Original audit notes (source resolutions above; runtime gates still apply): Files folder view files-browser is James-box only with no GitHub remote; API source alone is not a packaged Files UI; Avoid blanket PR branch replacement: donor carries live Service deltas; preserve existing Mac Files route/permissions.

### agents-runtime — parent-shared-dependency
No native separate-agent import promised. Parent owns runtime driver, tokens, proxy/helper/images/mounts and isolated routing.
Source: `2dbcfcfd7e215f7fe2f59b29c40acb66aadbe3b2`; `1d9816fdfe82b53ed14f58ec0a05edba1df5d77f`; `2aed55db17a0189dcdb31f656e27a67f70862d1a`; `15799aa238fd4545a3517664956f47e67906ad0a`; `d486becf355587daa58b81409854910be5ad67cc`.
Original audit notes (source resolutions above; runtime gates still apply): Guest agent-runtime helper, container/proxy/images/token wiring need packaging and native guest acceptance; Bring My Hermes still replaces main; no implemented separate-agent import contract; Private routing must not fall back to main on stopped agent.

### resumable-sharing — parent-shared-dependency
No native Finder sharing added. Parent owns Service/UX agent-aware upload/private-share source and privacy verification.
Source: `848115c9f5691f0d6db82e991c28b931f9919846`; `5e05b906c64841dbec6eda1b05ab5633f44a191f`; `260f517954587a4cc7d34de894ef6e44dc2e527b`.
Original audit notes (source resolutions above; runtime gates still apply): Private-share live readability/isolation verification still pending per PR29; must not claim approved final delivery; Private destinations require selected agent-home and proxy, cannot leak into main/media; Android share intent receiver is not native Mac Finder sharing support.

### five-fixes — parent-shared-dependency
No shared Service/UX/WAM edits here; parent/shared lane must compose manual Continue and media/voice/screen/silence fixes and retain dispatch security checks.
Source: `0a12f43a1e0b81965c6a863952e381f24f2b96ee`; `84e7a4a5eee7a5f72cb7da44f890c22712363f8c`; `8f86086806d8dec1e7df437701a07d6b991646f8`.
Original audit notes (source resolutions above; runtime gates still apply): Independent dispatch/manual-marker security review on final composition; Donor recording harness14/22 with8 known AltRight mismatch failures; update harness without weakening acceptance; WAM Thales75pass/1fail/2skip fixed-port environmental failure reproduced baseline, not blanket green.

### modular-package — parent-shared-dependency
No topology/image swap in native source. Parent owns split-service payload and persistent-state acceptance.
Source: `81575409c23e289fd765834a5a5853b72dff85ee`; `84e7a4a5eee7a5f72cb7da44f890c22712363f8c`; `bc9e2ec0daa15cbf69349eeae5e5f8bf358055d2`.
Original audit notes (source resolutions above; runtime gates still apply): Requires selected image digests, runtime topology and migration, not just source merge; Do not replace bundled guest path with new split images without preservation test.

### prep-status — preserved-baseline
Existing setup status/auth race fixes retained; 15 existing Python setup tests and 7 JS race tests still pass after import route/branding integration.
Source: `e81fdad73c8efadd7bce6b37f7be6b70fc370de7`.
Original audit notes (source resolutions above; runtime gates still apply): No new separate integration required.

### github-download-check — partially-retained-ancillary
Base retains generic WKDownload probe. Retain 1f90762 quit-on-last-window delta; exclude old DownloadCheckLauncher/package-check.py that hardcode private mac-mvp-20261013 image URLs and 0.6.1 package defaults. Approved R2 replaces that private-download distribution workflow; no stale checker offered as this release.
Source: `1f90762533051b91982e9c2ce71e02ba74b15781`.
Original audit notes (source resolutions above; runtime gates still apply): Not part of native runtime; confirm whether still wanted as ancillary distribution tool.

### parked-existing-hermes — excluded-superseded
Do not merge c5b5076/fdd6059 or vsock relay/prototype path; selected product is c851bea backup/import.
Source: `c5b5076485133744b2208d723ee45b43c005133a`; `fdd6059776c6838c4755a9ccbcbf5e067a4b13ad`.
Original audit notes (source resolutions above; runtime gates still apply): No acceptance as supported final product; would create conflicting import/relay paths.

### future-qa-channel — deferred-explicit
No in-client QA channel activation, feed generation, or publication.
Source: .
Original audit notes (source resolutions above; runtime gates still apply): No implemented/authorized channel activation; staged Sparkle candidates are not human delivery.

### intel-and-always-on — excluded-unbuilt
No Intel binary/resource UI/disk/export/always-on roadmap claimed; native compilation is arm64/macOS14 target.
Source: `5b3b40abf5e45241928a3cd0f2a7762e6ae64d25`.
Original audit notes (source resolutions above; runtime gates still apply): Issues/spec labels are not built artifacts; no verified Intel binary or scheduled restore acceptance.

### android-everywhere — excluded-other-platform
Android processing/admission fix is not a built Mac port; native capture admission baseline preserved.
Source: `058942b80f7b6711efe79632300970df292467d5`.
Original audit notes (source resolutions above; runtime gates still apply): No Mac port implemented.

## Unresolved / parent dependencies
- Bluetooth default-mic avoidance has no safe completed MVP port; see bluetooth-input.
- No combined App/Host/VM update, restart, rollback, state-preservation or fresh-guest QA performed by this lane. Compile is not proof of any of these.
- No physical keyboard/fullscreen/title drag/mic/music/meeting/TCC acceptance. Source and fixture checks are not physical-event acceptance.
- Bring My Hermes replaces MAIN; imported CLI chat-list visibility remains a known donor gap; separate-agent import not implemented. Must recheck interruption/undo/archive validation and fresh/existing terminal key with exact WAM pins.
- Parent owns final shared UX/Service/WAM pins, factory image and existing-guest payload, native build/version freeze, signer/notarization, signed feeds/artifact sizes and any public publication.
- Hosting source dependency is resolved; fallback index GET200 is a placeholder page, not proof a final release or signed feed is published.
- Standalone old private-image checker package excluded deliberately; reusable underlying probe retained.
- Existing FINISHER-HANDOFF.md and suspect Host PID3117 were not modified/stopped by this lane.

## Issues encountered
- Hat build.sh conflicted with candidate Sparkle build: resolved by unioning inputs/resources, retaining required monotonic BUILD and candidate version (not donor 0.6.0/build2).
- Initial shared worker.lock probe was busy; no compile bypass. Later acquired nonblocking lock and compiled both native programs on Thales.
- Remote non-login PATH lacked node; native compile already succeeded; reran only JS checks via /opt/homebrew/bin/node. Remote system Python lacks aiohttp; HTTP fixture checks ran lightweight locally with isolated temporary HOME and no user data.
- Donor SSH migration would replace an explicit terminal key; added managed-route guard and tests before handoff.
