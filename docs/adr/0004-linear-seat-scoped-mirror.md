# Linear Sync With Seat-Scoped Mirror

Linear workspace content syncs read-only into Citadel. The full workspace
lands in **Central** (`masumi-network`). Issues assigned to a seat-holder are
also **Seat-Scoped Mirrored** into that seat's **Node** so agents can answer
*"what do I need to do?"* from private memory without filtering Central on every
query.

**Considered options**

- **Central-only with search filter:** simpler storage, but every personal task
  query depends on search quality and assignee metadata in Central.
- **Mirror assignee subset to Node:** dual-write pattern aligned with ADR-0003
  promotion semantics; personal queries stay local and fast.
- **Write-back to Linear:** rejected — Citadel remains read-only for Linear in
  Phase 2.

**Consequences**

- Requires `CITADEL_LINEAR_API_KEY` and seat principal `email` (or
  `CITADEL_LINEAR_USER_MAP`) for assignee routing.
- MCP: `citadel_linear_my_issues` (Node mirror), `citadel_linear_search` (Central).
- Run via `POST /api/linear-sync/run`, `CITADEL_RUN_MODE=linear-sync`, or cron.
