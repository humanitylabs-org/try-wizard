# Canonical WAM route for normal voice-image update

REUSE: WAM's installed CLI (`install.sh`: `cd "$HERE" && exec "$PY" -m wam`) and API WorkingDirectory use the owning checkout. The guest provisioner installs it at `/home/wizard/wizard-app-manager`. No new lifecycle implementation, environment/provider fallback, dependency installation or search-path injection is introduced.

EXTEND: normal selected-image update/recovery now preflights that canonical directory with the same wizard user, HOME and system interpreter used for stop/start. Reject missing, redirected, writable or foreign-owned paths before acquiring/creating the update lock or writing journal/fence/service state. Ignore Python environment/user-site imports and suppress bytecode writes. Both ordinary and automatic rollback receive the same preflighted route. If recovery also fails, retain the original exception as primary with the recovery exception chained, leaving its journal/fence evidence.

The exact source-bound first-installer diagnostic proved the missing import only for that diagnostic generation. It does not retroactively establish the cause of the earlier historical rc=1.

## Focused source admission

`voice-wam-source-forum.py` is parent-admitted on Forum's light lane only. It runs exactly:

- `test_voice_update`: 9 existing affected transactions, with only canonical source fixture setup extended.
- `test_voice_wam_route`: 12 narrowly targeted cases, including a real Python subprocess reproducing missing WAM from unrelated cwd, real imports and fake WAM lifecycle requests, preflight refusals before mutation, normal/automatic rollback route equality and primary/recovery error preservation.
- `test_voice_image_acceptance`: 10 no-VM cases for safe evidence capture, completion binding, lexical globals and actual non-preflight result construction.

All systemd/Docker effects are faked. The real subprocess adapter verifies the exact sudo/user/HOME/interpreter/cwd/argv and replaces only privilege switching to run the fake package as the test user. These are not installed-guest, native transcription or TLS proofs. No broad 75+15 source suite or unchanged TLS tests are rerun.

## Full native acceptance admission

`voice-image-acceptance.py` preserves the full prior ordinary selected-image install, idempotence, three normal Retry requests, synthetic blue-lantern/window transcription, ordinary rollback, exact state restoration and inert Retry/service activation after rollback. Each installer command now retains bounded secret-safe streams, exact raw byte/hash identities and trusted source frames before enforcing exit/timeout.

`voice-image-acceptance-thales.py` requires an actual completed focused-source job, exact native receipt/log/result and stage/spec/source identities BEFORE native admission, archive construction or clone creation. The parent supplies a separately sealed completion in the runtime stage's sibling `-admission` directory; a template is not a completion. Read-only `--preflight` cannot accept runtime or source proof. It reuses the existing secured image/security evidence unchanged, with a separately inventoried one-file derivative code overlay. It never edits/repackages the accepted image or rewrites its descriptor. Only a parent-admitted ordinary installer may load that same accepted image into a fresh disposable clone.

Passing requires real ordinary transcription, Retry, rollback, clean production stop, current boot witness, descriptor closure and exact baseline metadata preservation. No owner activation, publication, image build/import or reuse of a failed mutated clone. Existing generation failures and receipts remain intact.
