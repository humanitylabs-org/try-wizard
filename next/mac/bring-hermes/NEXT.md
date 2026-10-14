# Bring My Hermes: alignment with the Agents MVP (before the next build)

James approved the Agents MVP on 14 Oct (wizard-os `spec/AGENTS.md`, PR #37; DECISIONS #43, #48 approved).
The tested import (r5 on Thales) restores into the box's `hermes-agent` Runtipi app. Before it ships:

1. **Entry point:** Agents app → Add agent → Import. The Mac menu item stays as a shortcut into the same flow.
   No Settings → Agents.
2. **Target:** write the imported agent as `agents/<id>/agent.json` schema 1 + `home/` (the restored Hermes),
   `harness: hermes`, `privacy: standard`, preset `standard`, runtime container `agent-<id>`. It then shows in
   `GET /wizard/v1/agents` (wizard-agent-service `feature/agents-mvp`).
3. **Main or secondary:** James wants an imported agent to be able to become main. Today the main agent is
   `id: "hermes"` and its state is never moved, so "make main" needs a decision in the Agents contract.
   Keep the current replace-the-box-agent path only as the "make it main" variant once that is decided.
4. Keep the r5 safeguards: filtered archive, Wizard wiring re-applied, messaging off, jobs paused, undo, the
   archive never in Files, the VM key re-tightened after Runtipi's start-time `chmod -R a+rwx`.
5. `AGENT_STATE.md` §9 is committed locally on `proposal/agent-state` (4e90eb7, not pushed). Rebase it onto
   main after PR #37 and point it at `spec/AGENTS.md` rather than restating the folder layout.

Briefs: ~/projects/wizard-os-integration/briefs/agents-mvp.md, agents-mvp-round2.md.
