# Read-side Hardening Sprint (issues #25–#49)

Status doc for the production-readiness sprint that resolves the heavy-user +
pentest findings filed as GitHub issues **#25–#49**. Self-contained so a fresh
session can resume without external scratch state. Last updated 2026-06-30.

## Origin

Two rounds of black-box testing against the production node surfaced a broken
read/write data plane behind green dashboards. Root insight: durable writes were
routed through cognee's per-session cache, which corrupted them to the literal
`[DataItem]` and never indexed them. See memory `citadel-session-id-cache-corruption`.

## Done — merged to `main` (auto-deployed to Railway), each with tests

| PR | Issues | Summary |
|----|--------|---------|
| #54 | #26, #32 | Durable writes go through cognee's permanent `add+cognify` path, not the session cache. **Verified live on the node** (a marker ingested post-deploy returns as real cognified text, `belongs_to_set: []`). |
| #56 | (latency) | `run_in_background=True` so ingest returns promptly instead of blocking on inline LLM cognify (fixed a timeout the #54 verification exposed). |
| #57 | #29 | MCP `citadel://` resource reads thread the caller token via `mcp.get_context()`. |
| #58 | #31 | `cognify` exits nonzero on failure: LLM-key guard + top-level `ok` reflects the `--verify` canary. |
| #55, #59 | #37 | Service version single-sourced from `kb.__version__` (hatchling dynamic); node reports real 0.2.1 instead of `0.1.0`/`0+unknown`. |
| #60 | #49 | Clamp search `top_k` to `[1,100]` at the `Citadel.search` chokepoint; 413 byte cap on `/ingest` + `/api/contribute`. |
| #61 | #30, #42 | Surface `authenticated` flag + warning on both syncers; repo-content `ok:False` (exit 1) when all repos error; webhook re-ingest records mesh errors. |
| #62 | #34 | Marker-based repo auto-join (AGENTS.md/CONTEXT.md/SKILL.md, opt-in) + index AGENTS.md. |

**Closed:** #26, #29, #30, #31, #32, #34, #37, #42, #49.

## Remaining — fix specs generated (apply → test → merge, one PR each)

Each was investigated and has a concrete, conservative fix. Approach summary:

- **#45 MCP 406 + #33 admin-tool filter** (`kb/mcp_server.py`, `kb/server.py`):
  - #45: FastMCP streamable-HTTP returns 406 unless `Accept` lists *both*
    `application/json` and `text/event-stream`. Add a pass-through ASGI shim on
    the mounted `/mcp` app that augments the `Accept` header so minimal clients
    (Pi) connect. LOW.
  - #33: `tools/list` advertises all 21 tools incl. 6 admin tools to writer
    seats. Add a request-scoped role-aware filter (resolve role via
    `resolve_client(ctx).get("/api/session")`, hide tools whose
    `ROLE_ORDER[policy.role]` exceeds the caller; fail open). Keep server-side
    403 as defense-in-depth. LOW.
- **#28 get_document drilldown** (`kb/server.py`, `kb/cognee_client.py`): cognee
  CHUNKS hits carry a synthetic `chunk:{sha}` id with no backing store →
  `get_document` 404s. Add a vector-store chunk resolver (or thread a resolvable
  `doc_` id into cognee external_metadata at ingest) and advertise a working
  `/api/documents` endpoint for chunk hits. MED.
- **#46 Linear sync fail** (`kb/linear_sync.py`): evolve linear stage fails every
  cycle on a runtime `LinearAPIError` (auth/scope/rate-limit — needs
  `LINEAR_API_KEY`, likely a runtime secret, not a code bug) that `run()`
  swallows; `mirror_count 0` because no Linear assignee email matches a seat
  email. Surface the fetch failure as structured `ok:False` + add
  assignee/seat-email diagnostics. LOW (code); runtime secret needed to fully
  resolve.
- **#39 + #48 promotion** (`kb/promotion_client.py`, `kb/promotion.py`,
  `kb/server.py`, `kb/cli.py`):
  - #39: a read `TimeoutError` escapes `_request`'s URLError-only handler →
    raw traceback + exit 0. Catch `TimeoutError`/`OSError` in `_request`;
    decorate the four promotion CLI handlers with `@_needs_server`.
  - #48: approve/reject gate on `require_access("writer","kb:ingest")`, so a
    seat-writer passes and a bogus id 404s before any admin check (a real item
    lets a seat self-promote into Central). Require `("admin","sources:sync")`
    so the role gate 403s before id resolution; align the two MCP ToolPolicy
    entries. MED — security-relevant.
- **#40 + #41 writer-seat** (`kb/service.py`, `kb/cognee_client.py`,
  `kb/cli.py`): both are false-green CLI bugs. #40 feedback drops silently
  (`recorded:false`, exit 0). #41 improve crashes three ways (UNIQUE
  `users.email` / empty graph / missing LLM key) and exits 0. Surface a clear
  reason + nonzero exit per failure mode; make cognee's default-user bootstrap
  idempotent. MED.
- **#35/#36/#38/#43 onboarding** (`kb/cli.py`, `kb/onboard.py`,
  `kb/tool_detect.py`, `kb/capture_config.py`): the interactive capture wizard
  wrote an empty `capture.json` (flipping the pre-push hook to fail-closed),
  never collected an LLM key, installed Claude session hooks at project scope,
  and left Claude MCP snippet-only. Seed the repo root (never persist empty
  roots, #43), offer an OpenRouter key (#35), move session hooks to
  `~/.claude/settings.json` + doctor check (#38), promote Claude to a write-tier
  `claude mcp add --scope user` handler + pi/keychain note rewording (#36). MED,
  largest item.

## Remaining — design/high-risk (do carefully, verify on node)

- **#27 health gates** (`kb/status.py`, `kb/service.py`, `kb/server.py`): make
  `check_search` honest (`ok = count > 0`) and fold it into `report.healthy`;
  add an indexed-docs-vs-tracked-sources corpus-volume gate; wire the existing
  `cognify_dataset(verify=True)` canary into `/readyz` or the evolve scheduler.
  Note: canary `ok = search_hit OR graph_grew` passes on growth alone — tighten
  with a short retry given background cognify.
- **#44 search timeout** (`kb/server.py`, `kb/service.py`, `kb/cognee_client.py`):
  `citadel_search` times out ~100s+. May partly ease now that #26 removed the
  `[DataItem]` bloat — re-measure on the node first, then address the cognee
  recall/search perf path. HIGH.
- **#47 Kuzu single-writer lock** (evolve scheduler / `kb/server.py` /
  `kb/cognee_client.py`): `cognify_session` crashes hourly (`Lock held by PID`).
  Serialize Kuzu writers / coordinate cognify so concurrent writers don't
  collide. HIGH — concurrency, live graph. See memory
  `citadel-evolve-cognify-concurrency`.

## Follow-up

- **#15 (no issue) purge legacy garbage**: #54/#56 fix *new* writes, but the live
  graph still holds old `[DataItem]` + `user_sessions_from_cache` entries
  (confirmed via node search). Add an admin cleanup that deletes those nodes,
  then re-run github/linear/repo-content sync to repopulate real content.

## Working agreement for this sprint

- One compartmentalized branch per issue/group off `main`; test (full `pytest`)
  before merge; merge = prod deploy (auto-deploy on `main`).
- Low-risk fixes auto-merge; the three HIGH-risk data-plane/concurrency items
  (#44, #47, and the data-plane work already done) get a node verification.
- No `Co-Authored-By`/"Generated with" trailers (repo convention).
