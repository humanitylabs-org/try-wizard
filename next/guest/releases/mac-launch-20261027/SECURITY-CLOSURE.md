# Mandatory image trust closure — Mac launch 2026-10-27

**Engineering selection is complete; runtime acceptance is deliberately not asserted.**
`security-image-plan.json` is schema 2, selects 17 immutable image targets, and remains
`complete: false` until real packaging receipts and 05's actual TLS probes pass.
No security row is deferred. No image/guest build or publication was executed by this change.

## Per-finding disposition

| Finding | Concrete resolution / source | Required evidence |
|---|---|---|
| OS roots, OpenSSL/Go clients, hashed CAPATH | All 14 inherited/default/stock targets are derived with `remediate-trust.py`: remove the four primary-advisory fingerprints from every discovered PEM/CRT, disable the Debian emSign/Comodo roots, and upgrade the image's CA package. The three existing core packaging outputs are independently tested, not presumed safe. | Each real packaging `remediation.json`, then 05 curl healthy controls and all 14 affected chains. Curl failures must be code 60, not DNS/timeouts. |
| Python system and venv TLS / incident Python releases | Preserve the admitted Linux interpreter ABI and absolute paths. Apply the *actual upstream incident fix*: hash-locked pip **26.2.2** and certifi **2026.10.19**, including `ensurepip/_bundled/*.whl`; do not swap unrelated interpreter binaries and invalidate managed-launch guards. | [Python release team's explanation](https://blog.python.org/2026/10/python-3151-3149-31317/) explicitly says these releases upgrade bundled pip/certifi. `pipRemediation` lists installed and ensurepip copies; every distinct interpreter and context is probed. This is a patched component, not a Python deferral. |
| certifi / pip vendor / venv vendor | Replace actual certifi source and CA files from the hash-locked official wheel in every discovered copy, including `pip/_vendor`. Upgrade actual pip package files and ensurepip bootstrap wheels; remove stale metadata/bytecode. | Real wheel smoke imported `pip=26.2.2`, `certifi=2026.10.19`, `pip._vendor.certifi=2026.10.19`; 05 checks each bundle and all bootstrap wheels. No package version is merely relabelled. |
| Node built-in roots | Copy same-major fixed Node **22.23.4 / 24.22.1 / 26.12.1** from architecture-specific, registry-verified digests, selecting glibc/musl correctly. | `security-upstream-inputs.json` records queried tags, real arm64 manifests and response hashes. 05 uses per-major minimums: old Node 26.5.1 does **not** pass a loose “>=22” gate. Each Node HTTPS client gets healthy and all-14-chain probes. |
| uv / native Claude Code bundled roots | Copy fixed uv **0.13.5** from its immutable manifest; when Claude Code is present, install pinned **2.1.303**, preserving the original app entrypoint, command, user and source labels. | Primary advisory thresholds, actual inventory, final binary versions and digest-pull readback. OS roots alone are not accepted as these binaries' remediation. |
| Retained slim/managed Hermes, old local shell and WAM | Replace with selected patched identities; managed guard packaging derives from the patched stock identity. Persist default/helper/infra overrides, rerun after final configuration writers, verify actual running IDs, then prune unused old containers/images/build cache **only in the pristine disposable guest**. | `security-application.json` lists exact writes/running/retained IDs and refuses any unplanned image. No invented manifest digest for an old local image ID. |
| Guest host, mounted/custom trust stores, configured runtimes | Apply the same CA/pip/vendor/ensurepip fix to the guest host. After all configuration writers, repeat through `docker exec` in every running container, including mounted environment-specific CA bundles. Headless Chrome is exercised separately; curl is not browser evidence. | `security-guest.json` host plus actual container checks. It is distinct from image preflight and remains a rebuild/sealing gate. |

## Concrete image jobs

The existing **01–04** jobs are not duplicated. After those finish:

1. `04r-activate-security.json` activates the separately staged security preparation,
   verifies all original source hashes, preserves the previous preparation, and runs the
   light admission tests. Runtime source commits remain unchanged.
2. `04s-01` through `04s-14` derive, in order:
   `helper-python`, `hermes-app`, `chatgpt`, `claude`, `files`, `transcriber`, `browser`,
   `secrets`, `notifications`, `recorder`, `stock`, `postgres`, `rabbitmq`, `traefik`.
   Each job is exact JSON in the control-plane `submit-jobs-v5/` and `PENDING-SUBMITS.md`.
   No mutable tag or release publication is requested; digest-only packaging outputs are
   read back and pulled before a success receipt exists.
3. Updated **05** loads the 14 real receipts plus the existing three core outputs,
   validates the exact selected bases/source commits, and probes all 17 identities.
   Only a successful real run writes `complete: true`, the exact image set and a
   plan-hash-bound `security-preflight.json`.
4. Existing **06** adopts those actual identities into the runtime release and stock
   build input. It cannot launder modified staged sources or substitute old digests.
5. Existing **07** remains separately authorized/conditional; nothing here runs it.

Files is specifically **not** an apt/apk image: a read-only Thales check found a
BusyBox/static-Go rootfs without `/etc/os-release`. Its explicit recipe copies the
already-patched helper's TLS/Python tools, retains Files' app/entrypoint/user, and
scrubs its original stores too. `helper-python` must package before Files.

## What is verified now

- 42 control-plane contract tests passed; these are not VM or TLS acceptance.
- Both fixed wheels were downloaded from official URLs, SHA-256 verified, and exercised
  in an isolated tree; actual imports reported `26.2.2 2026.10.19 2026.10.19`.
- All six Node platform/major inputs and fixed uv have real arm64 registry digests.
- Frozen default recipe blobs produced 17 actual service bindings (eight shared Python
  helpers plus nine app engines); no service names were guessed.
- Read-only cached-image checks identified old helper pip 25.0.1, transcriber uv 0.8.22,
  and the minimal Files rootfs. Missing local references remain “not locally present”,
  never “safe”.
- Source pins are unchanged; no merge to main, image build, guest rebuild or release
  publication was performed.

## Is 05 expected to pass?

**The unconditional plan blocker is removed in code. 05 is ready to attempt after
activation and all named packaging jobs produce real passing outputs. It cannot pass
now, and no actual 05 result is claimed.** Missing/pull-failed outputs, stale runtime
versions, a browser/client accepting any compromised chain, or inconclusive network
errors still fail it. Docker Hub returned 429 on Thales during metadata discovery;
control-plane registry retrieval verified the pins instead. Parent packaging must
have working registry access (or wait for the limit/authenticated route), not bypass
TLS or treat a pull error as security closure.
