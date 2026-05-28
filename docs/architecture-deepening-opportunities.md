# Architecture Deepening Opportunities

Last updated: 2026-05-28.

This note applies the domain language in `CONTEXT.md` and the decision in
`docs/adr/0001-github-vault-backup-mirror.md` to the current codebase. These are
candidates for deeper modules, not final interface designs.

## 1. Deepen The Vault Learning Module

**Files**: `kb/server.py`, `kb/service.py`, `kb/github_sync.py`,
`kb/obsidian_sync.py`, `kb/mesh.py`, `kb/models.py`

**Problem**: The flow from **Source Material** to **Structured Knowledge** is
spread across route handlers, source sync modules, `Citadel.ingest`, and
`MeshState`. Callers currently need to know too much ordering: filter input,
store or infer source state, call Cognee, record mesh activity, record audit,
and sometimes run improvement. That makes the current modules shallow around the
most important domain behavior.

**Solution**: Create a deeper module for the **Learning Process** that owns the
workflow from accepted **Source Material** through source provenance,
structured ingestion, Knowledge Index refresh, Knowledge Mesh projection, and
audit outcomes. Source-specific modules would feed it source facts instead of
repeating the orchestration.

**Benefits**: Locality improves because source ingestion, provenance, mesh
recording, and error handling stop leaking into every caller. Leverage improves
because tests can exercise one module to verify how source material becomes
vault memory across manual ingest, GitHub sync, Obsidian sync, and future agent
updates.

## 2. Deepen The Repository Daily Update Module

**Files**: `kb/github_sync.py`, `tests/test_github_sync.py`,
`tests/test_github_sync_job.py`

**Problem**: `GitHubOrgSyncer` fetches GitHub data, detects changes, formats the
digest, persists scan state, ingests the result, and optionally runs
improvement. The **Repository Daily Update** rule now says updates should
contain meaningful commits, pull requests, and repository changes only, but that
domain rule is not isolated behind a module.

**Solution**: Create a deeper **Repository Daily Update** module that decides
what source activity is meaningful and formats the update. Keep the GitHub HTTP
adapter focused on fetching raw GitHub activity.

**Benefits**: Locality improves because update quality rules live in one place.
Leverage improves because tests can verify meaningful-change filtering without
running a full GitHub sync or touching Cognee. This also makes it easier to add
pull request detail later without changing unrelated sync state code.

## 3. Add The Vault Backup Mirror Module

**Files**: future module plus `kb/config.py`, `kb/github_sync.py`,
`kb/obsidian_sync.py`, `kb/server.py`

**Problem**: ADR-0001 says Phase 1 uses a private GitHub repository as the
**Vault Backup Mirror**, but there is no module yet where mirror policy can
live. If implemented directly inside source sync routes, redaction, size
limits, manifest shape, and GitHub commits will spread across callers.

**Solution**: Add a dedicated **Vault Backup Mirror** module that owns mirror
export rules, redaction, manifest writing, size policy, and the GitHub adapter
for pushing text-first vault history.

**Benefits**: Locality improves because backup policy is testable without
starting the server or running Cognee. Leverage improves because every source
path can mirror through the same module, and the GitHub adapter can later be
replaced or paired with object storage without rewriting source ingestion.

## 4. Deepen The Access Policy Module

**Files**: `kb/access.py`, `kb/server.py`, `kb/mcp_server.py`,
`tests/test_server.py`

**Problem**: The code stores roles, scopes, principals, tokens, audit events,
and token metadata, but route handlers enforce authorization through scattered
`require_role` calls. The Phase 1 **Agent Action** policy is documented, but the
policy itself is not represented as a module. Scope fields exist even though
Phase 1 access is whole-vault by role.

**Solution**: Deepen access into a policy module that answers whether a
**Vault Member** or **Agent Identity** may perform a named **Agent Action** or
vault operation, then returns the audit facts that should be recorded.

**Benefits**: Locality improves because access decisions stop being distributed
across route handlers and MCP wrappers. Leverage improves because tests can
cover the reader/writer/admin policy directly, including future scoped access,
without needing to exercise every HTTP route.

## 5. Separate Knowledge Mesh From Runtime Projection

**Files**: `kb/mesh.py`, `kb/server.py`, `kb/static/app.js`,
`kb/static/index.html`, `tests/test_server.py`

**Problem**: `MeshState` currently mixes live dashboard projection, event
stream state, metrics, index descriptions, and simplified graph nodes. The
domain now distinguishes **Knowledge Mesh** from runtime UI activity, but the
current module name and interface can make wrapper-level events look like the
actual vault mesh.

**Solution**: Separate the runtime projection from the future **Knowledge Mesh**
module. The current dashboard module can remain focused on UI state and recent
events, while the real Knowledge Mesh module can later expose source, concept,
relationship, and provenance facts.

**Benefits**: Locality improves because UI projection changes do not affect the
domain mesh model. Leverage improves because tests can distinguish "what the UI
shows right now" from "what the Organization Vault knows," which matters once
source snapshots and the backup mirror can rebuild derived artifacts.
