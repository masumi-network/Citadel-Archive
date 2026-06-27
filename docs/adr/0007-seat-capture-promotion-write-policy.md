# ADR 0007 — Seat capture, promotion, and write policy

- **Status:** Accepted (2026-06-27)
- **Relates:** ADR-0003 (seat/node/Central private memory), ADR-0005
  (self-evolving memory + policy-gated ingestion), `CONTEXT.md` glossary terms:
  **Seat Node Write Policy**, **Approved Capture Roots**, **Capture Policy**,
  **Capture Root Tags**, **Promotion Agent**, **New Org Project**,
  **Promotion Approval**, **Operations Dashboard**.

## Context

Citadel separates private seat **Nodes** from shared **Central**. Devs connect
via MCP + seat tokens, autonomous capture (git push, session hooks), and a
planned setup CLI. Security requirements:

- Seat-scoped callers must not dump raw or sensitive content into **Central**.
- MCP and agents must not silently ingest; approved folders may auto-capture to
  the **Node** only.
- **Central** should evolve from org sync and governed **Promotion**, not direct
  seat writes or org-tag bypasses.

ADR-0003 allowed seat HTTP ingest with org-bound tags to reach **Central**.
This ADR **narrows** that path: all seat-scoped writes land in the **Node**;
**Central** is updated only through governed upstream jobs.

Partial implementation exists (2026-06-27): MCP seat write guards
(`guard_mcp_seat_write_policy`), secret scan on all write paths, client approval
docs. Gaps: HTTP seat org-tag routing, capture CLI wizard, promotion agent
reference checks, approval queue UI.

## Decision

### 1. Seat Node Write Policy (all channels)

Seat **Tokens** and **Agent Identities** scoped to a **Node** may **write only
to that Node**. **Central** is **read-only** for seat-scoped callers on every
channel: MCP, HTTP `/ingest`, autosync hooks, dashboard, and CLI capture.

**Central** receives **Structured Knowledge** only via:

- Org source sync (GitHub / Linear cron, Scout PR ingestion per ADR-0005)
- **Promotion Agent** (Node → Central, governed)
- Service-account **Vault Contributions** and operator/admin jobs

Direct seat ingest with org tags (`org-ready`, `repo-content`, etc.) to
**Central** is **removed** (supersedes the seat write exception in ADR-0003).

### 2. Ingest approval model

| Capture type | Approval |
|---|---|
| Inside **Approved Capture Roots** | Auto-capture to **Node** (no per-write MCP/agent prompt) |
| Outside approved roots | MCP client tool approval **and** agent explicit yes/no before `citadel_ingest` |
| All writes | Server **Security Finding** gate (block high/critical secrets) |

### 3. Approved Capture Roots + Capture Policy (hybrid)

**v1 triggers:** git push inside an approved root + manual `citadel capture`
on demand. No file watcher; no local schedule in v1.

**Storage (hybrid):**

- **Local:** **Approved Capture Roots** (filesystem paths) per machine, chosen in
  setup wizard.
- **Server:** org **Capture Policy** baseline per **Seat** (deny rules, templates).

**Governance:** admin sets org baseline; **Vault Member** may add **stricter**
local rules only — never remove org denies.

Any local path may be approved (org clones, personal, experimental). Capture
to **Node** does not imply **Central** visibility.

### 4. Capture Root Tags (setup wizard)

Each approved root is tagged at setup:

| Tag | Promotion rule |
|---|---|
| `personal` (preset) | Never auto-promote to **Central** |
| `org-work` (preset) | Eligible for auto-promotion when **Promotion Agent** finds a match |
| Custom tags | Labels for search/context only |

### 5. Promotion Agent (Node → Central)

Runs on **6h Railway cron** and **on demand** (Operations Dashboard or CLI).

For each candidate note in a seat **Node**:

1. Cross-reference **GitHub organization repo list** and **Structured Knowledge**
   already in **Central**.
2. If content clearly extends known org work → auto-promote (dual-write; original
   stays in **Node**).
3. If content introduces a **New Org Project** (no repo/org match and no
   **Central** representation) → require **Promotion Approval**.
4. Respect **Capture Root Tags**: `personal` never auto-promotes regardless of
   match.

LLM assists classification; structured lists are authoritative for repo names.

### 6. Promotion Approval surfaces

- **Operations Dashboard:** primary monitoring (health, seats, activity, memory,
  usage, share knowledge, access) plus pending promotion queue.
- **MCP:** in-flow yes/no when the **Vault Member** is in an agent session.
- **Visibility:** each **Vault Member** sees their own queue; admins see all
  seats’ pending items and may approve on a member’s behalf (e.g. out of office)
  with a full audit record.

### 7. Operations Dashboard role

Dashboard is for **monitoring and governance**, not the primary dev write surface.
Day-to-day capture flows through MCP, approved-root autosync, and CLI.

## Consequences

- **+** Clear security boundary: **Node** = private working memory; **Central** =
  curated org memory. Auto-capture without spamming approval prompts for trusted
  folders. Promotion is explainable (GitHub + **Central** refs, tags, approval
  queue).
- **−** Build work: setup CLI wizard, local policy file, server policy API,
  promotion reference checks, approval queue UI, HTTP guard parity with MCP,
  ADR-0003 doc/consequence updates. Admin delegate approval needs careful audit
  UX.
- **Migration:** Remove or 403 seat HTTP org-tag routing to **Central**; update
  tests such as `test_org_tag_ingest_routes_to_central`. MCP seat guards already
  partially enforce this.

## Build order (suggested)

1. Enforce **Seat Node Write Policy** on all HTTP write paths (parity with MCP).
2. Server **Capture Policy** baseline API + admin UI snippet.
3. Local setup wizard + `citadel capture` + merge local roots with server template.
4. **Promotion Agent** reference checks (GitHub org + **Central** search) + tag rules.
5. **Promotion Approval** queue (dashboard + MCP tool) + admin delegate with audit.
6. Wire 6h evolve cron + on-demand trigger to promotion pass.

## Open questions

- Exact CLI command names and local policy file location (e.g. `~/.citadel/`).
- Whether `citadel capture` runs full tree scan or git-diff / README-only summary
  (keep payloads small).
- Additional preset **Capture Root Tags** beyond `personal` / `org-work`.
