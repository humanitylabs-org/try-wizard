# Assembly reference and exact engineering blockers

## What the previous 0.7.0 / build-307 actually did

Read on Thales under `Projects/wizard-desktop/mac-release-20261015` (external media):

| Retained reference | SHA-256 (small file read this turn) |
|---|---|
| `final-package/run-factory.py` | `1fbff60eed1cbba40962f124bc226b486f4f83fe594707c439a7286d66b7f2b2` |
| `final-package/seal-factory.py` | `63ce063f842081b6a06cf6c7b799924f22f0cd29cddad04e9f478d6a445bd4e1` |
| `final-package/wait-runtipi.py` | `85a3621b8970ac1b7a94b984cf94d90c341b83d88e3c4fc080b445f3404bb0d2` |
| `final-package/factory/result.json` | `c226d9b7eaae2b6e22e0c621f527692130d93808d3cfbb79bccdc34cc5fa4406` |
| `final-package/factory-sanitization.json` | `365cf030ded35349316f5f022b685f83e413c5fafc63f67c989d65c12967d972` |
| `FINAL307-HANDOFF.md` | `2fac4a7e27bc870f96e3b34b287e4affebb5d8a6dca073e3470ab9dfb2a99e7b` |

The retained factory runner is from the build-306 preparation, not a new build-307 factory rebuild. It cloned `guest-runtime/baseline-factory.img`, copied the retained boot checkpoint, booted an explicitly owned isolated host, mounted a shared payload, waited for Runtipi, applied `upgrade-mvp-stack.py`, refused any prior onboarding/accounts/sessions/agents, sealed identities and cleanly powered off. Receipt says `phase=sanitized`, host exited, original unchanged and lock released. Sources were native `f0a302329b39a8c14c028d70239543e062d0cb4f`, Service `24a2b3ac9e941c595bb60dc826b52c9308260c8e`, WAM `0696805fe000dfc616abd0cf772c52ff83d580d9`, UX `31bdc3ecb0586f61323b72227ab70506d2627e5d`.

The 307 handoff explicitly says **do not build a new VM/factory/native product** and **do not rebuild/re-publish OS 0.4.0**. It reuses retained runtime archives with matching sealed-manifest hashes in 306/307. It is not a missing standalone pins-only fresh bootstrap recipe waiting to be copied. Its old paths, payload sources, hard-coded localhost ports, candidate Host, baseline image and signing spec must not be relabeled as today's pins. No signer path or signing material was copied into this candidate.

## Launch source/default set frozen, executable bootstrap not yet frozen

`wizard-os-release-candidate.json` freezes the current stable **0.3.39**, read from WAM releases on 2026-10-24, plus exact reconciled WAM/Service/UX and proven portable Recorder selections. All eleven default rows have source commits. The old `wizard-os-stable.json` 0.3.38 remains historical context; it is not passed off as the current pointer.

The RC is deliberately an **unpublished source assembly-input record**, not an executable `get.sh` release record. Existing stable image provenance is preserved in `bootstrapImages`; candidate Service/UX output digests remain null rather than invented. WAM's official image-input paths have zero diff from its recorded image source (`db4325a`) to candidate `7a1f0fdc`; the freeze specifies this reuse condition instead of relabeling a new image build. The shell/Service source changes cannot be attributed to the old stable image digests.

## Remaining blockers, not a submit-ready build claim

1. **Complete assembly adapter still absent (`pins.json.execution=null`).** It must consume pins.json, materialize exact source archives, build/select the candidate images, generate a validated local Wizard OS runtime release, build or verify a digest-pinned pristine factory base, boot only an owned disposable VM, apply all source/host/runtime overlays, install the pinned Recorder with explicit device policy, seal fresh identity, clean shutdown/fsck, produce BOM and sparse archive. Retained `run-factory.py` only supplies the older clone/apply/seal segment. No new unexercised wrapper is represented as a working assembly.
2. **Bootstrap consumer still wrong.** `wizard-provision` invokes `get.sh` with `WAM_REF`, which explicitly chooses unpinned developer mode and bypasses release/default selection. Merely adding WIZARD_RELEASE while retaining WAM_REF does not fix it. Pass a validated generated release using WIZARD_RELEASE and a local immutable WIZARD_RELEASE_BASE, with no WAM_REF, then read back all default recipe and image identities. Source RC intent alone does not satisfy that contract.
3. **Mutable build toolchain and external inputs.** Current guest Dockerfile uses `debian:trixie` and live apt; build-image.sh also uses mutable Alpine/Debian helpers. Existing runtime shell base is a local image ID, not a portable staged base-image archive. Installer code invokes additional Runtipi/catalog inputs that are not exhaustively digest-pinned. A pins-only invocation cannot honestly be called all-inputs pinned until these transitive inputs are frozen or replaced by a verified pristine base archive. No multi-GB guest/base image was hashed or rebuilt on this conversational turn.
4. **84-row map now exists; not all rows ship.** `queue-mapping.json` identifies 59 source-carried rows, two superseded rows, one Android-only no-guest row and **22 not-fully-carried rows**. The latter are private/optional app recipes not selected, unproven legacy meeting-recorder equivalence, Service #64 absent from all three source allowlists, and image trust remediation. An explicit scoped exclusion is preferable to silently claiming a private app shipped. The mapping never converts ancestry to final guest acceptance.
5. **Security and appearance admission remain open.** Queue security row 81 needs actual updated trust stores/base selections and revoked-chain/image execution evidence. UX #472 retains seven protected failures, with exact source/differential/screenshot analysis in ux-472-review.md. Neither live deployment nor a screenshot is owner baseline approval. Existing final guest and physical-device gates remain unrun.

The guarded heavy descriptor remains available for the parent but is **not submitted and not rebuild-ready**: read-only audit must exit 2 with buildStarted=false. Making it exit 0 now would be a false positive. Signing stays unsigned/pluggable; no main merges, tags, feeds or release publication.

REUSE: proven clone/apply/seal flow, existing pin validator, guest updater, browser QA and unchanged appearance fixtures.
EXTEND: frozen source/default selection, queue source evidence, and fail-closed checks for their identities.
NEW: no replacement UI component; no fake assembly runner.
