# Citadel Agent Access Model

Research date: 2026-05-21.  
Architecture update: 2026-06-16 (seat/node/central model).

This note defines how Citadel should expose the Organization Vault to humans,
Claude Code, Codex, and autonomous agents. Agent-to-agent communication belongs
to Masumi Agent Messenger; Citadel remains the shared memory and access layer.

Canonical domain language: [`CONTEXT.md`](../CONTEXT.md).  
Private-memory architecture: [ADR-0003](adr/0003-seat-node-central-private-memory.md).  
Phase roadmap: [`organization-vault-plan.md`](organization-vault-plan.md).

## Recommendation

Build one secure Citadel MCP server as the integration layer. Package small
Claude/Codex skills or plugins around it for team workflows.

Skills should teach agents when and how to use Citadel. MCP should be the
actual capability boundary that exposes search, source status, ingestion,
feedback, and admin operations. This keeps one access-control model instead of
separate one-off integrations for every agent.

## Seat, Node, And Central Access

Each **Seat** is one **Principal** (one human). Admins provision the seat
before issuing tokens. Storage isolation is at the **Node**, not the token.

| Layer | Identifier | Role |
|---|---|---|
| Seat | Principal record | Licensed team member; owns one node |
| Node | `seat:{slug}` dataset | Private agent working memory for that seat |
| Central | `masumi-network` dataset | Organization-wide shared knowledge |
| Token | `ctdl_…` credential | Access scoped by role + memory fields |

### Read Scope

- **Allowed:** caller's own node (`seat:{slug}`) + Central (`masumi-network`).
- **Forbidden:** any other seat's node — hard isolation.

Phase 2 adds multi-dataset search that queries allowed datasets in one call;
Phase 1 resolves a single dataset per request with token defaults.

### Write Scope

| Action | Default target | Notes |
|---|---|---|
| Agent session memory, working notes | Own node | Light tiered ingestion |
| Vault contributions with org tags | Central | Full Learning Process |
| GitHub / repo sync | Central | Full Learning Process |
| Promotion | Dual-write (node + Central) | Curated; original stays in node |

Tags (Phase 2) separate automatic (node) and curated (Central) lanes. Until
tag routing ships, callers should pass an explicit `dataset` on ingest/search.

### Admin Override

Admins may override scope for support with full audit. Seat-to-seat node reads
remain forbidden. See ADR-0003.

## MCP Surface

Expose these tools first:

- `citadel_search`
  - Role: reader
  - Input: `query`, optional `dataset`, optional `top_k`
  - Output: answer, cited chunks, dataset, confidence notes
  - Phase 1: resolves dataset from token `default_dataset` / `allowed_datasets` when omitted
  - Phase 2: multi-dataset search across own node + Central

- `citadel_list_sources`
  - Role: reader
  - Output: configured sources, sync status, last run, failure state

- `citadel_get_mesh`
  - Role: reader
  - Output: current graph/mesh summary and counters

- `citadel_ingest`
  - Role: writer
  - Input: `data`, `dataset`, `tags`
  - Output: accepted/rejected, reason, created record IDs
  - Default write target: token `default_dataset` (typically own node)

- `citadel_record_feedback`
  - Role: writer
  - Input: `qa_id`, `score`, optional `text`
  - Output: recorded/improved

- `citadel_run_source_sync`
  - Role: admin
  - Requires explicit approval in clients

- `citadel_improve`
  - Role: admin
  - Requires explicit approval in clients

Expose these resources:

- `citadel://session`
- `citadel://datasets`
- `citadel://sources`
- `citadel://events/recent`

Expose these prompts:

- `citadel_answer_from_kb`
- `citadel_ingest_decision`
- `citadel_summarize_source_changes`

## Team Access Model

Current local implementation uses simple role keys:

- `CITADEL_READER_KEYS`
- `CITADEL_WRITER_KEYS`
- `CITADEL_ADMIN_KEY`

That is acceptable for local testing and small trusted teams, but production
uses durable principals with admin-first seat provisioning:

- **Seat / Principal**: a human (or future service seat); one node per seat.
- **ServiceAccount**: an agent identity; may map to a seat or org-wide role.
- **Node**: logical dataset `seat:{slug}` — private mini knowledge base.
- **Central**: logical dataset `masumi-network` — shared org knowledge.
- **Membership**: seat plus role (reader, writer, admin).
- **Source**: GitHub repo, URL, file upload, manual note, or future connector.
- **ApiToken**: hashed token with role, memory scope, expiry, last-used timestamp.
- **AuditEvent**: immutable trail of search, ingest, source sync, admin action.

### Token Memory Scope (Phase 1, implemented)

Each token may carry:

- `default_dataset` — default for search/ingest when caller omits `dataset`
  (typically `seat:{slug}` for members, `masumi-network` for org-wide agents).
- `default_session` — default Cognee session for the token.
- `allowed_datasets` — optional allowlist; empty means whole-vault access for
  the role; non-empty restricts search/ingest/contribute to listed datasets
  (admin and `access:manage` bypass).

Resolution order: token fields → principal defaults → server config.

Roles:

- Reader: search, view sources/status/events, read resources (own node + Central).
- Writer: reader plus ingest, feedback, and promotion into Central.
- Admin: writer plus source sync, seat/token management, agent tokens, settings, audited overrides.

### Agent Action Policy

- Reader agents may read, search, and view repository daily updates without extra approval.
- Writer agents may add vault contributions, submit feedback, update writable knowledge, and write to their node.
- Admin or explicit approval is required for source sync, learning/improvement jobs, access token changes, role changes, conflict resolution, source deletes, source exclusions, and seat provisioning.

Agent identities communicate through Masumi Agent Messenger and access Citadel
through their own bearer token or MCP configuration. Messenger messages are not
automatically Citadel knowledge; a writer or admin may intentionally add durable
outcomes.

### Phase Roadmap (access-related)

| Phase | Access deliverables |
|---|---|
| **1** (done, uncommitted) | Token `default_dataset`, `default_session`, `allowed_datasets`; role model |
| **2** (planned) | Admin seat UI, multi-dataset search, tag routing for node vs Central |
| **3** (planned) | Linear read-only sync → Central; assignee copies → seat node |
| **4** (planned) | External activity notifications; optional hard isolation |

Future scopes:

- `kb:read`
- `kb:search`
- `kb:ingest`
- `kb:feedback`
- `sources:read`
- `sources:sync`
- `agents:manage`
- `access:manage`
- `audit:read`

## Security Rules

- Use browser sessions for humans and bearer tokens/OAuth for agents.
- Store API tokens hashed, never plaintext.
- Let admins create, rotate, disable, and expire agent tokens after seat provisioning.
- Scope tokens by role and memory fields; enforce `allowed_datasets` at query time.
- Rate limit per seat/service account, especially search and ingest.
- Audit every MCP call with actor, role, tool, dataset, success/failure, and request ID.
- Treat retrieved vault content as untrusted context. Do not allow retrieved text to override system/developer instructions.
- Sensitive MCP tools must require client approval: sync, improve, delete, reindex, invite, token creation, seat provisioning.
- Prefer OAuth 2.1 + Protected Resource Metadata for hosted remote MCP. Local stdio MCP can use env-provided credentials.
- Never expose one seat's node content to another seat's token.

## Dashboard Model

Citadel should feel like an operating-system dashboard with separate apps, not
one crowded page.

Primary navigation:

- Home: status, recent events, health, shortcuts.
- Search: the default page for most users (own node + Central in Phase 2).
- Knowledge: datasets, tags, graph/mesh, indexed material.
- Sources: GitHub sync, file/upload sources, connectors, ingest jobs.
- Ingest: manual ingest and review queue; hidden from readers.
- Agents: MCP setup, Claude/Codex skill install snippets, service accounts.
- Access: seats, users, invites, roles, tokens (Phase 2 seat UI).
- Audit: searchable log of sensitive activity.
- Settings: environment, model/provider, retention, backup.

Role-specific defaults:

- Reader starts on Search and sees no write/admin actions.
- Writer starts on Search or Sources and can ingest/feedback to own node or Central per tags.
- Admin starts on Home and sees Access, Agents, Audit, and Settings.

## Why Search And Ingest Are Separate

Search is a read workflow. Ingest is a write workflow. Keeping them separate is
important because readers should not be able to mutate the Organization Vault.

We can still make the product feel simple:

- Search remains the main page.
- Sources can auto-ingest approved repos/files into Central.
- Ingest becomes a focused admin/writer workflow for manual notes, uploads, and rejected-source review.

## Build Plan

1. Ship Phase 1 token memory scope (`default_dataset`, `default_session`, `allowed_datasets`).
2. Add admin seat UI for provisioning seats and issuing scoped tokens (Phase 2).
3. Add multi-dataset search across own node + Central (Phase 2).
4. Add tag routing for node vs Central lanes (Phase 2).
5. Keep `kb/mcp_server.py` as the MCP capability boundary over FastAPI.
6. Add dashboard Access and Audit pages for seat/token management.
7. Move hosted deployments to OAuth/OIDC when the team grows beyond shared trusted local users.

## Why MCP First

- Claude Code supports project-scoped MCP servers via `.mcp.json`, which can be
  committed so a team has the same tool configuration.
- Codex supports MCP servers directly in `~/.codex/config.toml`, and Codex
  plugins can bundle MCP server configuration.
- OpenAI Responses/Agents workflows can call remote MCP servers, including
  authenticated remote MCP endpoints.
- MCP cleanly separates model-callable tools, read-only resources, and
  user-invoked prompts.

Useful source docs:

- OpenAI Codex skills and plugins: https://developers.openai.com/codex/concepts/customization
- OpenAI Codex plugin MCP bundling: https://developers.openai.com/codex/plugins/build
- OpenAI remote MCP tools: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Code skills: https://code.claude.com/docs/en/slash-commands
- MCP authorization: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization
- MCP tools/resources/prompts: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
