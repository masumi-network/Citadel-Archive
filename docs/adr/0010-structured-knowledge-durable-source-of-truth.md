# Structured Knowledge as the durable source of truth; retrieval engine as a rebuildable projection

Status: accepted (2026-07-15 grill)

## Context

Today the retrieval engine (cognee: Kuzu graph + pgvector) holds the *only*
durable copy of the vault's knowledge. **Structured Knowledge** has no
independent existence — it lives solely inside cognee's graph/vectors. So the
vault inherits every cognee failure mode (session-cache corruption, Kuzu
single-writer locks, loop-binding, 6–9s search) and a cognee wipe loses
everything. In effect Citadel is a wrapper around a store it does not own, even
though the glossary already says the **Knowledge Index** and **Knowledge Mesh**
should be *rebuildable* and **Structured Knowledge** should be the source-linked
company knowledge the vault keeps.

## Decision

**Structured Knowledge becomes the durable, first-class source of truth the
vault owns.** It is retained directly in the runtime vault and **synced to the
Vault Backup Mirror** for recovery. It is:

- **Synthesized at the full (Central) tier only** — on the governed org source
  sync and **Promotion** paths, never on light-tier **Node** captures
  (**Tiered Ingestion** unchanged; a **Node** stays raw captures + light index).
- **Maintained as canonical per-topic knowledge, updated in place.** The
  synthesis step is plan-then-write: the **Promotion Agent** resolves which
  existing **Central** page a candidate belongs to (identity match against page
  briefs, biased toward update) before writing.
- **Contradiction-gated.** A revision that contradicts the existing page raises
  a **Knowledge Conflict** and keeps both sides visible instead of silently
  overwriting; prior versions stay recoverable through the **Vault Backup
  Mirror**.

The **Knowledge Index** and **Knowledge Mesh** (produced by cognee) become
**rebuildable projections of Structured Knowledge**, reached through a
`RetrievalBackend` interface so the engine is swappable in principle. **Cognee
is kept and coexists** — it is good — earning retrieval duty by measurement (a
frozen-fixture eval harness) and remaining the **Knowledge Mesh** builder
regardless of the retrieval outcome. This is per-dataset: each **Node** and
**Central** own their own **Structured Knowledge**, so read isolation
(ADR-0009) holds by construction.

The point that makes Citadel "not just a cognee wrapper" is **ownership**, not
removal: Citadel stops being a wrapper the moment the engine is no longer the
sole owner of the knowledge — not by deleting cognee.

## Considered options

- **Keep cognee authoritative, export Structured Knowledge as a parallel copy.**
  Rejected: still a wrapper, still loses everything on a cognee wipe.
- **Replace cognee retrieval with BM25-over-Structured-Knowledge now.**
  Rejected as premature — the eval harness must decide by measurement; cognee
  may well win and keeps the Mesh regardless.
- **Per-Node synthesis (canonical pages inside every seat Node).** Deferred:
  violates **Tiered Ingestion**, multiplies LLM cost, and risks cross-Node
  isolation leaks. Synthesized knowledge is a **Central** benefit for v1.

## Consequences

- **Contradiction detection is a prerequisite** of safe update-in-place, not an
  independent enhancement.
- **Vault lint** becomes a companion of synthesis — it catches the failure mode
  of LLM identity-resolution (two topics merged, one topic split, near-duplicate
  pages, "term everywhere but no page").
- `citadel reindex` becomes a real, safe operation: drop and rebuild the
  Index/Mesh from Structured Knowledge.
- The **Vault Backup Mirror** finally protects substantive content, not just
  connector state.
- An agent querying its *own* **Node** gets raw captures, not synthesized pages;
  synthesized **Structured Knowledge** is a **Central** benefit.
