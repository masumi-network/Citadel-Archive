# Organization Vault Plan

Last updated: 2026-06-16.

Citadel is an **Organization Vault**: a cloud-hosted, access-controlled shared
memory layer for a company. It keeps approved company sources in sync, turns raw
source material into structured knowledge, and exposes that knowledge to humans
and agents through the web app, API, and MCP.

Canonical domain language: [`CONTEXT.md`](../CONTEXT.md).  
Core private-memory architecture: [ADR-0003](adr/0003-seat-node-central-private-memory.md).

## Goal

The end goal is a shared organizational memory that behaves like an
Obsidian-style vault for the company, but is hosted, governed, source-linked,
and agent-accessible — with **private seat nodes** for agent working memory and
**Central** for organization-wide knowledge.

The vault should answer questions like:

- What changed in our repositories today?
- Which team, project, or source owns this knowledge?
- What context should a teammate or agent know before working on a task?
- Which documents, commits, notes, and decisions support this answer?
- What can this member or agent read, write, sync, or administer?

## Product Boundaries

Citadel is not a generic database. The database stores data, but the product is
the governed organization vault on top of it.

Citadel is not a full Obsidian clone. It borrows the vault mental model, links,
backlinks, graph, and workspace feel, while adding cloud hosting, source sync,
access control, provenance, and MCP access.

Citadel is not a replacement for GitHub. GitHub remains the source of truth for
code and repository activity. Citadel learns from GitHub and produces structured
context, daily summaries, and searchable memory.

## Seat, Node, And Central

Private memory and shared memory are deliberately separate. See
[ADR-0003](adr/0003-seat-node-central-private-memory.md) for the full decision
record.

| Concept | Meaning |
|---|---|
| **Seat** | One licensed team member slot; equals one **Principal** (one human, one seat). |
| **Node** | That seat's private mini knowledge base (`seat:{slug}`). Storage boundary — not the token. |
| **Central** | Organization-wide shared knowledge. Dataset: `masumi-network`. |
| **Token** | Credential issued to a seat after admin provisioning. Scopes access; does not define storage. |
| **Promotion** | Curated dual-write from a seat node into Central. Original stays in the node. |

### Provisioning

1. Admin creates a **Seat** (Principal) before any tokens.
2. Admin assigns the seat a node dataset: `seat:{slug}`.
3. Admin issues one or more **Tokens** with role, `default_dataset`, `default_session`, and optional `allowed_datasets`.

Admin-first provisioning (not lazy auto-create on first login) keeps seat inventory, licensing, and support overrides auditable.

### Read Scope

- **Own node** + **Central** — always for normal member/agent tokens.
- **Never** another seat's node — hard isolation between seats.
- Multi-dataset search (Phase 2) searches only datasets the token is allowed to read (typically own node + Central).

### Write Scope And Promotion

| Content type | Default write target | Pipeline |
|---|---|---|
| Agent working memory, session notes | Seat node (`seat:{slug}`) | Light indexing (Tiered Ingestion) |
| Org-bound sync (GitHub, repo content) | Central (`masumi-network`) | Full Learning Process |
| Tagged vault contributions, org paths | Central | Full Learning Process |
| **Promotion** (curated share) | Dual-write: node + Central | Full Learning Process on Central copy |

**Automatic + curated sync:** default agent writes stay in the seat node. Tags and org pipelines route content to Central — not a full mirror of every node into Central, and never seat-to-seat sync.

### Tiered Ingestion

- **Full pipeline** (security review, enrichment, structuring): org-bound content destined for Central — GitHub sync, repo content, tagged contributions, promoted copies.
- **Light pipeline** (lighter indexing only): raw seat-node agent memory — working context that may never be promoted.

### Admin Override

Admins may override dataset scope, reassign seats, or perform support actions. Every override is **audited**. Seat-to-seat node reads remain forbidden even for admins unless a future hard-isolation phase introduces explicit break-glass policy (Phase 4).

## Core Actors

- **Vault Admin**: provisions seats, manages sources, access roles, tokens, sync policy, and audit visibility.
- **Vault Member (Seat)**: searches, reads, and optionally contributes knowledge based on their role and node/Central scope.
- **Agent Identity**: an autonomous or assistant agent that communicates through Masumi Agent Messenger and uses its own access token for vault access.
- **Source Owner**: a person or team responsible for the quality and freshness of a connected source.

## Core Objects

- **Organization Vault**: the shared body of company knowledge (Central plus governed access to seat nodes).
- **Source Material**: raw inputs such as repositories, commits, notes, docs, manual entries, and future connectors.
- **Source Snapshot**: retained evidence or a source pointer used to reproduce what the vault learned from source material.
- **Vault Backup Mirror**: a secondary synced copy of vault evidence and history used for recovery, audit, and rebuilds.
- **Structured Knowledge**: source-linked concepts, relationships, summaries, citations, and context produced from source material.
- **Knowledge Index**: the searchable organization of structured knowledge used for fast retrieval.
- **Knowledge Mesh**: the relationship map connecting structured knowledge by source, concept, and provenance.
- **Learning Process**: the governed process that turns source material into structured knowledge.
- **Access Token**: a credential issued to a seat or agent identity.
- **Access Role**: the permission level attached to a member or agent identity.
- **Agent Action**: a vault operation performed by an agent identity.
- **Repository Daily Update**: a source-linked summary of meaningful changes in one repository over a day.
- **Knowledge Conflict**: a visible disagreement between structured knowledge or its supporting source snapshots.

## Phase Roadmap

### Phase 1: Token Scoping And Shared Vault Foundation (done, uncommitted)

Proves Citadel as a hosted organization vault with per-token memory scope.

**Token scoping (implemented):**

- `default_dataset` — default write/search dataset for the token (typically `seat:{slug}` or `masumi-network`).
- `default_session` — default Cognee session for the token.
- `allowed_datasets` — optional allowlist; empty means whole-vault access for the role; non-empty restricts search/ingest/contribute to listed datasets (admin and `access:manage` bypass).

**Shared vault foundation (existing):**

- Hosted vault with web dashboard for status, search, sources, access, and audit.
- GitHub org sync into Central (`masumi-network`).
- LLM-backed Learning Process for org-bound content.
- Knowledge index, knowledge mesh, repository daily updates.
- Vault Backup Mirror (ADR-0001).
- MCP access with role-gated tools.
- Reader / writer / admin roles with audit on sensitive actions.

Phase 1 access tokens still grant role-constrained vault access; dataset scoping is the first step toward seat/node isolation without yet requiring admin seat UI.

### Phase 2: Admin Seat UI, Multi-Dataset Search, Tag Routing (planned)

- **Admin seat UI:** create seats, assign `seat:{slug}` nodes, issue and rotate tokens, view seat inventory.
- **Multi-dataset search:** search own node + Central (and other allowed datasets) in one query; enforce `allowed_datasets` at query time.
- **Tag routing:** tags separate automatic (node) vs curated (Central) lanes — e.g. org tags route to Central, session tags stay in node.
- Tiered ingestion enforcement at ingest routing layer.

**Not in Phase 2:** Linear sync, external notification adapters, physical DB-per-seat isolation.

### Phase 3: Linear Sync (planned)

Read-only Linear API integration. Scope (subject to implementation planning, not yet ADR'd):

- Whole Linear workspace content syncs to **Central** (org-wide visibility).
- Issues assigned to a seat may copy relevant context into that seat's **node** for agent working memory.
- MCP activity notifications when Linear-linked knowledge changes.

Linear remains read-only from Citadel's perspective in this phase — no write-back to Linear.

### Phase 4: External Notify And Hard Isolation (planned)

- External notification surfaces (beyond existing Google Chat digests) for vault activity relevant to seats.
- Optional hard isolation upgrades (e.g. break-glass admin access to seat nodes, stronger physical separation) if logical-dataset isolation proves insufficient at scale.

### Masumi Agent Messenger (orthogonal)

Agent-to-agent communication through Masumi Agent Messenger remains separate from vault storage. Agents use the Organization Vault as shared memory via their own tokens; messenger threads do not automatically become vault contributions. See [`docs/agent-access-model.md`](agent-access-model.md).

## Daily Knowledge Flow

1. A connected source changes, such as a repository commit or pushed note.
2. Citadel records the change as source material and keeps a source snapshot when citation, audit, or reprocessing requires it.
3. Org-bound content runs through the full Learning Process into Central; seat-node agent memory gets lighter indexing.
4. The vault updates structured knowledge, knowledge index, and knowledge mesh.
5. The dashboard shows source status, recent activity, and repository daily updates.
6. Humans and agents query own node + Central through the UI, API, or MCP.
7. Curated content may be **promoted** from a seat node to Central (dual-write).
8. Feedback and new source activity improve future structured knowledge.

## Trust Rules

- Every useful piece of structured knowledge should retain a link to its source material.
- Source snapshots should be retained when needed for citation, audit, debugging, or reprocessing.
- The knowledge index and knowledge mesh should be rebuildable from source snapshots and structured knowledge.
- The vault should maintain a redundant backup mirror for recovery, audit, and rebuilds without using it as the live retrieval store.
- Private repository access must come from a scoped GitHub token with only the needed repository permissions.
- Every seat and agent should have its own access token; shared tokens are avoided outside bootstrap or local testing.
- Seat nodes are private; Central is shared. Reads never cross seat nodes.
- Promotion is dual-write, not move-and-delete.
- Agent Messenger conversations remain outside the vault unless a writer or admin intentionally adds them.
- For code behavior, newer source-linked repository truth should outrank older notes, agent contributions, and human-written summaries.
- Conflicting knowledge should be marked visibly instead of silently merged or overwritten.
- Agent access should be auditable by identity, role, tool, source, and outcome.
- Admin overrides require audit; seat-to-seat reads remain forbidden.

## Open Design Questions

- Which sources are trusted enough for automatic structuring into Central?
- Which tags definitively route content to Central vs seat node in Phase 2?
- What UI should reviewers use to resolve visible knowledge conflicts?
- What should be shared through Masumi Agent Messenger versus stored in the Organization Vault?
- When does logical-dataset isolation require Phase 4 hard isolation?

## Immediate Build Priorities

1. Commit and ship Phase 1 token scoping (`default_dataset`, `default_session`, `allowed_datasets`).
2. Document and smoke-test seat/node/Central access rules against existing MCP tools.
3. Design Phase 2 admin seat UI and multi-dataset search API.
4. Keep polishing the hosted dashboard around source status, access, audit, and search.
5. Smoke-test MCP search and ingest from Claude Code and Codex with scoped tokens.
6. Verify private GitHub repository sync with a fine-grained token into Central.
