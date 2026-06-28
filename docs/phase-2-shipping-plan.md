# Phase 2 Shipping Plan — Autonomous Sync + Graph

Last updated: 2026-06-26.

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
- **MCP** — agents read Node + Central; humans never manage sync manually unless they ask for a refresh.
- **Graph** — one universal org view (seat **Nodes** + **Central** together); no scope toggles.

---

## Overall progress

| Milestone | Weight | Status | % of milestone | Contributes |
|-----------|--------|--------|----------------|-------------|
| M0 Graph Phase 1 | 15% | **Done** | 100% | **15%** |
| M1 Git push sync | 25% | **Done** | 100% | **25%** |
| M2 Session hook coverage | 10% | **Done** | 100% | **10%** |
| M3 Linear backend sync | 20% | **Done** | 100% | **20%** |
| M4 Linear MCP + skills | 10% | **Done** | 100% | **10%** |
| M5 Graph UI Phase 2 | 15% | **Done** | 100% | **15%** |
| M6 QA, merge, deploy | 5% | Partial | 60% | **3%** |
| **Total** | **100%** | | | **~99%** |

Update the **Contributes** column as checkpoints close. Target: **100%** before calling Phase 2 shipped.

---

## M0 — Graph Phase 1 ✅ (100%)

**Branch:** merged PR #5 (`ffabc1f`)

| Checkpoint | Done |
|------------|------|
| Vendored `force-graph`; removed Three.js | ✅ |
| Central hub, seat tiers, hover/click, labels | ✅ |
| Activity ↔ Knowledge graph toggle | ✅ |
| Docs + commit | ✅ |
| Merge to `main` + production deploy | ✅ (PR #5, `ffabc1f`) |

**Exit criteria:** PR merged; production serves `force-graph.min.js`; Activity + Knowledge modes work in browser.

---

## M1 — Git push sync ✅ (100%)

**Delivers:** Every `git push` snapshots commit metadata → seat **Node**.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 1.1 | Define snapshot payload (hash, message, author, branch, changed paths, repo) | **100%** | `sync_push.py` docstring |
| 1.2 | `sync_push.py` — stdlib POST to `/ingest`, same contract as `sync_session.py` | **100%** | Unit tests pass |
| 1.3 | Git hook template (`pre-push`) + skill install docs | **100%** | `templates/git-pre-push.sh`, `install_autosync.sh` |
| 1.4 | Reuse `CITADEL_MCP_ACCESS_TOKEN`; no `dataset` field → private Node | **100%** | Test asserts no `dataset` |
| 1.5 | Fail-silent, HTTPS-only, size cap (match session sync) | **100%** | Hook never blocks push |
| 1.6 | Integration test + manual E2E (push → search Node) | **100%** | 7 pytest; prod E2E after deploy |

**Depends on:** nothing (extends existing proactive-ingest skill).

---

## M2 — Session hook coverage ✅ (100%)

**Delivers:** Session distill where IDE supports it; git push remains universal fallback.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 2.1 | Claude Code `SessionEnd` → `sync_session.py` | **100%** | Shipped PR #4 |
| 2.2 | Document git push as universal path in skill + onboarding | **100%** | `citadel-autosync.md` + SKILL.md |
| 2.3 | Cursor — git push baseline + optional project rule | **100%** | `citadel-autosync-ides.md` |
| 2.4 | Codex — same as 2.3 | **100%** | `citadel-autosync-ides.md` |
| 2.5 | Shared `citadel-proactive-ingest` skill: one install, git + session | **100%** | `install_autosync.sh` |

**Note:** No stable Cursor/Codex session hook API exists; git push (M1) satisfies "works everywhere."

---

## M3 — Linear backend sync ✅ (100%)

**Delivers:** Linear workspace → **Central**; assignee issues **Seat-Scoped Mirror** → each **Node**.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 3.1 | ADR: Central + Mirror routing (read-only Linear) | **100%** | ADR-0004 |
| 3.2 | `kb/linear_sync.py` — fetch issues/projects via Linear API | **100%** | Mocked tests |
| 3.3 | Config: `CITADEL_LINEAR_API_KEY`, optional team filter | **100%** | `kb/config.py` + `.env.example` |
| 3.4 | Ingest org-wide digest → `masumi-network` (Central) | **100%** | Central search finds issue titles |
| 3.5 | Mirror assignee issues → `seat:{slug}` per seat mapping | **100%** | Seat token search finds own issues |
| 3.6 | Seat ↔ Linear user mapping (email or admin config) | **100%** | `CITADEL_LINEAR_USER_MAP` |
| 3.7 | Run mode / admin endpoint / cron (`CITADEL_RUN_MODE=linear-sync`) | **100%** | `scripts/run_railway.py` |
| 3.8 | Tests (`tests/test_linear_sync.py`) | **100%** | pytest green |

**Depends on:** `CITADEL_LINEAR_API_KEY` from operator (Read scope sufficient).

---

## M4 — Linear MCP + skills ✅ (100%)

**Delivers:** John asks agent "what do I need to do?" → MCP reads mirrored Node (+ Central fallback).

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 4.1 | MCP tool: list my issues (seat-scoped, from Node mirror) | **100%** | `citadel_linear_my_issues` |
| 4.2 | MCP tool: org issue search (Central, reader+) | **100%** | `citadel_linear_search` |
| 4.3 | Wire audit + scopes (`kb:read`, seat token) | **100%** | Audit event on call |
| 4.4 | Update `citadel-vault` / connector / proactive-ingest skills | **100%** | Skill docs list Linear tools + sync policy |
| 4.5 | On-demand refresh optional (trigger sync before read) | **100%** | Admin tools only when user asks |

**Depends on:** M3.4–M3.5 minimum.

---

## M5 — Graph UI Phase 2 ✅ (100%)

**Delivers:** Graph useful once Nodes have content — universal org view, depth, spokes.

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 5.1 | Universal org view (seat **Nodes** + **Central** together) | **100%** | Scope toggles removed; one canvas |
| 5.2 | Local graph + depth slider (0–3 hops from selection) | **100%** | Click node → neighborhood |
| 5.3 | Explicit Central ↔ `seat:` vault spokes | **100%** | Visual hub links |
| 5.4 | Mode parity (Activity vs Knowledge where metadata allows) | **100%** | Knowledge graph loads from Cognee |
| 5.5 | Browser QA checklist | **100%** | Fit, pause, mode switch, mobile (2026-06-25) |

**Also shipped:** `_ensure_base_graph` always seeds **Central** (`masumi-network`) so the hub is visible for all sessions.

**Depends on:** M0 merged; richer Node content (M1/M3) makes QA meaningful.

---

## M6 — QA, merge, deploy (60% → target 100%)

| # | Task | % | Checkpoint / verify |
|---|------|---|---------------------|
| 6.1 | Merge Phase 2 → `main` | **100%** | `5f6c0ed`+ on `main` |
| 6.2 | Full pytest suite | **100%** | 346 passing |
| 6.3 | Prod: cognify **Central** healthy; Linear key + cron set | **40%** | LLM fix done; Linear key + cron pending |
| 6.4 | Update `docs/progress.md`, `tasks.md`, README | **100%** | 2026-06-26 pass |
| 6.5 | Teammate rollout: token + skill + git hook one-pager | **100%** | `teammate-rollout.md` |

**Remaining operator work:** `CITADEL_LINEAR_API_KEY` set on web (2026-06-29) —
still need the `linear-sync` cron + `GET /api/linear-sync` verify; per-dev
onboarding via `citadel onboard` (replaces the removed `install_autosync.sh`).
Graph repopulation is **done** (280 nodes; evolve cognify fixed via the
subprocess-then-in-loop split).

---

## Recommended ship order

```
M0 merge ──► M1 git push ──► M3 Linear backend ──► M4 Linear MCP
                    │                                    │
                    └──► M2 session docs/hooks ──────────┤
                                                         ▼
              M5 graph Phase 2 (parallel after M0) ──► M6 deploy
```

1. **Week 1:** Merge graph Phase 1 (M0) + ship git push sync (M1). ✅
2. **Week 2:** Linear backend + mirror (M3); graph unified view + depth (M5). ✅
3. **Week 3:** Linear MCP (M4) + docs/onboarding. ✅
4. **Week 4:** Production rollout — Linear key, cron, teammate hooks (M6). **In progress**

---

## Verification checklist (final gate)

- [x] John pushes code → issue/findable note in his **Node** without manual ingest.
- [x] John closes Claude session → distill still lands in **Node** (existing).
- [ ] Linear sync runs → issues in **Central**; John's assigned issues in his **Node**.
- [ ] John asks agent via MCP → task list from **Node** mirror.
- [x] Graph: universal org view + local depth around a node.
- [x] All failures fail-silent; push/session never blocked.

---

## Open items (resolve during build)

| Item | Owner | Blocks |
|------|-------|--------|
| Linear API key (Read scope) + cron service | Operator | M6.3 |
| Seat ↔ Linear user mapping (email vs manual) | Admin | Mirror accuracy |
| Per-dev `install_autosync.sh` | Each teammate | M6 rollout |

---

## Related docs

- [`CONTEXT.md`](../CONTEXT.md) — **Seat-Scoped Mirror**, **Node**, **Central**, autonomous sync
- [`docs/onboarding/citadel-autosync.md`](onboarding/citadel-autosync.md) — dev onboarding
- [`docs/onboarding/teammate-rollout.md`](onboarding/teammate-rollout.md) — 5-minute one-pager
- [`docs/organization-vault-plan.md`](organization-vault-plan.md) — vault phases
- [`docs/progress.md`](progress.md) — session log
