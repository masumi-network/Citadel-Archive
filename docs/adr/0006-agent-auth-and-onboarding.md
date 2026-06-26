# ADR 0006 — Agent authentication & onboarding (OAuth 2.1 + device grant)

- **Status:** Proposed (2026-06-26)
- **Relates:** ADR-0003 (seats), ADR-0005 (secret gate / policy), `skills/citadel-mcp-connector`.

## Context

Teammates connect AI agents (Claude Code, Cursor, Codex, CLIs) to Citadel's hosted
MCP endpoint. Today onboarding is **manual token paste**: create a `ctdl_` token in
the dashboard, paste it into the client's MCP config. That works but is clunky and
error-prone, and it pushes a long-lived secret through copy-paste.

Goal: an **OAuth-style approve-in-browser flow** — the agent triggers auth, the human
approves in a browser, a **seat-scoped, revocable** token is issued automatically, no
paste. The consent screen should also surface the content policy (no secrets — already
enforced server-side by ADR-0005). **Full OAuth 2.1 (MCP Authorization) is the target
end-state.**

Constraint: two client classes behave differently.
- **Native MCP-OAuth clients** (Claude Code, Cursor) can do the OAuth 2.1 redirect flow
  themselves once the server advertises auth metadata.
- **CLIs / non-browser agents** (Codex, scripts, headless) cannot do browser redirects —
  they need the **Device Authorization Grant (RFC 8628)**.

## Decision

**Target: Citadel is an OAuth 2.1 Authorization Server for its MCP Protected Resource,
supporting both the Authorization Code (PKCE) flow and the Device Authorization Grant.**

1. **OAuth 2.1 metadata + endpoints (the full-OAuth goal).**
   - Serve `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`
     (extend the existing `/.well-known/citadel.json` discovery).
   - `/authorize` (Authorization Code + PKCE), `/token`, and **Dynamic Client Registration**
     (`/register`) so Cursor/Claude Code complete the browser flow automatically. A `401`
     from `/mcp/` returns `WWW-Authenticate` pointing at the metadata.
2. **Device Authorization Grant for CLIs.**
   - `/device/authorize` issues a `device_code` + `user_code` + verification URL; the agent
     polls `/token`. The human opens the URL, authenticates, **approves**, and the agent
     receives the token. This is the universal path for Codex/CLIs/headless.
3. **Human authentication = Google SSO (OIDC).**
   - The consent/approval step authenticates the human via Google (org Workspace), verifies
     team membership, and **maps them to (or auto-provisions) their seat → personal node**.
   - The existing admin-key/browser-session login stays as an admin fallback.
4. **Tokens are seat-scoped and revocable, issued through the access store.**
   - The flow mints a **seat-writer** token (`default_dataset=seat:{slug}`) via the existing
     `AccessStore` — **opaque + instantly revocable** (pairs with the admin-console revoke
     work). Short TTL + refresh tokens for the OAuth flow. (JWT access tokens are an option
     but opaque-store-backed wins on revocation; revisit if stateless validation is needed.)
5. **Policy on the consent screen + in the skill.**
   - The approval screen states scope ("read the org vault; write to *your* personal node")
     and the content policy ("secrets are rejected at ingestion — ADR-0005"). The
     `citadel-mcp-connector` skill **routes by client**: OAuth-capable → write the config and
     let the client run the flow; else → trigger the device flow (show URL+code, poll); else →
     manual token. The **server-side secret gate (ADR-0005) is the real guarantee**; the
     consent screen + skill are signage.

## Phasing (the goal is full OAuth; ship value incrementally)

| Phase | What | Why |
|---|---|---|
| A (today) | Wizard seat-token paste + policy notice | Works everywhere now; zero new infra |
| **B** | **Device Authorization Grant + Google-SSO consent** | Approve-in-browser, no paste, for *all* CLIs/agents; reuses access store + dashboard login |
| **C (goal)** | Full OAuth 2.1 metadata + Auth-Code/PKCE + DCR | Native auto-flow for Cursor/Claude Code; the end-state |

Recommended build order: **B then C** (device grant first is the fastest universal win and
shares most infra with C — consent UI, Google SSO, seat-token minting, the access store).

## Consequences

- **+** No copy-paste; browser-approval; seat-scoped + instantly revocable tokens; standards-based
  (works with native MCP-OAuth clients); policy shown at consent; clean reuse of seats + access store.
- **−** Real surface to build: OAuth/OIDC server (or a delegated IdP — Auth0/Clerk/Supabase Auth/
  WorkOS — worth evaluating to avoid hand-rolling), consent UI, token TTL/refresh + rotation, DCR.
  Hand-rolling OAuth is security-sensitive; a vetted IdP/library is strongly preferred.

## Open questions

- IdP: hand-rolled vs delegated (Auth0/Clerk/Supabase/WorkOS) for Google SSO + the OAuth server?
  (Strong lean: delegate the human-auth + token issuance to a vetted provider; Citadel maps the
  resulting identity to a seat.)
- Access-token format: opaque-store-backed (instant revoke) vs short-TTL JWT + refresh.
- Exact MCP-OAuth client support matrix (Cursor/Codex/Claude Code versions) — **verify before C**.
- Seat auto-provisioning policy: who may self-onboard (domain allowlist) vs admin-approval per seat.
- Scopes surfaced at consent (reader vs seat-writer; can a teammate request reader-only?).
