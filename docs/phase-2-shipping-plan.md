# Phase 2 Shipping Plan — Autonomous Sync + Graph

Last updated: 2026-06-25.

This plan tracks everything agreed in the Phase 2 design session: background
autonomous capture into seat **Nodes**, Linear → **Central** with **Seat-Scoped
Mirrors**, and graph UI Phase 2. Goal: zero extra dev steps; agents get context
via MCP.

**Execution checklist:** [`tasks.md`](../tasks.md) (sequential M0→M6 todos).
Update milestone **Contributes** % in the table below as checkpoints close.

**Design principles (locked)**

- **Autonomous Node Sync** — background, fail-silent, no developer action per capture.
- **Git push** — universal baseline (Cursor, Codex, Claude).
- **IDE session hooks** — supplementary where the platform supports them (Claude `SessionEnd` today).
- **Linear** — full workspace → **Central**; assignee issues also **mirrored** into that seat's **Node**.
- **MCP** — agents read Node + Central; humans never manage sync manually.

---

## Overall progress

| Milestone | Weight | Status | % of milestone | Contributes |
|-----------|--------|--------|----------------|-------------|
| M0 Graph Phase 1 | 15% | **Done** | 100% | **15%** |
| M1 Git push sync | 25% | Not started | 0% | 0% |
| M2 Session hook coverage | 10% | Partial | 30% | **3%** |
| M3 Linear backend sync | 20% | Not started | 0% | 0% |
| M4 Linear MCP + skills | 10% | Not started | 0% | 0% |
| M5 Graph UI Phase 2 | 15% | Not started | 0% | 0% |
| M6 QA, merge, deploy | 5% | Not started | 0% | 0% |
| **Total** | **100%** | | | **~18%** |

Update the **Contributes** column as checkpoints close. Target: **100%** before calling Phase 2 shipped.

---

## M0 — Graph Phase 1 ✅ (100%)

**Branch:** `feat/graph-logseq` (commit `a2770e0`)

| Checkpoint | Done |
|------------|------|
| Vendored `force-graph`; removed Three.js | ✅ |
| Central hub, seat tiers, hover/click, labels | ✅ |
| Activity ↔ Knowledge graph toggle | ✅ |
| Docs + commit | ✅ |
| Merge to `main` + production deploy | ⬜ |

**Exit criteria:** PR merged; production serves `force-graph.min.js`; Activity + Knowledge modes work in browser.

---

## M1 — Git push sync (0% → target 100%)

**Delivers:** Every `git push` (or post-commit on push) snapshots commit metadata → seat **Node**.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 1.1 | Define snapshot payload (hash, message, author, branch, changed paths, repo) | 0% | Spec in script docstring |
| 1.2 | `sync_push.py` — stdlib POST to `/ingest`, same contract as `sync_session.py` | 0% | Unit tests pass |
| 1.3 | Git hook template (`post-commit` or `pre-push`) + skill install docs | 0% | One `npx skills add` wires hook |
| 1.4 | Reuse `CITADEL_MCP_ACCESS_TOKEN`; no `dataset` field → private Node | 0% | Ingest lands in `seat:{slug}` |
| 1.5 | Fail-silent, HTTPS-only, size cap (match session sync) | 0% | Hook never blocks push |
| 1.6 | Integration test + manual E2E (push → search Node) | 0% | Marker commit findable |

**Suggested PR:** `feat(sync): git push commit snapshot to seat node`

**Depends on:** nothing (extends existing proactive-ingest skill).

---

## M2 — Session hook coverage (30% → target 100%)

**Delivers:** Session distill where IDE supports it; git push remains universal fallback.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 2.1 | Claude Code `SessionEnd` → `sync_session.py` | **100%** | Shipped PR #4 |
| 2.2 | Document git push as universal path in skill + onboarding | 0% | `citadel-autosync.md` updated |
| 2.3 | Cursor — research exit hook / rule pattern; template if viable | 0% | Doc or template in skill |
| 2.4 | Codex — same as 2.3 | 0% | Doc or template in skill |
| 2.5 | Shared `citadel-proactive-ingest` skill: one install, git + session | 0% | Single setup story |

**Note:** M2.3–2.4 may stay doc-only if no stable hook API exists; git push (M1) still satisfies "works everywhere."

---

## M3 — Linear backend sync (0% → target 100%)

**Delivers:** Linear workspace → **Central**; assignee issues **Seat-Scoped Mirror** → each **Node**.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 3.1 | ADR or plan section: Central + Mirror routing (read-only Linear) | 0% | Aligns with `CONTEXT.md` **Seat-Scoped Mirror** |
| 3.2 | `kb/linear_sync.py` — fetch issues/projects via Linear API | 0% | Mocked tests |
| 3.3 | Config: `CITADEL_LINEAR_API_KEY`, optional team filter | 0% | `kb/config.py` + Railway env doc |
| 3.4 | Ingest org-wide digest → `masumi-network` (Central) | 0% | Central search finds issue titles |
| 3.5 | Mirror assignee issues → `seat:{slug}` per seat mapping | 0% | John's token search finds only his issues in Node |
| 3.6 | Seat ↔ Linear user mapping (email or admin config) | 0% | Assignee resolution tested |
| 3.7 | Run mode / admin endpoint / cron (`CITADEL_RUN_MODE=linear-sync`) | 0% | Manual + scheduled run |
| 3.8 | Tests (`tests/test_linear_sync.py`) | 0% | pytest green |

**Suggested PRs:** `feat(linear): sync workspace to Central` then `feat(linear): seat-scoped mirror`

**Depends on:** `CITADEL_LINEAR_API_KEY` from operator.

**Supersedes:** `organization-vault-plan.md` Phase 3 ordering for Linear — pulled forward per 2026-06-25 design session.

---

## M4 — Linear MCP + skills (0% → target 100%)

**Delivers:** John asks agent "what do I need to do?" → MCP reads mirrored Node (+ Central fallback).

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 4.1 | MCP tool: list my issues (seat-scoped, from Node mirror) | 0% | `citadel_linear_my_issues` in `tools/list` |
| 4.2 | MCP tool: org issue search (Central, reader+) | 0% | Cross-team query works for admin |
| 4.3 | Wire audit + scopes (`kb:read`, seat token) | 0% | Audit event on call |
| 4.4 | Update `citadel-vault` / connector skills | 0% | Skill docs list Linear tools |
| 4.5 | On-demand refresh optional (trigger sync before read) | 0% | Stale cache documented |

**Depends on:** M3.4–M3.5 minimum.

---

## M5 — Graph UI Phase 2 (0% → target 100%)

**Delivers:** Graph useful once Nodes have content — scope, depth, spokes.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 5.1 | Scope filter: My Node / Central / Both | 0% | Filter toggles visible nodes |
| 5.2 | Local graph + depth slider (1–3 hops from selection) | 0% | Click node → neighborhood |
| 5.3 | Explicit Central ↔ `seat:` vault spokes | 0% | Visual hub links |
| 5.4 | Mode parity (Activity vs Knowledge where metadata allows) | 0% | Knowledge assignee nodes filterable |
| 5.5 | Browser QA checklist | 0% | Fit, pause, mode switch, mobile |

**Depends on:** M0 merged; richer Node content (M1/M3) makes QA meaningful — can start 5.1–5.3 in parallel.

---

## M6 — QA, merge, deploy (0% → target 100%)

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 6.1 | Merge `feat/graph-logseq` → `main` | 0% | PR approved |
| 6.2 | Full pytest suite | 0% | 328+ passing |
| 6.3 | Staging/prod: re-cognify if needed; Linear key set | 0% | Knowledge graph non-empty |
| 6.4 | Update `docs/progress.md`, `tasks.md`, README | 0% | Phase 2 marked shipped |
| 6.5 | Teammate rollout: token + skill + git hook one-pager | 0% | Onboarding tested |

---

## Recommended ship order

```
M0 merge ──► M1 git push ──► M3 Linear backend ──► M4 Linear MCP
                    │                                    │
                    └──► M2 session docs/hooks ──────────┤
                                                         ▼
              M5 graph Phase 2 (parallel after M0) ──► M6 deploy
```

1. **Week 1:** Merge graph Phase 1 (M0.4) + ship git push sync (M1).
2. **Week 2:** Linear backend + mirror (M3); start graph scope filter (M5.1).
3. **Week 3:** Linear MCP (M4) + graph depth/spokes (M5.2–5.3).
4. **Week 4:** QA, docs, production rollout (M6).

Adjust if Linear API key or seat↔user mapping blocks M3.

---

## Verification checklist (final gate)

- [ ] John pushes code → issue/findable note in his **Node** without manual ingest.
- [ ] John closes Claude session → distill still lands in **Node** (existing).
- [ ] Linear sync runs → issues in **Central**; John's assigned issues in his **Node**.
- [ ] John asks agent via MCP → task list from **Node** mirror.
- [ ] Graph: scope filter + local depth around a node.
- [ ] All failures fail-silent; push/session never blocked.

---

## Open items (resolve during build)

| Item | Owner | Blocks |
|------|-------|--------|
| Linear API key + workspace ID | Operator | M3 |
| Seat ↔ Linear user mapping (email vs manual) | Design in M3.6 | M3.5 |
| Merge graph Phase 1 PR | Review | M0.4, M5 prod |
| Cursor/Codex hook API availability | Research in M2 | M2.3–2.4 only |

---

## Related docs

- [`CONTEXT.md`](../CONTEXT.md) — **Seat-Scoped Mirror**, **Node**, **Central**
- [`docs/onboarding/citadel-autosync.md`](onboarding/citadel-autosync.md) — current SessionEnd setup
- [`docs/organization-vault-plan.md`](organization-vault-plan.md) — vault phases (Linear note superseded for ordering)
- [`docs/progress.md`](progress.md) — session log
