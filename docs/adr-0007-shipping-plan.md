# ADR-0007 Shipping Plan — Seat capture, promotion, and write policy

Last updated: 2026-06-27.

**ADR:** [`0007-seat-capture-promotion-write-policy.md`](adr/0007-seat-capture-promotion-write-policy.md)  
**Glossary:** [`CONTEXT.md`](../CONTEXT.md)  
**Tasks:** [`tasks.md`](../tasks.md)

## Goal

Seat-scoped callers write only to their **Node**. **Central** is read-only for
seats and evolves via org sync, **Promotion Agent**, and service accounts.
Capture is governed: approved folders auto-sync; everything else needs explicit
approval; secrets blocked everywhere.

## Overall progress

| Step | Weight | Status | % |
|------|--------|--------|---|
| P0 Docs + glossary + ADR | 5% | **Done** | 5% |
| P1 Seat write policy (all channels) | 20% | **Done** | 20% |
| P2 MCP security hardening (partial) | 10% | **Done** (local) | 10% |
| P3 Capture policy server API + admin baseline | 15% | **Done** | 15% |
| P4 Setup CLI + `citadel capture` + local roots | 20% | **Done** | 20% |
| P5 Promotion Agent (refs + tags + cron) | 20% | **Done** (local) | 20% |
| P6 Promotion Approval UI + MCP tool | 10% | **Done** (local) | 10% |
| **Total** | **100%** | | **~98%** |

## P1 — Seat write policy (all channels)

Enforce **Seat Node Write Policy** on HTTP and MCP — not MCP-only.

| # | Task | Verify |
|---|------|--------|
| 1.1 | Generalize `guard_seat_write_policy` (ingest + contribute) | Seat + org tag → 403 |
| 1.2 | `resolve_write_targets`: seat always → own **Node** | No Central dual-write via tags |
| 1.3 | Block seat `/api/contribute` | 403 with promotion pointer |
| 1.4 | Update tests (`test_org_tag_*`, promotion dual-write) | pytest green |
| 1.5 | Discovery manifest + skills already document policy | — |

**Exit:** Seat token cannot reach **Central** on any write path; admin/service bypass unchanged.

## P3 — Capture policy (server)

| # | Task | Verify |
|---|------|--------|
| 3.1 | `GET/PUT /api/access/seats/{slug}/capture-policy` (admin baseline) | Admin CRUD |
| 3.2 | Merge org deny globs with `CITADEL_EXCLUDE_PATTERNS` | Unit tests |
| 3.3 | Settings UI snippet: org capture baseline | Admin can view/edit |

## P4 — Capture CLI (local)

| # | Task | Verify |
|---|------|--------|
| 4.1 | `citadel setup` wizard — pick roots + **Capture Root Tags** ✅ | Writes `~/.citadel/capture.json` |
| 4.2 | `citadel capture` — scan approved roots, POST summaries to **Node** ✅ | Manual E2E |
| 4.3 | Git hook checks root is in local allowlist ✅ | Push outside list → skip or warn |
| 4.4 | Docs: teammate-rollout + connect skill ✅ | — |

## P5 — Promotion Agent

Design locked 2026-06-27 (ADR-0007 **Refinements**). Local sketch exists; parity gaps below.

| # | Task | Verify |
|---|------|--------|
| 5.1 | Reference check: masumi **GitHub org repo list** + **Central** search | Known vs **New Org Project** |
| 5.2 | **Capture Root Tags** — only `org-work` capture roots auto-promote; `personal` + custom never | Unit tests |
| 5.3 | No-repo-hint → **Central** match only; else stay on **Node** (no queue) | Unit tests |
| 5.4 | **Secret scan + LLM** always required (structured match alone insufficient) | Unit tests |
| 5.5 | 6h evolve cron + on-demand (`POST /api/promote/run`, seat-scoped for members) | Railway / dashboard / CLI |
| 5.6 | Auto-promote writes promotion metadata on **Central** copy (audit + traceability v1) | Audit + ingest payload |
| 5.7 | Reject dedupe — unchanged notes not re-queued | Cron regression test |
| 5.8 | `citadel promotion run|list` CLI + `--json` | Headless E2E |

## P6 — Promotion Approval

| # | Task | Verify |
|---|------|--------|
| 6.1 | `GET /api/promotion/pending` + `POST .../approve` + `POST .../reject` | Seat + admin delegate |
| 6.2 | Dashboard queue on **Operations Dashboard** | Browser QA |
| 6.3 | MCP: `citadel_promotion_pending` / approve / reject (human confirm) | MCP tests |
| 6.4 | Audit admin-on-behalf approvals | `/api/audit` |
| 6.5 | Agent proposes queue items — members approve/reject only (no manual add) | Docs + UX |
| 6.6 | `citadel promotion approve|reject` CLI + `--json` | Headless E2E |

## Dependencies

```
P0 docs ──► P1 seat write policy ──► P3 capture policy API
                         │                    │
                         └──────────► P4 capture CLI
P1 + P5 promotion engine ──► P6 approval UI
```

## Related

- Phase 2 M6 operator rollout (Linear key, graph repop) — parallel, not blocked
- ADR-0005 steps 4–5 (Scout PR ingest, cognee auto_improve depth) — after P5
