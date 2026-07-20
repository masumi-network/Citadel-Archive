# ADR 0011 — Shared Session Traces as a third storage layer

- **Status:** Proposed (2026-07-20)
- **Amends:** ADR-0007 (seat capture, promotion, and write policy), ADR-0003
  (seat/node/Central private memory)
- **Relates:** ADR-0009 (mesh read isolation — presence vs content),
  `CONTEXT.md` glossary terms: **Session Trace**, **Shared Session Trace**,
  **Seat Presence**, **Approved Capture Roots**, **Capture Policy**.
- **Design spec:** [`docs/superpowers/specs/2026-07-20-shared-session-index-design.md`](../superpowers/specs/2026-07-20-shared-session-index-design.md)

## Context

When one **Vault Member**'s agent works through a problem, the route it took —
what was tried, what failed, and why — is discarded at session end. The next
member's agent rediscovers the same dead ends from scratch. The expensive thing
to rediscover is the failed attempt, and nothing in the system records it.

Citadel today stores **semantic** memory: source-linked facts and decisions,
curated in **Central**. What is missing is **episodic** memory: the route.

The distiller already exists (`kb/hooks/sync_session.py`, SessionEnd hook) and
writes a **Session Trace** to the member's own **Node**. The gap is entirely on
the sharing and retrieval side.

Two prior decisions constrain any solution:

- **ADR-0007:** seat-scoped writes are **Node-only on all channels**; **Central**
  is read-only for seat callers.
- **ADR-0003:** reads never cross seat **Nodes**.

A shared trace index appears to violate both. It does not, but the reason is
non-obvious enough that it must be written down.

## Decision

A **Shared Session Trace** is a **Session Trace** its author has volunteered to
the organization. Shared traces live in a dataset (`session-traces`) that is
**neither a Node nor Central**: readable by every **Seat**, writable by a seat
only for its own traces, and never curated.

### 1. A third storage layer, deliberately

| Layer | Dataset | Write | Read | Curated |
|---|---|---|---|---|
| **Node** | `seat:{slug}` | own seat only | own seat only | no (light tier) |
| **Shared Session Traces** | `session-traces` | own seat, own traces, opt-in | **all seats** | **no — never** |
| **Central** | `masumi-network` | governed sync + **Promotion** | all seats | yes (full tier) |

Traces are **consultable prior work, not Structured Knowledge**. They carry no
claim of being true, are never synthesized into canonical pages, and are never
promoted to **Central**. This is the whole reason they get their own layer
rather than joining **Central**: routing unverified episodic records through the
curated path would poison the synthesis that makes **Central** trustworthy.

### 2. How this amends ADR-0007

ADR-0007's "Node-only on all channels" becomes:

> Node-only, **except** content the seat explicitly volunteers as a
> **Shared Session Trace**.

The invariant ADR-0007 was actually protecting survives intact: **no
involuntary seat write leaves the Node.** ADR-0007 removed the seat's *implicit*
org-tag route to **Central** precisely because it fired without the member
choosing it. Volunteering a trace is the opposite — an explicit act, per repo or
per session.

**Central** remains strictly read-only for seat callers. This ADR opens no path
from a seat to **Central**.

### 3. How this relates to ADR-0003

"Reads never cross seat **Nodes**" holds **literally and without exception**. A
**Shared Session Trace** is a *copy* written to a separate dataset; no seat ever
reads another seat's **Node**. Stated explicitly because the feature looks like
a violation until the copy is noticed — the same dual-write shape ADR-0003
already chose for **Promotion**.

### 4. Approved Capture Roots are the outer boundary

Both consent paths are bounded by **Approved Capture Roots** and the merged
**Capture Policy** deny globs. Roots decide what may leave the machine *at all*;
the consent level decides whether a trace is additionally shared.

| | Root, `share_traces=true` | Root, `share_traces=false` | Not a root |
|---|---|---|---|
| **Automatic** (SessionEnd hook) | shares | no | no |
| **Explicit** (`citadel_share_session`) | shares | shares that one | **refused** |

A trace from a path outside **Approved Capture Roots** is refused with an
actionable message, never shared silently. The root check is enforced
**server-side**: the share tool is reachable by any writer token, and a
client-side check on a token-bearing path is not a check.

### 5. Attribution without verdicts on people

A **Shared Session Trace** always carries its author **Seat** — so members can
follow up, and so bad guidance is attributable.

Outcome is recorded per *approach* (`resolution: solved | superseded | dead_end`)
and never as a verdict on the session or its author. "This approach was a dead
end" is a fact about the code; "this member abandoned this" is a claim about a
person. The vault records the first and never the second.

This also protects the feature's value: abandoned work is the most useful thing
to share, and members will stop sharing it if sharing produces a durable public
record of their failures.

### 6. A third ingestion tier: enriched, never synthesized

**Tiered Ingestion** becomes three tiers rather than two:

| Tier | Content | Enrichment | Synthesis |
|---|---|---|---|
| light | **Node** capture | no | no |
| **shared** | **Shared Session Trace** | **yes** | **no** |
| full | org sync, **Promotion** | yes | yes |

Detecting a tool *failure* is mechanical; detecting a *dead end* — an approach
tried and then abandoned — is semantic. So dead-end distillation needs an LLM.
Placing it server-side and only on the shared tier keeps three properties at
once: the SessionEnd hook stays stdlib-only and never egresses transcript
content to a model provider; private **Node** memory is never enriched, exactly
as today; and LLM cost is paid only for traces a member chose to share.

Shared traces are enriched but **never synthesized**. Synthesis is what produces
canonical **Structured Knowledge**, and a trace makes no claim of being true.
Enrichment is the price of volunteering content to the org; synthesis remains a
**Central** benefit.

### 7. Seat Presence is unchanged

`CONTEXT.md` **Seat Presence** now reads "never includes **Node** content
disclosed *involuntarily*". Shared traces are disclosure by choice and are
governed by this ADR, not by **Seat Presence**. The ADR-0009 rule stands: the
org broadcast still carries presence only — counts, timing, seat slug — never
**Node** content.

### 8. Retrieval

A new MCP tool, `citadel_prior_work(task, files, repo)`, ranks on file-path
overlap, then same-repo, then semantic fill over `session-traces` only. Results
render inside a fenced, attributed, reference-only wrapper.

Read scope is **org-wide**, consistent with `CONTEXT.md:311` — department-scoped
access was considered for the first version and resolved against.

## Considered Options

- **Route traces through the Promotion queue (ADR-0007's existing lane).**
  Least new authorization surface and a perfect fit for the existing model.
  Rejected: promotion requires human approval per item, and an approval queue
  on a per-session-volume feed dies from neglect — taking the feature with it.
  Promotion exists to gate what becomes *org truth*; traces make no truth claim.

- **Put traces in Central under an `org-ready` tag.** No new layer at all.
  Rejected: **Central** is curated **Structured Knowledge** with full-tier
  synthesis. Unverified episodic records would be synthesized into canonical
  pages as though they were source-linked fact. It would also require reopening
  the seat→Central write path that ADR-0007 deliberately closed.

- **Share every Session Trace by default, with opt-out.** Maximum coverage, and
  the feature only pays off at volume. Rejected: reverses the
  personal-by-default invariant that ADR-0003 and the whole seat model rest on.

- **Keep traces Node-private; solve reuse by having members write notes.** Zero
  new risk. Rejected: this is the status quo, and it does not happen — the
  distiller has been shipping Node traces and none of them are reachable.

## Consequences

- **+** Episodic memory becomes reusable across the org without touching
  **Central**'s curation guarantees or the **Node** isolation boundary.
- **+** Reuses **Approved Capture Roots** as the consent surface rather than
  inventing a second one.
- **−** A third dataset class in a codebase whose write and read routers assume
  a Node/Central dichotomy. Every branch of the form "Central, else it must be a
  seat node" is now a latent bug. These must be found and fixed, not assumed
  absent.
- **−** A high-volume write source contending for the single-writer Kuzu
  cognify lock (#47), alongside the evolve scheduler, GitHub/Linear sync, and
  git-push hooks. Requires coalescing before the 15-seat rollout.
- **− Accepted risk:** cross-seat prompt injection is **contained, not
  prevented**. A trace authored by an authenticated teammate enters another
  member's agent context. Containment is structural — typed fields, fenced
  render, author attribution — with no LLM screening in v1. Related open item:
  M2 (prompt-injection promotion gate).
- **Unresolved at proposal time:** retention policy for an uncurated,
  monotonically growing dataset, and whether a delete/retraction path exists at
  all in the current stack.

## Open questions

- Retention: what bounds `session-traces` growth, and does the stack support
  deletion of ingested content?
- Retraction: `citadel unshare <trace-id>` is required to make per-repo standing
  consent safe, but depends on the deletion answer above.
- Cognify coalescing window, tuned against measured seat volume.
