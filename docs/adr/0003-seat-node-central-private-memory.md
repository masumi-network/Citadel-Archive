# Seat, Node, And Central As The Private-Memory Architecture

Citadel separates **private agent memory** from **organization-wide knowledge** using three layers: a **Seat** (one licensed human **Principal**), a **Node** (that seat's private mini knowledge base), and **Central** (the shared organization dataset, `masumi-network`). The **Node** is the storage boundary — not the **Token**. Admins provision a seat before issuing tokens; each token inherits the seat's node scope plus read access to Central. Reads never cross seat nodes; writes default to the seat node, with org-bound paths and tagged contributions landing in Central; **Promotion** copies curated content from a node into Central via dual-write (the original stays in the node).

**Considered Options**

- **Lazy provisioning vs admin-first:** Auto-create a node on first token use is simpler to ship, but makes audit, seat inventory, and support overrides harder. Admin-first provisioning keeps a clear principal → seat → node → token chain and matches licensed team membership.
- **Move vs dual-write for promotion:** Moving content from node to Central loses private working memory and breaks agent continuity. Dual-write keeps the seat's draft/context in the node while publishing a curated copy to Central.
- **Central-only read vs node + Central:** Searching only Central misses private agent context; searching all nodes violates isolation. Default read scope is the caller's own node plus Central.
- **Physical database per node vs logical dataset:** Separate databases per seat would maximize isolation but multiply operational cost (migrations, backups, mesh rebuilds). Logical datasets (`seat:{slug}` for nodes, `masumi-network` for Central) in one Cognee deployment match Phase 1 infrastructure while enforcing access at the API/MCP layer.

**Consequences**

- Node naming convention: `seat:{slug}` (e.g. `seat:alice`). Central remains `masumi-network`.
- Token fields `default_dataset`, `default_session`, and `allowed_datasets` (Phase 1, implemented) scope memory without redefining the node boundary.
- **Tiered ingestion:** org-bound syncs (GitHub, tagged vault contributions, promoted content) use the full Learning Process; raw seat-node agent memory gets lighter indexing only.
- **Automatic + curated sync:** default agent writes stay in the seat node; tags and org pipelines route content to Central separately — not a full vault mirror between seats.
- Admins may override scope with audit; seat-to-seat node reads remain forbidden.
- Phase 2 adds admin seat UI, multi-dataset search, and tag routing; Phase 3 adds Linear read-only sync; Phase 4 adds external notifications and hard isolation options. See [`docs/organization-vault-plan.md`](../organization-vault-plan.md).
