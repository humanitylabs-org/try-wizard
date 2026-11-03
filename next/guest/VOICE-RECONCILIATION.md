# Local voice reconciliation candidate (not runtime acceptance)

REUSE / EXTEND: WAM install/start lifecycle, existing `wizard-voice` unit and
Retry endpoint, native overlay, authenticated code-only runtime payload and
`upgrade-mvp-stack.py`, and the final security factory writer. No new frontend,
agent core, provider, model, VM implementation or image-store owner. There is no
COMPONENTS.md in this repository; the shared Service component inventory was
read; no Service implementation is copied here.

## Ownership

`voice/reconcile.py` is the one selected-engine contract writer/schema. Final
factory derives it from **the final security plan and actual compose bindings**.
The normal payload sealer carries the same canonical record and covers it with
the existing runtime BOM. The coordinator cannot derive an image from Hermes.
The selected manifest in this candidate is derived from the r5 frozen security
plan, not a new pin: engine fe0bde304023..., helper 242ebd26a806....

Known legacy override migration restores **both** security-selected helper and
engine images. Unknown fields, including tighter/custom settings, are refused
without changing their bytes; nothing is silently dropped. Read-only source
fixtures cover this conservative policy. Old code and selected bindings have a
bounded component backup. Rollback restores bytes/modes/ownership with the old
coordinator disabled: a timer/Retry cannot activate an obsolete writer.

`voice/install.py PAYLOAD --apply` is the production component transaction used
by the normal stack upgrader and final factory writer. PAYLOAD must be inside
the existing authenticated update/preparation boundary; this is not a new trust
or distribution channel. `--rollback` is the component rollback entry. It never
mutates an image store or starts/replaces an engine. Retry uses WAM, not a
handwritten Docker command. Multiple processes share a stable flock inode.

## Runtime gate and current boundary

This is a repair candidate, **not a working Parakeet claim**. Health uses the
actual Speaches `{"message":"OK"}` contract. A model name is insufficient:
readiness additionally checks pinned revision/INT8 model bytes and a compatible
Parakeet loader, a loaded model, and image identity before/after probes. Failure
is bounded/actionable, with fixed public summaries, no provider/model fallback.
The immutable image and all existing security source pins remain unchanged.

The upstream v0.9.0-rc.3 tag resolves to
24f209c90218187747a9205f0b84bc06b42ce775. It includes a Parakeet executor, so it
is incorrect to say Speaches lacks Parakeet. Its exact shipped container still
needs inspection before deciding whether pinned INT8 is supported. The current
read-only loader/revision gate deliberately refuses an unverified graph rather
than reporting ready from a health/model list. No new image or model download
is authorized by this component transaction.

Parent-owned consequential proof must inspect the shipped immutable image and
model/runtime ABI, then either prove a synthetic transcription through normal
Wizard local voice or build a compatible hardened packaging-only voice image
through the existing security plan if the exact image cannot meet the pinned
contract. A changed image requires its own selected-image/security closure; this
installer refuses silent selection changes. No full guest rebuild is warranted
merely for these code changes. The unchanged production VM core and pristine
baseline must be reused, never the Retry-mutated r4 disk. A fake source test
passing is not runtime, upgrade, rollback, native UX or transcription acceptance.
