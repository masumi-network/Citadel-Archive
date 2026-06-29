# Dispute handling + corrupt/poisoned-node removal — plan

Status: **approved, not yet built** (2026-06-29). Grounded in a parallel codebase
audit (node lifecycle, moderation machinery, access/audit, surfaces, integrity
gaps) + an adversarial risk pass.

## Goal

Let the org flag a corrupt or **poisoned** node (bad/false/malicious knowledge
that got ingested) and remove it from the vault — with a multi-party dispute
process, not a silent admin delete.

## Core findings (why this needs designing, not just a delete button)

- **Citadel is append-only today.** There is **no delete/remove/forget path** at
  any granularity — not in `CogneeGateway`, `CogneePublicClient`, `Citadel`,
  CLI, MCP, or HTTP. Append-only is deliberate (`kb/self_improve.py:12`; Obsidian
  "delete" is a skip-tombstone, `kb/server.py:2457-2459`).
- **cognee *can* delete, but it's unwired.** cognee 1.2.2 exposes
  `cognee.forget(*, data_id, dataset_id, memory_only)`; smallest real unit = one
  **source document** (+ everything cognify derived from it).
- **Unit reality:** removal targets a whole **source document**, NOT an arbitrary
  single graph entity. A poisoned *shared* entity referenced by many docs can't
  be surgically removed without deleting every source doc that mentions it.
- **No `data_id` is persisted.** Ingest keeps only a content sha256 in an
  in-memory set (`kb/service.py:67-73`), wiped on restart. cognee's `data_id`
  (needed to target a doc for `forget`) is discarded. Capturing it is a hard
  prerequisite for real erasure.

## Decisions (locked)

- **v1 = A (quarantine) + C (dispute queue).** B (hard erase) **deferred**.
- Defaults: **forward-only `data_id` capture** · **permanent re-ingest blocklist
  on uphold** · surfaces **HTTP + web + MCP** (CLI later) · **advisory
  confirmation** for v1 (A is reversible).

## v1 — `feat/dispute-quarantine` (non-destructive, ~3–4 days)

Almost entirely a *clone* of the existing promotion pipeline.

1. **Queue + store** — `kb/dispute_queue.py` (states `pending`/`upheld`/
   `dismissed`), cloned from `kb/promotion_queue.py`; a JSON quarantine set keyed
   by content-fingerprint (+ cognee `data_id` when known).
2. **`data_id` capture** — store cognee's `data_id` at ingest next to the sha256
   (`kb/service.py:67-73`). Forward-only; pre-existing docs are quarantine-able
   by fingerprint, not (yet) hard-erasable.
3. **Containment (A)** —
   - recall post-filter in `Citadel.search` / cognee recall: drop any result
     whose `data_id`/fingerprint is quarantined, before returning.
   - blocklist hook in `_guard_content` (`kb/service.py:83-105`) rejects
     re-ingest of a quarantined fingerprint — mirrors promotion's
     `previously_rejected` (`kb/promotion.py:362-367`, `kb/access.py:683-697`).
     **Mandatory** — without it, Obsidian/GitHub sync re-adds the poison.
4. **Governance (C)** — `kb/dispute.py` `DisputeEngine`, cloned from
   `kb/promotion.py`: writer **flags** → admin **upholds** (→ suppress via A) or
   **dismisses**. `record_event` audit on every transition (`kb/access.py:506-531`).
5. **Surfaces** — HTTP (clone `/api/promotion/*`, `kb/server.py:2724-2803`) ·
   MCP tools `citadel_dispute_*` with `destructiveHint` (clone
   `citadel_promotion_*`) · web **Disputes** sub-tab under Admin. CLI later.
6. **Gating** — flag = writer/`kb:ingest`; uphold = admin + new `knowledge:remove`
   scope (`kb/access.py:43-55`). Advisory confirm for v1.
7. **Tests** — mirror `tests/test_promotion.py`.

## Deferred — B (hard erase via `cognee.forget`)

Only after the v1 `data_id` work lands AND the open questions below are answered.
Blockers the risk pass surfaced:

- **Reversibility was fictional** — `cognee.datasets.delete_data(…, mode='soft')`
  does **not** exist with that signature in the venv; only the deprecated
  `cognee.delete` takes `mode`. `forget(memory_only=True)` keeps the raw file but
  still hard-deletes graph+vector. Re-ground reversibility before building B.
- **Can't target a doc** until `data_id` is persisted (v1 step 2) + a backfill
  story for already-cognified docs (graph provenance, or accept fingerprint-only
  quarantine).
- **Must run in the web process's single FastAPI loop**, serialized against
  cognify/ingest (Kuzu single-writer + cognee loop-binding,
  `kb/server.py:78-90,118-135,283-286`). Never a thread/subprocess/separate service.
- **Blocklist is mandatory** (see A step 3) or removal is self-defeating.

## Open questions to lock before B

erasure-vs-hide threshold · reversibility requirement · `data_id` backfill vs
forward-only · bulk source-scoped purge (poisoned repo/vault/seat) · hard
confirm-token at the API boundary (net-new; no precedent to copy) · permanent
blocklist vs trusted re-add.

## Reuse map

`kb/promotion_queue.py`, `kb/promotion.py`, `kb/access.py` (scopes/audit/
`is_promotion_rejected`), `kb/server.py:2724-2803` (promotion endpoints),
`kb/mcp_server.py` (`citadel_promotion_*` + `ToolPolicy`/`destructiveHint`),
`kb/service.py` (`ingest`/`_guard_content`/recall).
