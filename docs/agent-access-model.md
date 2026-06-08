# Citadel Agent Access Model

Research date: 2026-05-21.

This note defines how Citadel should expose the Organization Vault to humans,
Claude Code, Codex, and autonomous agents. Agent-to-agent communication belongs
to Masumi Agent Messenger; Citadel remains the shared memory and access layer.

## Recommendation

Build one secure Citadel MCP server as the integration layer. Package small
Claude/Codex skills or plugins around it for team workflows.

Skills should teach agents when and how to use Citadel. MCP should be the
actual capability boundary that exposes search, source status, ingestion,
feedback, and admin operations. This keeps one access-control model instead of
separate one-off integrations for every agent.

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

## MCP Surface

Expose these tools first:

- `citadel_search`
  - Role: reader
  - Input: `query`, optional `dataset`, optional `top_k`
  - Output: answer, cited chunks, dataset, confidence notes

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

That is acceptable for local testing and small trusted teams, but it should not
be the long-term sharing model. Production should have durable principals:

- `User`: a human login identity.
- `ServiceAccount`: an agent identity.
- `Team`: a group that owns datasets and sources.
- `Membership`: user or service account plus role inside a team.
- `Dataset`: logical knowledge boundary.
- `Source`: GitHub repo, URL, file upload, manual note, or future connector.
- `ApiToken`: hashed token, owner, scopes, expiry, last-used timestamp.
- `AuditEvent`: immutable trail of search, ingest, source sync, admin action.

Roles:

- Reader: search, view sources/status/events, read resources.
- Writer: reader plus ingest and feedback.
- Admin: writer plus source sync, access management, agent tokens, settings.

Phase 1 agent action policy:

- Reader agents may read, search, and view repository daily updates without
  extra approval.
- Writer agents may add vault contributions, submit feedback, update existing
  writable knowledge, and provide updates.
- Admin or explicit approval is required for source sync, learning/improvement
  jobs, access token changes, role changes, conflict resolution, source deletes,
  and source exclusions.

Phase 1 access boundary:

- Access tokens grant whole-vault access constrained by role.
- Vault members and agent identities are still distinct actors.
- Agent identities communicate through Masumi Agent Messenger and access Citadel
  through their own bearer token or MCP configuration.
- Vault members and agent identities use the same reader/writer/admin role model
  for Citadel access.
- Agent Messenger messages are not automatically Citadel knowledge; a writer or
  admin may intentionally add durable outcomes to Citadel.
- Department, dataset, source, repository, and tool-level scopes are later
  refinements once the initial team workflow is proven.

Future scopes:

- `kb:read`
- `kb:search`
- `kb:ingest`
- `kb:feedback`
- `sources:read`
- `sources:sync`
- `agents:message`
- `agents:manage`
- `access:manage`
- `audit:read`

## Security Rules

- Use browser sessions for humans and bearer tokens/OAuth for agents.
- Store API tokens hashed, never plaintext.
- Let admins create, rotate, disable, and expire agent tokens.
- Scope every Phase 1 token to a role and whole-vault access; add dataset/team
  and tool allowlists after the initial workflow is proven.
- Rate limit per user/service account, especially search and ingest.
- Audit every MCP call with actor, role, tool, dataset, success/failure, and
  request ID.
- Treat retrieved vault content as untrusted context. Do not allow retrieved
  text to override system/developer instructions.
- Sensitive MCP tools must require client approval: sync, improve, delete,
  reindex, invite, token creation.
- Prefer OAuth 2.1 + Protected Resource Metadata for hosted remote MCP. Local
  stdio MCP can use env-provided credentials.

## Dashboard Model

Citadel should feel like an operating-system dashboard with separate apps, not
one crowded page.

Primary navigation:

- Home: status, recent events, health, shortcuts.
- Search: the default page for most users.
- Knowledge: datasets, tags, graph/mesh, indexed material.
- Sources: GitHub sync, file/upload sources, connectors, ingest jobs.
- Ingest: manual ingest and review queue; hidden from readers.
- Agents: MCP setup, Claude/Codex skill install snippets, service accounts.
- Access: users, teams, invites, roles, tokens.
- Audit: searchable log of sensitive activity.
- Settings: environment, model/provider, retention, backup.

Role-specific defaults:

- Reader starts on Search and sees no write/admin actions.
- Writer starts on Search or Sources and can ingest/feedback.
- Admin starts on Home and sees Access, Agents, Audit, and Settings.

## Why Search And Ingest Are Separate

Search is a read workflow. Ingest is a write workflow. Keeping them separate is
important because readers should not be able to mutate the Organization Vault.

We can still make the product feel simple:

- Search remains the main page.
- Sources can auto-ingest approved repos/files.
- Ingest becomes a focused admin/writer workflow for manual notes, uploads, and
  rejected-source review.

## Build Plan

1. Keep the current role-key system for immediate local testing.
2. Add a persistent access store for users, service accounts, roles, tokens, and
   audit events.
3. Add an admin Access page for inviting teammates and issuing role-based agent
   tokens.
4. Build `kb/mcp_server.py` around the existing FastAPI service methods.
5. Add `.mcp.json` for Claude Code project setup, using env-token expansion.
6. Add a Codex plugin or repo skill that bundles the MCP server and Citadel
   workflows.
7. Add dashboard Agents and Audit pages.
8. Move hosted deployments to OAuth/OIDC when the team grows beyond shared
   trusted local users.
