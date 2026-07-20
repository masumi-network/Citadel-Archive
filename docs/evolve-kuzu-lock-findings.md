# Evolve pass Kuzu lock — findings (2026-07-20)

Investigation notes for #88 / #89 / #46 / #69. **No decision made; no code changed.**
This exists so the next session starts from verified facts rather than re-deriving them.

## TL;DR

#88's stated root cause is wrong. The Kuzu opens that break the evolve pass are graph
**reads**, not writes — and Kuzu allows concurrent readers. The real defect is that
cognee opens Kuzu **read-write unconditionally**, so a read-only need takes an
exclusive lock the web process already holds.

## Verified by experiment

Kuzu 0.16.0, tested directly (parent holds a read-write handle, children try to open):

| Child opens | Result |
|---|---|
| `read_only=True` | **succeeds** — real rows returned while the parent holds read-write |
| default (read-write) | fails: `RuntimeError: IO exception: Could not set lock on file` |

The read-write failure is the exact production error. `kuzu.Database.__init__`'s docstring
contradicts itself on this point ("Multiple read-only Database objects can be created with
the same database path. However, there cannot be multiple Database objects created with the
same database path") — the experiment is authoritative, the docstring is not.

**Therefore:** one read-write process (the web) plus any number of read-only processes is
a legal Kuzu configuration. Phase-1 graph reads were never inherently in conflict.

## Why the reads take a writer lock anyway

cognee constructs `Database(...)` at three sites in
`.venv/.../cognee/infrastructure/databases/graph/ladybug/adapter.py:279, 301, 336`.
None passes `read_only`. There is no config knob. (Kuzu is aliased as `ladybug` in this
version; `Database` enters the adapter as one module-level symbol at `adapter.py:10`.)

## What actually opens Kuzu (traced)

Two Citadel entry points — `_read_graph_data()` (`kb/cognee_client.py:543-546`) and
`_graph_engine()` (`kb/cognee_client.py:693-695`) — plus, critically, **`cognee.search()`
itself**, which calls `get_graph_engine()` unconditionally even for the `CHUNKS` search
type Citadel configures by default:
`cognee/modules/search/methods/search.py:272`, `get_retriever_output.py:32`.

That last one matters: the library takes the lock in places Citadel's own code gives no
hint of. Any fix resting on "we enumerated the graph-touching call sites" is fragile
across cognee upgrades.

Confirmed **not** to touch Kuzu:
- `remember()` → `cognee.add()` (`kb/cognee_client.py:338`) — relational + pgvector only
  (`cognee/api/v1/add/add.py:222`). The comment at `kb/cognee_client.py:335-337` is accurate.
  **This directly contradicts #88's claim that "plain `learning.learn()` add-writes still
  open Kuzu".**
- `_ensure_cognee_ready` / `_create_cognee_database` (`kb/cognee_client.py:264-268, 293-308`)
- `MeshState.snapshot` (`kb/mesh.py:208`) — JSON projection
- `detect_contribution_conflict` (`kb/conflicts.py:217-248`) — local JSON

## Per-stage reality vs. what the logs claim

The evolve "succeeded=" list is substantially fiction:

| Stage | Logged | Actually |
|---|---|---|
| github_sync | failed | failed. Two graph reads: unconditional vault `search()` (`kb/learning_agent.py:152`) and `run_improve=True` (`config.py:183`) + `ingest_unchanged=True` (`github_sync.py:324`) forcing `improve` → `_graph_counts` → `graph_data` **every pass even when nothing changed** |
| repo_content_sync | succeeded | no-op — `learn()` sits inside the per-file loop behind the unchanged short-circuit (`repo_content_sync.py:452-459`) |
| self_improve | succeeded | **improve step failing and swallowed** (`self_improve.py:224-231`) — still returns `ok: True` |
| promotion | succeeded | never runs — `promotion_enabled` defaults False (`config.py:194`) |
| linear_sync | failed | mechanism unresolved — see open question below |

So #89 is larger than a wrong exit code: at least three independent swallow-and-report-success
sites (`self_improve.py:224-231`, `learning.py:247-252`, `learning_agent.py:153-163`).
The exit code is one symptom of a pattern.

## #69 is already fixed — close it

`scripts/stage_loop.py` + `run_evolve()` wrapping `_run_stages` in `stage_loop()`
(`scripts/run_railway.py:459`) is exactly the fix #69 asked for, covered by
`test_stage_loop_shares_one_event_loop`. Corroborating evidence: #69's symptom was
`got Future attached to a different loop`; #88's is `Could not set lock on file`. The error
changed — the loop-binding fix landed and a different failure took its place.

## The inert lock

`server.py:225` acquires `cognee.writer_lock` around the Phase-1 subprocess. It is an
`asyncio.Lock` — in-process only. It correctly serializes web-internal cognifies and does
**nothing** across processes. #88 is right about this part.

## Options considered

- **(A) Enumerate and patch call sites** — what #88 proposes. Rests on an enumeration that
  has now been wrong three times (write hypothesis, `schedule_cognify` hypothesis, search
  hypothesis), and `cognee.search`'s hidden graph open shows why.
- **(B) Structural guard** — make graph access in Phase 1 raise a named error. Turns the
  enumeration problem over to the test suite. Weakness found late: both cognee modules use
  module-level `from ... import get_graph_engine`, so patching the source module doesn't
  reach them — the guard would need its own consumer-module list, i.e. the same enumeration
  one layer down. Also converts today's quiet degradations into loud failures.
- **(C) Open Kuzu read-only in Phase 1** — wrap the single `Database` symbol at
  `adapter.py:10` to inject `read_only=True` when in Phase-1 mode. Not an enumeration:
  it acts where the lock is actually taken. Reads keep working; a Phase-1 *write* fails
  loudly, enforced by the storage engine rather than by our own guard. Makes "Phase 1 is
  add-only" a property of the process instead of an env-var convention.

**Leaning (C), undecided.** Unresolved risks before it could be built:
1. `init_database()` (`adapter.py:343`) and `LOAD EXTENSION JSON` (`adapter.py:347`) run on
   every open — unknown whether either needs write access. Must be tested against a real
   cognee database, not assumed.
2. It monkeypatches a vendored internal, so it is version-fragile. A guard that silently
   stops guarding is worse than none: needs a startup assertion that the symbol still exists
   plus a test asserting write-fails / read-succeeds.

## Open questions

- **linear_sync's failure mechanism is unexplained.** `linear_sync_run_improve` defaults
  False (`config.py:242`) and its `schedule_cognify` is suppressed by the env var the
  scheduler does set (`server.py:242`). With defaults, nothing there should open Kuzu — yet
  production reports it failing. Either `CITADEL_LINEAR_SYNC_RUN_IMPROVE` is true in prod, or
  a path was missed. Needs a Railway env check of that one key.
- **Latent second bug:** `linear_sync.py:448-464` is guarded *only* by an env var, not a code
  invariant. A Railway-cron `CITADEL_RUN_MODE=evolve` job (per `railway.toml`) does not set
  that var, so in that launch path linear_sync would attempt a real Kuzu write.
- **#89's suggested fix cannot work as written.** It proposes the scheduler record failed
  stages as mesh error events, but `MeshState` is in-memory on `app.state`
  (`kb/server.py:617-620`), web-process-only and ephemeral. The Phase-1 subprocess would
  record into its own throwaway mesh and exit. A results channel back to the parent is a
  prerequisite. (Undecided: JSON summary file via env-passed path / stdout marker / POST to API.)
- **Should a partially-failed pass degrade `/readyz`?** #46 asked for a RED health check.
  Real behaviour change, deploy consequences — undecided.

## Terminology note

`Vault Activity` (CONTEXT.md) is defined as *ephemeral* and *reset with the service*. Any
#89 design that makes stage failures durable/queryable needs to say whether it is extending
Vault Activity or introducing a separate operational-health concept. Not resolved.
