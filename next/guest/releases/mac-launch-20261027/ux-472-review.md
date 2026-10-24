# UX #472 protected-appearance review (2026-10-24)

Candidate: `69cb20679e46477a0c1a74a006eec733dd99b284`.
Frozen main comparison: `08d6ecc17a76ce0999bc4017222ba00135e15167`.
This is the main baseline used by the launch freeze, **not a claim that main stopped moving** (local origin/main now also contains `dcfee5c4b75251b1c15cb441694b3ad3fce941aa`).

## Exact seven protected failures

| Unmodified assertion | Expected main fixture | Candidate actual | Cause |
|---|---|---|---|
| `James's nebula skin is unchanged` | `3bd6f1bb5473f77f` | `1a9173933fd7cbce` | Explicit Nebula selectors added in core/skins.css; global dock breathing rule also scoped away from collaborator skins |
| `James's grove skin is unchanged` | `7a28f6d0e952b2d9` | `04869c101ef49d46` | Same owner-family orb selectors |
| `James's tide skin is unchanged` | `9e70f67f23e47f15` | `c3cdc648129686be` | Same owner-family orb selectors |
| `James's ember skin is unchanged` | `47178b9243aa389a` | `f8fb1091c187cb11` | Same owner-family orb selectors |
| `James's signal skin is unchanged` | `e71f86e31185108c` | `8b1f66c98ff178f0` | Same owner-family orb selectors |
| `only Miguel's skin packages style the pill dock and show #orbApp` | No `.orb-app` in core stylesheets | `skins.css must not style .orb-app (skin-only)` | Owner-family desk icons now intentionally style #orbApp in core/skins.css |
| `only our skin packages style the symmetric dock and the orb X` | No `.desk-dots.sym`, `.dnew`, `data-sheet="launcher"` in core CSS | `core/skins.css must not carry our skins' dock` | New `.dock .ddot:not(.dplus):not(.dnew)` breathing selector contains `.dnew`; this lexical assertion fails even though the selector excludes new-desk buttons and the rule excludes Obsidian/Light/Landscapes |

The last assertion is broader than the visual behavior it is trying to protect. It is still a genuine failed unchanged contract, not a reason to edit or suppress the test. The other six directly contradict the old owner/skin-only visual policy and require a policy/owner decision.

`3a0c6a45` intentionally adds white current-desk glyphs inside all five Wizard-family orbs, a ring and recording fade. `4defd354` intentionally unifies the breathing/hover glow of dock controls and scopes it away from collaborator skins. Both are ancestors of the candidate's preserved live branch, not fresh accidental styling introduced by this reconciliation. `core/skins.js` owner definitions and `core/base.css` are unchanged.

**Verdict: intentional live-vs-frozen-main differences; not approved baseline changes.** Their presence on the owner's live system is evidence of behavior, not proof of explicit owner permission to update protected fixtures. Keep #472 draft and the appearance gate open. No fixture/test was changed.

## Real Thales execution and screenshots

Evidence root: `$THALES_MEDIA/QA/mac-launch-472-review` (exact retained location in PR body).

- `protected-assertions.log`: candidate three protected files, exit 1, seven failures.
- `main-protected-assertions.log`: exact frozen-main three protected files, exit 0.
- `candidate/result.json`: read-only browser probe against daily API with exact frozen candidate assets, **19/19 checks pass**.
- `baseline/result.json`: same probe, exact frozen-main assets, **17 expected feature assertions fail**, two pass. This probe checks the new behavior; its failures against main are a differential witness, not newly discovered main regressions.
- `live/result.json`: un-overridden daily assets, **19/19 checks pass**. All non-GET/HEAD requests were aborted in these browser probes; desk navigation is browser-local only.
- `owner-file-hashes.json`: current live files are **not all byte-identical** to the candidate. `core/skins.js` and `core/base.css` match all three; `core/skins.css`, `core/chats.css` and `app.js` have advanced on live. Do not claim full final-head live parity from these targeted probes.

For **each** of `nebula`, `grove`, `tide`, `ember`, `signal`, `obsidian`:

- `candidate/<skin>-home.png`
- `baseline/<skin>-home.png`
- `live/<skin>-home.png`

Additional `candidate/nebula-app.png`, `baseline/nebula-app.png`, `live/nebula-app.png` show desk-change glyph behavior. These are phone dock crops, not full-shell, desktop, onboarding, physical device or guest acceptance.

Human inspection of Nebula candidate/baseline confirms the central orb gains a white Home icon; the baseline is the same purple orb without that icon. Obsidian retains its separate grayscale pill treatment and Home glyph. No new icon overlap is visible in the inspected Nebula crop; Obsidian's outer ring reaches beyond the crop, so the crop alone cannot establish full viewport clipping safety. Do not call this whole-release two-skin acceptance.

REUSE: existing `tools/qa-orb-desk-icon.cjs`, unchanged guard files and fixtures.
EXTEND: review evidence and differential execution only.
NEW: no UI implementation or parallel component.

## Launch baseline decision (2026-10-24)

Archimedes, owner of this launch, explicitly directs: live `8fa9804` is the accepted baseline; James's running install is the merge gate. The five owner hashes and two core dock assertions now accept that behavior. Core CSS is SHA-256 guarded, not exempted from regression testing. Source CSS/JS is unchanged by this acceptance. Screenshots above remain targeted phone-dock evidence, not whole-release acceptance.
