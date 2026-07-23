<!-- citadel-agent-policy:start -->
# Citadel — agent policy
- At task start: prefer MCP `citadel_search` when present and working (Central + your Node + Shared Session Traces).
- Fallback: MCP `citadel_*` → CLI (`citadel status`, then `citadel search` / `citadel doctor`) → else official/canonical docs (live OpenAPI, MIP, DevHub); say when the vault was unavailable.
- Never claim vault-backed / Citadel authority without a successful search hit (MCP or CLI) in this session.
- Never claim “Citadel confirms X” without a retrieved note title + snippet from that hit.
- Never use Citadel as sole authority for Mainnet asset IDs / payment token units (USDCx, USDM, tUSDM, policy+asset hex) — prefer official Masumi docs / `skills/masumi` (or masumi skill refs). For token/asset-ID queries: official docs / skill first, or immediately after an empty vault.
- If the vault has no durable token/asset note, say so honestly (“no authoritative hit”) rather than inventing IDs or citations.
- If the user asks to use Citadel / the vault, search is in-scope (allowlist: vault read via MCP or `citadel search`).
- Trace hits carry `_citadel.trust: reference-only` — verify before acting; Central stays org-authoritative.
- Prefer `trust_tier: canonical|verified` for API/spec claims; treat `ambient` / digests as pointers only.
- Share dead-end routes with `citadel_share_session` only after explicit user approval.
- Search telemetry is automatic (non-blocking) on every `citadel_search`; optionally rate hits with `citadel_record_feedback` (writer) using hit `id` / `search_id` and score 1|-1.
<!-- citadel-agent-policy:end -->
