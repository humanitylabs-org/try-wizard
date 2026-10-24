# Build-307 retained-factory assembly adapter — launch input checkpoint

## Recipe decision (launch owner instruction, 2026-10-24)

Do **not** wait for a new pins-only fresh factory. `assemble.py` clones the exact retained build-307/OS-0.4 factory, installs the frozen source RC with WAM #204, and applies the Mac-specific layers. It never calls `build-image.sh all` or rebuilds the Debian/Alpine factory base.

The original 307 handoff prohibited rebuilding during that **older** release. It was provenance evidence, not a prohibition on this newly authorized significant release. Original v3/v4 freezes remain untouched.

## Actual retained input, read back on Thales

Relative to `$THALES_MEDIA/Projects/wizard-desktop/mac-release-20261015`:

| Input | SHA-256 |
|---|---|
| `final-package/factory-publish-source/rootfs.img` (17,179,869,184 bytes) | `64ddc2b8123b3185668aab666cd93843a228d769a2ab55c68e64e00a4c1f1366` |
| `final-package/factory-publish-source/boot/vmlinux` | `5028c424ee9fd0f4d18c38269122e30e3d084deb1b13404ab070a3f478ddd30a` |
| `final-package/factory-publish-source/boot/initrd` | `b32a28fd79ea7cedea49520befe694f513fb35af53203074006a016128c3c06b` |
| retained native-303 `Wizard Host` executable (disposable factory transport only) | `799b1618496aaa0aa7040c87913c0870662ecfde3a0a5a588f874015bf861bb0` |

The complete 16-GiB rootfs SHA-256 was calculated this turn, not copied from an old receipt. Boot identities match the retained sealed manifest. `pins.json.assembly` records these inputs with portable `${THALES_MEDIA}` paths; the parent submit descriptors supply the exact mount. The old host is **not** relabelled as the new native candidate.

Retained scripts read as reference, not executed: `run-factory.py` `1fbff60eed1cbba40962f124bc226b486f4f83fe594707c439a7286d66b7f2b2`; `seal-factory.py` `63ce063f842081b6a06cf6c7b799924f22f0cd29cddad04e9f478d6a445bd4e1`; `wait-runtipi.py` `85a3621b8970ac1b7a94b984cf94d90c341b83d88e3c4fc080b445f3404bb0d2`.

## Implemented adapter

- Verify the base/boot/owned Host hashes, refuse occupied dev-shell ports and insufficient external-volume space, clone with APFS CoW, boot **only** the owned disposable data home.
- Refuse account/onboarding/session/agent state before installing anything.
- Generate a get.sh-compatible local release from actual pull-verified candidate image receipts; validate selected source commits/digests and the sha256-pinned archived `get.sh` before first execution.
- Install with explicit `WIZARD_RELEASE`, immutable local `WIZARD_RELEASE_BASE`, `WIZARD_STRICT=1` and explicit image digests. Remove `WAM_REF` and inherited image overrides. Read back the WAM commit, installed release pins, strict `release.json` result, default-source verification and running core images.
- Apply the frozen native overlay, selected Service agent-runtime package, managed-stock runtime contract, product plugin, import/phone/runtime wiring. `wizard-runtime-configure` supports the selected split Service and retains the old combined topology for existing guests.
- Require TLS checks on the guest host and every running container; DNS/network errors are not evidence of revoked-chain rejection. Seal only the pristine guest, remove recipient identity/secrets, shut down cleanly, and exit only this spawned Host.
- Offline fsck; check sealed machine identity/WAM source; zero free blocks while verifying allocated bytes remain identical; emit BOM/manifest and archive, then stream-read/hash its actual members.

The recipe's `--plan` and fail-closed source contracts have been exercised. **No clone, VM boot, get.sh install, container build, seal or package operation has been executed this turn.** Implementation is staged for the parent, not represented as a previously proven new guest build. Signing is unsigned/pluggable, with no signing material copied.

## Candidate images and source verification

`package-image.py` has one parent-only light job per reconciled WAM/Service/UX image. It freezes external FROM manifests before building, records the rendered Dockerfile, updates trust stores, uses patched Node/Bun for WAM, runs real TLS checks, and pushes **by digest only** using an isolated ephemeral Docker config. It reads the exact digest back and pulls/inspects architecture/source labels before writing a receipt. It does not write `latest`, a version tag, a Git tag, an OS release or a feed. Existing GH package-write permission must actually work; a denied push is a failure, not a fake output.

Only the three missing reconciled output digests are `TODO_BUILD_OUTPUT_*`. Historical stable digests remain historical. `resolve-images.py` adopts actual image receipts into `pins.json` and the executable RC only after source/security receipts pass; it preserves pre-resolution metadata and refuses changed immutable source inputs. Parent must commit/read back the resulting manifest on the named branch before build approval.

`verify-sources-v5.py` runs the **full** Service/UX/WAM suites inside digest-pinned Linux arm64 Node, with `/work/t` and traversable temp permissions (GNU Bash, `/proc`, uid1000). Native Swift admission and source contracts still run on the Mac host. This replaces neither assertions nor failed v3 evidence with a green claim. The old v3 full-suite failure remains historical evidence; v5 has not been submitted.

## Queue and appearance decisions

All 84 original rows/text/line order are retained. Of the 22 previously uncarried rows:

- **Carry 23**: accepted live UX orb/app-badge behavior. Corrected the prior erroneous recorder-related classification.
- **Carry 80**: Service #64 (`d2aefaaf` cherry-picked as `15d501a`), all three CLI/TUI allowlists plus its regression test; exact-head CI green.
- **Carry 81, mandatory security gate**: never deferred. Actual all-image remediation/verification is still required below.
- **Defer 19** optional/private/legacy-unproven app scopes to next release, each with its own one-line reason in `queue-mapping.json`. The portable Recorder is not falsely treated as equivalent to every old local Meeting Recorder behavior. No device/capture grant is implied.

Aggregate: 61 source-carried, 1 mandatory carried security gate, 19 deferred, 2 superseded, 1 Android/no-guest change. Source carriage is not final guest acceptance; the rebuild queue is not cleared.

UX #472 accepts the explicit launch-owner decision that live `8fa9804` is the baseline. Five owner hashes and two dock assertions now guard that live baseline, including a full core CSS SHA-256; no product CSS/JS changed. Exact selected head `e1bc34fa` has green CI, including `shared-features` run `40120979667`. See `ux-472-review.md`, the PR body and the existing candidate/baseline/live screenshots. These remain targeted phone-dock evidence, not whole-release acceptance.

## Remaining blockers — exact names

1. **`IMAGE_DIGESTS_PENDING`** — WAM/Service/UX packaging jobs have not run. No new output digest is fabricated.
2. **`SOURCE_VERIFICATION_V5`** — the new exact-pin Linux/Mac full-source job has not run.
3. **`SECURITY_IMAGE_CLOSURE`** — substantive remaining engineering/execution, not just a flag: three patched core outputs alone do not remediate all inherited/default containers, stock/managed Hermes, Python/certifi/vendor copies and Node. Read-only offline Docker repositories and all pinned default compose recipes were collected into `evidence/build307-image-repositories.json` and `evidence/default-image-recipes.json`. `security-image-plan.json` records their real manifests/local-image gaps, but deliberately remains `complete=false`. Those remaining surfaces need immutable remediated selections (or proved safe retirement), application wiring and actual good/revoked/no-CT client tests before the security/resolve/rebuild tail can run. Do not turn this boolean on to bypass the work.

Primary security source: <https://emudhra.we-have-a-problem.com/>. Patched minimums include Alpine CA `20261020-r0`, certifi `2026.10.19`, Node 22 `22.23.4`, Bun `1.4.4`; tool/runtime/vendor stores must be inventoried, not assumed covered by host curl.

Admission currently exits **2**, with `buildStarted=false`, `publishing=false`. It requires actual source/image/security/UX-CI receipts and checks staged identities/recipe/installer/Service-64 file hashes. Contract tests exercise each missing receipt and a malicious bare-factory argv; no synthetic unit fixture is represented as real acceptance evidence.

REUSE: retained clone/apply/seal flow, WAM release installer, existing product/runtime overlay, source/full test suites and owner/collaborator guards.
EXTEND: exact immutable base adapter, split-Service runtime selection, explicit queue decisions, accepted guarded live baseline and fail-closed receipt checks.
NEW: no UI component, no alternate brain, no main merge, no publisher.
