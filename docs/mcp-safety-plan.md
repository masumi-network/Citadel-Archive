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

Citadel currently has four relevant layers:

- `kb/server.py`: the real FastAPI service and access-control boundary.
- Hosted `/mcp/`: streamable HTTP MCP mounted into the same FastAPI process.
  Each request authenticates with `Authorization: Bearer <ctdl_token>` and is
  checked by the same role/scope API boundary.
- `kb/mcp_server.py`: the MCP implementation and local stdio fallback. Hosted
  requests use the caller's bearer token; stdio fallback uses
  `CITADEL_MCP_ACCESS_TOKEN`.
- Public skill/discovery surfaces: `/skills`, `/skills/*`, and
  `/.well-known/citadel.json`, which publish metadata only.
- `plugins/citadel-archive-mcp/`: a thin Codex plugin that bundles `.mcp.json`
  and a skill for clients that still need packaged setup.

The current production path uses Citadel-issued bearer tokens, per-token scopes,
approval guidance, MCP tool annotations, and audit attribution. OAuth/OIDC
protected-resource metadata remains the later enterprise-auth path; until then,
the bearer-token MCP endpoint must keep strict HTTPS, scope checks, per-agent
tokens, and redacted audit/error surfaces.

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
10. Serve public skill/discovery metadata with integrity hashes and browser
    security headers; never include vault contents or tokens in public metadata.

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

Status on 2026-06-03: implemented and extended. Hosted `/mcp/` is the primary
path, stdio remains a fallback, `citadel_discovery` and `citadel://discovery`
publish safe metadata, MCP calls are tagged in audit logs, and public skill files
carry content hashes.

## Phase 2: Scope Enforcement

Goal: make Citadel tokens least-privilege in the API, not just descriptive in
the UI.

Status on 2026-06-03: implemented. `kb/server.py` uses `require_access(role,
scope)` on protected API routes, bootstrap env keys receive the default scopes
for their role, and scoped service-account tokens are denied when the required
scope is missing. `kb/access.py` rejects custom token scopes that exceed the
selected role.

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

Status on 2026-06-03: implemented for hosted and stdio-forwarded MCP calls.
`kb/mcp_server.py` forwards `X-Citadel-MCP-Tool`, and `kb/server.py` records
`mcp.<tool_name>` audit events in the persistent access store. Events include
actor, role, tool, path, required role/scope, dataset when known, success/failure,
status or redacted error class, and safe counts/hashes instead of raw queries,
note bodies, feedback text, or tokens. Admins and agents with `audit:read` can
query `/api/audit` with `view=all|mcp|access|failures` and an optional bounded
`limit` to retrieve the same filtered audit view outside the dashboard. MCP
admins can use `citadel_audit_events`, which calls the same API with a bounded
client-side limit.

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

## Phase 6: Hosted MCP Auth Evolution

Goal: evolve the hosted MCP endpoint from Citadel-issued bearer tokens to a
standards-based OAuth/OIDC profile when the organization needs enterprise SSO.

Tasks:

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

## Phase 7: Browser And Public Surface Hardening

Status on 2026-06-03: implemented for baseline headers.

Tasks:

- Serve dashboard, JSON, public skill files, static assets, and MCP responses
  with baseline browser security headers:
  - strict self-only Content Security Policy.
  - `X-Content-Type-Options: nosniff`.
  - `X-Frame-Options: DENY` plus `frame-ancestors 'none'`.
  - `Referrer-Policy: no-referrer`.
  - restrictive `Permissions-Policy`.
  - same-origin cross-origin opener/resource policy.
- Set HSTS only for HTTPS or HTTPS-forwarded requests.
- Keep login JavaScript in `/static/login.js`; do not reintroduce inline login
  script that would require `unsafe-inline`.
- Use explicit cache policy:
  - public skill/discovery/static metadata: `Cache-Control: public, max-age=300`.
  - health, login, authenticated API, vault search/document, audit, and MCP
    responses: `Cache-Control: no-store` and `Pragma: no-cache`.

## Acceptance Criteria

- A reader MCP token cannot mutate Citadel.
- A writer MCP token cannot run admin jobs.
- Write/admin MCP tools are approval-gated in the documented Codex setup.
- Tokens are never printed in normal MCP errors.
- Non-local HTTP Citadel endpoints are blocked by default.
- MCP calls are attributable in audit logs.
- Public and authenticated HTTP responses include browser security headers.
- Plugin validation and the Python test suite pass.

## First Implementation Slice

Start with Phase 1 only:

1. Add tool annotations and a tool catalog to `kb/mcp_server.py`.
2. Add base URL validation and MCP error redaction.
3. Add focused MCP unit tests with fake HTTP clients.
4. Update README/plugin docs with safe Codex approval policy.

That slice improves safety without changing the hosted Citadel API contract.
