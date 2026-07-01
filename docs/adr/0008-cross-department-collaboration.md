# ADR 0008 — Cross-department collaboration: one shared brain, typed contributions, poison-safe curation

- **Status:** Accepted (2026-07-01) — amends ADR-0007 (promotion/write policy), builds on ADR-0003 (seat/Node/Central).
- **Relates:** `CONTEXT.md` terms **Contribution Type**, **Quarantine**, **Vault Contribution**, **Promotion Agent**, **Learning Process**, **Knowledge Conflict**, **New Org Project**.

## Context

Citadel was designed dev-first (git-push capture, repo-referenced promotion). A cross-department need surfaced (2026-07-01 grill): marketing, design, HR, finance — "everyone", most of them agent users — must share one org brain. Product feedback, ideas, campaigns, roadmaps, and design/brand specs must reach a shared, searchable store so any teammate's agent can discover across departments ("what are the campaign ideas for X?", "conform this UI to the current design").

The existing skeleton was already right — private seat **Node** → **Learning Process** → shared **Central**, governed by **Promotion** — but three things blocked the vision: "feedback" was overloaded, promotion was repo-centric (so non-code knowledge stranded on the Node), and capture assumed git.

## Decision

Everyone shares **one Central**; there are **no department scopes** (reaffirms the v1 decision — departments are people, not boundaries).

| # | Decision |
|---|----------|
| 1 | **"feedback" stays the QA/retrieval signal.** Product pain-points, ideas, campaigns, roadmaps, design/brand are **Vault Contributions**, distinguished by **Contribution Type**. |
| 2 | **Promotion is by Contribution Type, not only repo reference.** Typed non-code contributions (`idea`, `campaign`, `design`, `brand`, `pain-point`, …) may reach **Central** with no GitHub repo — extends ADR-0007 §5, which stranded no-repo notes on the Node. |
| 3 | **Topic areas (design/marketing/HR/finance) are filterable views over the one Central**, not separate stores. A "design node" is a Type/topic slice, not an isolated **Node**. |
| 4 | **Specs vs exploration.** Design/brand **specs** are canonical living documents (Source Material, indexed, agent reads the current version verbatim); ideas/pain-points are searchable contributions the agent synthesizes. |
| 5 | **Two-layer promotion filter.** A deterministic floor (`personal` tag + **Security Finding** / secret-scan) never reaches **Central**; the LLM filters *relevance* (org-related only) above the floor. The LLM guards relevance, never privacy alone. |
| 6 | **Poison-safe curation.** Content that connects to nothing in the **Knowledge Mesh** and matches no plausible project is an **Orphan Contribution** → **Quarantine**. Contradictions → **Knowledge Conflict**. New-but-plausible → a sparse **New Org Project** cluster. |
| 7 | **Deletion is never automatic.** An admin keeps/deletes quarantined items from the **Operations Dashboard** (yes/no) — agent proposes, human disposes (mirror of **Promotion Approval**). |
| 8 | **Non-dev capture is agent-mediated.** Deliberate **MCP** `citadel_ingest` + the user-scope **SessionEnd** hook; the git-push hook is a developer convenience, not the capture path. Non-devs onboard in a lean no-repo mode (token + user-scope MCP + SessionEnd, skip git hook / capture-roots). |

## Consequences

- **+** The vision is mostly a generalization of the existing pipeline, not a rewrite: Node → Learning Process → Central, plus a Type dimension, a Quarantine queue, and lean onboarding.
- **+** Broad (noisy) agent-session capture is safe *because* of the two-layer filter + Quarantine.
- **−** Build work (Release B): a **Contribution Type** on contributions + promotion routing by type; a **Quarantine** store + admin dashboard keep/delete + orphan/connectivity detection on cognify; a lean no-repo `citadel onboard` mode; a typed-contribution dashboard form.
- **Not built yet.** These are decisions. The current product (Release A: MCP search + capture) serves the team today; Release B implements the above.

## Open questions

- Exact **Contribution Type** taxonomy — fixed set vs LLM-assigned (the user leans LLM-assigned).
- Connectivity threshold that marks an **Orphan Contribution** for **Quarantine**.
- Whether canonical design/brand specs live in a repo (git) or a dashboard-editable doc for non-dev maintainers.
