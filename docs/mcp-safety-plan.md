# Citadel MCP Safety Plan

Research date: 2026-06-01.
Status: draft.

This plan defines how to make the Citadel MCP integration safe enough for team
agents while preserving the current architecture: Codex or Claude launches a
local stdio MCP wrapper, and that wrapper calls the hosted Citadel HTTP API with
a scoped service-account token.

## Sources Checked

- MCP authorization specification, latest 2025-11-25:
  https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- MCP security best practices:
  https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- MCP tools and schema reference:
  https://modelcontextprotocol.io/specification/2025-11-25/schema
- OpenAI MCP and connectors safety guidance:
  https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- OpenAI Codex customization guidance:
  https://developers.openai.com/codex/concepts/customization
- OpenAI Codex plugin build guidance:
  https://developers.openai.com/codex/plugins/build
- MCP Python SDK server guide:
  https://py.sdk.modelcontextprotocol.io/server/

## Current Shape

Citadel currently has three relevant layers:

- `kb/server.py`: the real FastAPI service and access-control boundary.
- `kb/mcp_server.py`: a local stdio MCP wrapper that forwards calls to the
  FastAPI service with `Authorization: Bearer <CITADEL_MCP_ACCESS_TOKEN>`.
- `plugins/citadel-archive-mcp/`: a thin Codex plugin that bundles `.mcp.json`
  and a skill.

This is the right default for phase 1. The latest MCP authorization spec says
HTTP transports should follow the MCP OAuth authorization profile, while stdio
transports should retrieve credentials from the environment. Citadel is doing
the stdio/env path today.

Do not expose a hosted remote HTTP MCP server yet. The hosted remote path should
be a later OAuth/OIDC project, not a quick wrapper around the current bearer
token API.

## Threat Model

Assets:

- Citadel bearer tokens and admin keys.
- Organization Vault content, search results, Obsidian documents, source
  digests, feedback records, and audit trail.
- Admin actions: source sync, learning-agent run, Cognee improvement, token
  management.
- Runtime secrets used by Cognee, OpenRouter, GitHub, Railway, or future
  connectors.

Primary risks:

- Prompt injection from retrieved vault/source content.
- Accidental write/admin tool use by an agent.
- Overprivileged long-lived service-account tokens.
- Token leakage through errors, logs, browser output, or copied config.
- Role-only enforcement while token scopes are stored but not enforced.
- Missing MCP-specific audit records.
- Local MCP command compromise via malicious plugin/config changes.
- Future remote-MCP risks: confused deputy, token passthrough, OAuth discovery
  SSRF, session hijacking, and weak audience validation.

## Safety Principles

1. Keep stdio local-first until OAuth/OIDC is implemented.
2. Make read-only the default agent profile.
3. Require explicit approval for write and admin tools.
4. Enforce scopes server-side; do not rely only on roles or tool descriptions.
5. Treat all retrieved vault/source content as untrusted model context.
6. Never pass through third-party tokens. Citadel MCP tokens must only be for
   Citadel.
7. Audit every mutating or admin MCP operation, and preferably every MCP call.
8. Minimize output size and redact secrets in error surfaces.
9. Use MCP tool annotations for client UX, but treat annotations as hints, not
   enforcement.

## Phase 1: Local Stdio Hardening

Goal: make the existing plugin and `kb/mcp_server.py` safe for local team use.

Tasks:

- Add a single MCP tool catalog in `kb/mcp_server.py` with each tool's role,
  required scope, risk class, and annotation metadata.
- Add MCP `ToolAnnotations` through `FastMCP.tool(...)`:
  - `citadel_session`: read-only, closed-domain.
  - `citadel_search`, `citadel_get_mesh`, `citadel_list_sources`: read-only,
    conservatively open-world because returned content can originate from
    learned external sources.
  - `citadel_ingest`, `citadel_record_feedback`: additive writes, not
    destructive, not idempotent.
  - `citadel_run_learning_agent`, `citadel_improve`: admin operations,
    approval-required by client config.
- Add an MCP HTTP client base URL guard:
  - allow `http://localhost` and `http://127.0.0.1` for local development.
  - require `https://` for non-local Citadel servers unless an explicit
    `CITADEL_MCP_ALLOW_INSECURE_HTTP=true` escape hatch is set.
- Redact tokens and secret-shaped values from MCP error messages.
- Add MCP-side input clamps:
  - cap `top_k` to a conservative maximum.
  - cap ingest payload size in the MCP wrapper before forwarding.
  - reject empty or whitespace-only write payloads.
- Add tests for:
  - missing token error does not leak secrets.
  - base URL guard rejects non-local HTTP.
  - reader token cannot call writer/admin endpoints.
  - writer token cannot call admin endpoints.
  - annotations are present on registered tools.
  - HTTP error details are redacted.
- Update `skills/citadel-vault/SKILL.md` with the
  read/write/admin safety policy.
- Add README snippets for safe Codex plugin MCP policy:
  - enable read tools by default for a reader service account.
  - require approval for `citadel_ingest` and `citadel_record_feedback`.
  - require approval, or disable by default, for `citadel_run_learning_agent`
    and `citadel_improve`.

## Phase 2: Scope Enforcement

Goal: make Citadel tokens least-privilege in the API, not just descriptive in
the UI.

Tasks:

- Add `require_scope(request, scope)` or `require_access(request, role, scope)`.
- Map every endpoint to a required scope:
  - search/session/mesh/index/source reads: `kb:read`, `kb:search`, or
    `sources:read`.
  - ingest: `kb:ingest`.
  - feedback: `kb:feedback`.
  - source sync and learning-agent runs: `sources:sync`.
  - access management: `access:manage`.
  - audit reads: `audit:read`.
- Reject custom token scopes that exceed the selected role's allowed scopes.
- Add regression tests for role/scope combinations.

## Phase 3: MCP Audit Trail

Goal: make agent activity attributable.

Tasks:

- Have `kb/mcp_server.py` send a header such as `X-Citadel-MCP-Tool` for each
  forwarded request.
- Record audit events for all MCP calls, or at minimum all write/admin calls.
- Store actor ID, token ID, tool name, dataset, success/failure, and redacted
  error class.
- Avoid logging raw search queries by default; store a hash or short preview.
- Add dashboard filtering for MCP-originated audit events.

## Phase 4: Safe Agent Token UX

Goal: make the safe path the easiest path.

Tasks:

- Add an Agents page flow for creating MCP service-account tokens.
- Default to reader tokens with expiry.
- Offer explicit profiles:
  - Reader: search/session/mesh/source status.
  - Writer: reader plus ingest/feedback.
  - Admin: only for operators, not default agent use.
- Show copyable `.mcp.json` and Codex plugin policy snippets.
- Add token rotation and quick revocation guidance.

## Phase 5: Prompt-Injection And Output Handling

Goal: reduce the chance that retrieved memory controls the agent.

Tasks:

- Wrap search results with explicit metadata:
  - `retrieved_content_is_untrusted: true`
  - source IDs, datasets, timestamps, and confidence fields.
- Clip long result bodies and provide source IDs for follow-up retrieval.
- Add a malicious-content regression test where a search result instructs the
  agent to ignore system instructions; the skill and prompt text must frame it
  as untrusted.
- Treat URLs from vault content as untrusted. Do not embed or auto-fetch them
  in client code without domain review.

## Phase 6: Hosted Remote MCP, Later

Goal: expose Citadel as a real remote MCP server only after auth is ready.

Tasks:

- Add a separate remote MCP endpoint using streamable HTTP, not the stdio
  wrapper.
- Implement MCP protected resource metadata.
- Use OAuth/OIDC access tokens with:
  - bearer auth on every request.
  - audience/resource validation for the Citadel MCP server.
  - short-lived access tokens and refresh-token rotation where applicable.
  - no tokens in query strings.
  - 401 for missing/invalid tokens and 403 for insufficient scopes.
- Map OAuth scopes to Citadel scopes.
- Do not pass through OAuth tokens to downstream services. If Citadel needs to
  call another API, use Citadel-owned credentials or an explicitly separate
  downstream token flow.
- Add SSRF controls if Citadel ever becomes an MCP client that fetches OAuth
  metadata from arbitrary remote MCP servers.

## Acceptance Criteria

- A reader MCP token cannot mutate Citadel.
- A writer MCP token cannot run admin jobs.
- Write/admin MCP tools are approval-gated in the documented Codex setup.
- Tokens are never printed in normal MCP errors.
- Non-local HTTP Citadel endpoints are blocked by default.
- MCP calls are attributable in audit logs.
- Plugin validation and the Python test suite pass.

## First Implementation Slice

Start with Phase 1 only:

1. Add tool annotations and a tool catalog to `kb/mcp_server.py`.
2. Add base URL validation and MCP error redaction.
3. Add focused MCP unit tests with fake HTTP clients.
4. Update README/plugin docs with safe Codex approval policy.

That slice improves safety without changing the hosted Citadel API contract.
