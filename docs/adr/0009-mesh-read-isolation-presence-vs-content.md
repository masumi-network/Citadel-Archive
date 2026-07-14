# Mesh Read Isolation: Presence For All, Content Per Caller Scope

Citadel's graph surfaces read the whole Cognee graph store and served every seat's **Node** content — document nodes, chunk text via per-item drill-down, and extracted entities — to any reader **Access Token**. That violated [ADR-0003](0003-seat-node-central-private-memory.md)'s "reads never cross seat nodes," which `/search` already enforced through dataset allowlists. At the same time, CONTEXT.md promises a "universal org view" where every seat is visible on one canvas. The 2026-07-13 grill resolved the tension: **universal means every seat's *presence* is visible; content stays scoped.** Mesh content surfaces (the **Knowledge Mesh** view and its document drill-down) now enforce the same read scope as search — **Central** plus the caller's own **Node**, with admin/operator callers seeing all content for support and audit — while every seat always appears as **Seat Presence** (a hub with activity counts, synthesized from the seat list, never from content). Extracted entities are visible only when reachable in the graph from at least one document the caller may see. The runtime activity canvas is renamed **Vault Activity**; **Knowledge Mesh** names the Cognee-backed relationship map, matching the glossary definition.

**Considered Options**

- **Cached global graph vs per-caller filtering:** one shared, cached graph payload is fastest and simplest, but cannot express isolation — any cache key short of the caller's dataset scope leaks. Per-caller filtering costs a dataset-map lookup (mitigated by a 60s TTL cache that also remembers failures) plus linear per-request passes over nodes/edges. Isolation won.
- **Admin-only content graph:** trivially safe, but strips members of the graph view of **Central** — the shared-memory value the **Organization Vault** exists for.
- **Transparency amendment ("glass walls"):** let every member see every seat's content and supersede ADR-0003. Rejected: it breaks the **Node** privacy promise already made to the team mid-rollout and contradicts the pentest posture.
- **Entity visibility — org-visible names vs strict reachability:** concept names alone ("AcquireCo") can leak exactly what **Node** privacy protects, so entities require reachability from a visible document. Cognee dedupes entities across datasets, so shared concepts stay visible to everyone through their **Central** sightings.
- **Hubs from kept content vs from the seat list:** content-derived hubs vanish exactly when isolation hides the content, silently deleting seats from the "universal org view." Hubs therefore come from the seat inventory, independent of content visibility.

**Consequences**

- The mesh graph endpoint and the document drill-down filter per caller; there is deliberately **no globally cached graph payload**. Content-node visibility = reachability from the caller's visible documents (own **Node** + **Central** + non-seat datasets; admin bypasses).
- Drill-down on a document the caller may not see returns the same not-found response as a nonexistent id (no existence oracle).
- **Seat Presence** is a glossary term: every seat always renders as a hub (slug + contribution counts) for every **Vault Member**; presence metadata never includes **Node** content, session titles, or member emails.
- The seat overview page (Operations Dashboard) shows operational presence for all seats, content lists only for the caller's own **Node**; admin content drill-down is support/audit, flagged as such.
- UI and docs say **Vault Activity** (runtime projection, restart-transient) vs **Knowledge Mesh** (the relationship map). CONTEXT.md "Graph views (Phase 2)" section is the canonical description.
- The pre-existing production leak closes when this ships; it rides the same release as the drill-down/legibility branch so the more convenient UI never deploys without the isolation that makes it safe.
