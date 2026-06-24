---
name: citadel-proactive-ingest
description: Use to capture durable engineering knowledge into Citadel automatically and proactively while working in an org repo. Two halves — (1) instructs the agent to call citadel_ingest mid-session for durable facts/decisions (personal-by-default; only org-ready/vault-contribution tags promote to shared Central), and (2) documents the SessionEnd auto-sync hook that distills each session to the dev's private node with a one-time token setup. Triggers include "auto sync my sessions", "remember this in citadel", "proactive ingest", "set up citadel autosync", "personal kb sync", and https://citadel-archive-production.up.railway.app/skills/proactive-ingest.
---

# Citadel Proactive Ingest

Capture durable engineering knowledge into Citadel **as it happens**, with no
per-session ceremony. Two layers:

1. **Mid-session, agent-driven.** While working, the agent proactively calls
   `citadel_ingest` for durable facts and decisions. Personal-by-default.
2. **SessionEnd, hook-driven.** On every session close, a non-blocking hook
   distills the transcript and POSTs a short note to the dev's PRIVATE node —
   zero per-session steps after a one-time token export.

```
Personal node:  seat:{slug}   (the dev's private Citadel node — default target)
Shared Central: masumi-network (org-wide; only via explicit promotion tags)
Hosted base:    https://citadel-archive-production.up.railway.app
```

Setup first (token + MCP): `https://citadel-archive-production.up.railway.app/skills/connect`
Read/write rules: `https://citadel-archive-production.up.railway.app/skills/vault`

## Personal-by-default (read first)

| Personal (default) | Shared Central (opt-in) |
|---|---|
| No `dataset` field on writes | tag `org-ready` or `vault-contribution` |
| Lands in your `seat:{slug}` node | Promotes to `masumi-network` |
| Only you (+ Central) can read it | Whole org can read it |

A **seat-writer token** carries `default_dataset=seat:{slug}`. Send writes with
**no `dataset` field** and the server's `resolve_write_targets` routes them to
your private node. Do not set `dataset` to promote — use a promotion **tag**
instead, so the seat-node default still applies and the dual-write is audited.

Never let promotion be a surprise. Promote to Central **only** when the user
explicitly asks to share, or the content is plainly org-wide (an ADR, a shared
runbook, an interface contract).

## Layer 1 — proactive mid-session ingest (agent behavior)

While working in an org repo, when a durable fact crystallizes, call
`citadel_ingest` without waiting to be asked. Keep each note small and curated.

**Ingest proactively when:**
- A decision is made (approach chosen, tradeoff settled, library picked).
- A non-obvious root cause is found, or a bug class is understood.
- An interface/contract, env var, or config invariant is established.
- A reusable runbook or "how we do X here" emerges.

**Personal-by-default call (lands in your node):**

```
citadel_ingest(
  data="Picked urllib over requests for the SessionEnd hook so it stays "
       "stdlib-only and dependency-free.",
  tags=["dev-session", "decision"],
)
```

No `dataset` field → seat node. To promote a genuinely org-wide fact, add a
promotion tag (still no `dataset`):

```
citadel_ingest(
  data="ADR: seat tokens default to their seat:{slug} node; writes omit "
       "dataset; promotion is by tag, not by dataset override.",
  tags=["org-ready", "adr"],
)
```

**Never ingest** (same rules as `citadel-vault`): secrets, tokens, keys, seed
phrases, PII, raw logs/debug dumps, ephemeral chatter, or large uncurated
dumps. Summarize durable decisions and source facts instead.

## Layer 2 — SessionEnd auto-sync (the hook)

`scripts/sync_session.py` runs from a Claude Code `SessionEnd` hook. On every
session close it:

1. reads the hook payload (`transcript_path`, `cwd`, `session_id`,
   `hook_event_name`) from STDIN;
2. parses the transcript JSONL **defensively** (skips malformed lines, never
   crashes);
3. distills a **short, deterministic** note — 1-2 line recap, key decisions,
   files changed, notable facts — with **no local LLM call**;
4. derives `tags = ["dev-session", <git-branch>, <repo-name>]`;
5. truncates to `CITADEL_MCP_MAX_INGEST_BYTES` (default 200000);
6. POSTs `{data, tags}` (NO `dataset` → personal node) to `{base}/ingest` with
   `Authorization: Bearer ${CITADEL_MCP_ACCESS_TOKEN}`, **HTTPS only**;
7. **fails silently** — catches everything, exits 0, never blocks session
   close, never prints the token.

Server-side LLM enrichment (`CITADEL_LLM_ENRICHMENT_ENABLED`) does any deeper
structuring after the note lands; the hook stays deliberately dumb and fast.

### One-time token setup (the only step)

Get a **seat-writer** token from the connect wizard
(`https://citadel-archive-production.up.railway.app/skills/connect`) and export
it once:

```bash
export CITADEL_MCP_ACCESS_TOKEN='ctdl_...'
```

That's it. The same token already powers `citadel_search` and the MCP config,
so most devs already have it set. With it in the environment, every session
auto-syncs to your private node. With it unset, the hook is a clean no-op.

### Wire the hook into a repo

Copy `templates/claude-settings.json` into the repo's `.claude/settings.json`
(point the command at this skill's `scripts/sync_session.py`). See
`README.md` in this skill for the drop-in steps and opt-out.

## Privacy posture

- **Token from env only.** Read solely from `CITADEL_MCP_ACCESS_TOKEN`; never
  printed, echoed, or written to a tracked file.
- **Distilled, not raw.** The hook sends a curated short note, not the
  transcript.
- **Personal-by-default.** No `dataset` field on auto-sync → your seat node.
- **HTTPS only.** The POST refuses any non-`https://` base URL.
- **Non-blocking.** The hook always exits 0; a Citadel outage never delays your
  session close.

## Opt-out

Drop a `SessionEnd` override into `.claude/settings.local.json` (gitignored), or
simply unset `CITADEL_MCP_ACCESS_TOKEN` for that shell. With no token the hook
does nothing. See `README.md`.

## Reference

- This skill: `https://citadel-archive-production.up.railway.app/skills/proactive-ingest`
- Connect wizard: `https://citadel-archive-production.up.railway.app/skills/connect`
- Vault read/write rules: `https://citadel-archive-production.up.railway.app/skills/vault`
- Ingest API: `POST /ingest` with `{data, dataset?, tags?, session_id?}` (writer token)
- Seat/node/Central model: [ADR-0003](https://github.com/masumi-network/Citadel-Archive/blob/main/docs/adr/0003-seat-node-central-private-memory.md)
