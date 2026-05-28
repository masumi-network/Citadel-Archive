# Citadel Obsidian Integration Plan

Research date: 2026-05-28.

This note summarizes the official `obsidianmd` GitHub/docs research and the
implementation path for making Citadel feel like an Obsidian-style shared vault,
while adding team access, source sync, and an Obsidian companion plugin.

## Source Reality

Obsidian's desktop app source is not public. The official organization is still
useful because it exposes the plugin API, sample plugin, developer docs,
community release registry, JSON Canvas format, importer, clipper, headless sync
tooling, help vaults, translations, sample theme, and ecosystem lint rules.

Primary sources:

- https://github.com/obsidianmd
- https://github.com/obsidianmd/obsidian-api
- https://github.com/obsidianmd/obsidian-sample-plugin
- https://github.com/obsidianmd/obsidian-developer-docs
- https://github.com/obsidianmd/obsidian-releases
- https://github.com/obsidianmd/jsoncanvas
- https://github.com/obsidianmd/obsidian-importer
- https://github.com/obsidianmd/obsidian-clipper
- https://github.com/obsidianmd/obsidian-headless
- https://github.com/obsidianmd/obsidian-maps
- https://docs.obsidian.md
- https://obsidian.md/help

## Product Direction

Citadel should not clone Obsidian as a local desktop note app. It should borrow
the mental model that works: vault, files, links, backlinks, graph, command
ribbon, side panes, properties, canvas, and extensions.

Citadel's value is the shared, server-side layer:

- role-gated team knowledge base
- durable source ingestion and sync
- graph and GraphRAG over documents, chunks, entities, claims, citations, and
  provenance
- MCP/agent access with auditability
- optional Obsidian plugin for teams already living in vaults

## Interface Recommendations

P0 interface changes:

- Use an Obsidian-like application shell: left ribbon, file/source explorer,
  central document or graph workspace, right context panes, and status surface.
- Make "Vault", "Graph", "Sources", "Agents", "Access", and "Audit" feel like
  workspace panes rather than separate marketing pages.
- Provide linked context panes for backlinks, outgoing links, source provenance,
  GraphRAG context, and agent/MCP activity.
- Align visual tokens with Obsidian's documented color variable model, while
  keeping Citadel's own identity.

P1 interface changes:

- Add saved per-user and shared workspace layouts.
- Add local graph depth controls, filters, groups, orphan/dead-link visibility,
  and provenance edge labels.
- Add a source sync status pane with current cursor, last run, failures, and
  retry actions.
- Add conflict review UI before bidirectional sync is allowed.

## Canonical Knowledge Model

Use Obsidian-compatible formats at the boundary, not as the only data model.

Citadel's canonical model should include:

- documents
- chunks
- entities
- claims
- links
- backlinks
- tags
- properties/frontmatter
- attachments
- source revisions
- sync cursors
- conflicts
- embeddings
- ACLs
- audit events
- agent-access metadata

Obsidian compatibility should include:

- Markdown files
- YAML frontmatter/properties
- wikilinks
- Markdown links
- tags
- aliases
- headings
- block references
- embeds
- attachments
- `.canvas` import/export via JSON Canvas

## JSON Canvas

Use JSON Canvas as an import/export and persisted layout projection. Do not make
it the canonical graph store.

P0:

- Import `.canvas` files into Citadel.
- Export graph projections to `.canvas`.
- Preserve unknown JSON Canvas keys so round trips do not destroy user data.
- Map Citadel graph nodes to JSON Canvas `file`, `text`, `link`, and `group`
  nodes.
- Store Citadel-only metadata in sidecar records keyed by canvas/node/edge IDs.

P1:

- Generate canvases for GraphRAG answers: query node, answer node, evidence
  files, entity groups, relation edges, and confidence styling.
- Use edge labels/colors for relation type: `cites`, `mentions`, `supports`,
  `contradicts`, `derived-from`, and `synced-from`.

## Source Sync

Start with explicit ingest and one-way managed sync. Defer full bidirectional
sync until the revision/conflict model is proven.

P0:

- Add a first-class `obsidian_vault` source type.
- Register a vault from the plugin.
- Let users push selected notes, current note, or an explicitly selected folder.
- Store path, normalized path, content hash, current revision, source ID, and
  actor ID.
- Do not silently ingest an entire vault.
- Do not overwrite local Obsidian notes from Citadel.
- Do not hard-delete remote documents in the MVP.

P1:

- Add one-way Citadel-to-Obsidian pull into a managed folder such as
  `Citadel/Inbox` or `Citadel/Team`.
- Add sync manifests, cursors, tombstones, and conflict records.
- Add optional server-side sync using `obsidian-headless` for teams that already
  use Obsidian Sync.

P2:

- Add bidirectional sync with conflict UI.
- Support attachments, embeds, `.canvas`, and rename detection.
- Add OAuth/OIDC or device authorization for team onboarding.

## Obsidian Plugin

The companion plugin should be a thin team client, not a hidden full-sync
engine.

P0 plugin capabilities:

- Connect to Citadel with `Authorization: Bearer <ctdl_...>`.
- Store tokens in Obsidian `SecretStorage`, not plain plugin settings.
- Call `/api/session` on load and show effective role/capabilities.
- Search Citadel from a side pane.
- Ingest selected text, current note, or an explicitly selected folder.
- Add a ribbon command and command-palette actions.
- Use Obsidian `Vault` APIs for file access and `requestUrl` for HTTP.

Plugin outline:

```text
manifest.json
versions.json
package.json
esbuild.config.mjs
styles.css
src/main.ts
src/settings.ts
src/citadelClient.ts
src/auth.ts
src/commands.ts
src/ui/CitadelView.ts
src/ui/SearchModal.ts
src/ui/ConflictModal.ts
src/sync/syncEngine.ts
src/sync/vaultScanner.ts
src/sync/localIndex.ts
src/sync/frontmatter.ts
src/types.ts
```

Manifest constraints:

- `id` should be `citadel-archive` or `citadel-team-kb`.
- The plugin ID should not contain `obsidian`.
- `isDesktopOnly` can be `false` if the plugin avoids Node/Electron APIs.
- `minAppVersion` should be chosen after confirming required APIs such as
  `SecretStorage`.

## Citadel API Additions

Add these endpoints before the plugin becomes more than a prototype:

- `POST /api/obsidian/vaults`
  Register a vault and return `vault_id`.
- `GET /api/obsidian/manifest?vault_id=&cursor=`
  Return known documents, hashes, revisions, and tombstones.
- `POST /api/obsidian/sync/push`
  Push a batch of selected notes or folder-scoped changes.
- `GET /api/obsidian/sync/pull?vault_id=&cursor=`
  Pull changes for a managed Citadel folder.
- `POST /api/obsidian/conflicts/{id}/resolve`
  Resolve local, remote, save-both, or manually merged conflicts.
- `GET /api/sources?type=obsidian_vault`
  Show vault sync status in the web UI and MCP.
- `GET /api/documents/{id}`
  Fetch source-aware document details and previews.

Data model additions:

```text
Source(type=obsidian_vault, team_id, owner_actor_id)
SourceDocument(source_id, path, normalized_path, current_rev, content_hash)
SourceRevision(document_id, rev, base_rev, actor_id, origin, body_hash, created_at)
SyncCursor(actor_id, vault_id, cursor, updated_at)
SyncConflict(document_id, local_rev, remote_rev, base_rev, status)
```

## Access Model

Use the existing Citadel roles as the P0 plugin boundary:

- Reader: search, read mesh/source status, view results.
- Writer: reader plus explicit ingest/sync push.
- Admin: token creation, source registration, sync policy, and conflict
  defaults.

P0 token model:

- Admin creates a per-user `ctdl_...` token.
- Plugin stores the token through Obsidian `SecretStorage`.
- Every request uses bearer auth.
- Plugin calls `/api/session` to disable actions the current actor cannot use.

P1 token model:

- Add scoped tokens with `team_id`, `dataset`, `vault_id`, expiry, and scopes.
- Initial scopes: `kb:search`, `kb:ingest`, `obsidian:sync:push`,
  `obsidian:sync:pull`, `sources:read`.
- Add rotation, revocation, and audit filters.

## Sync Rules

- Content hash plus Citadel revision is authoritative. File mtime is not.
- Every plugin push must include `base_rev` when updating an existing document.
- Server returns `409 Conflict` when the client base revision diverges.
- Avoid loops with `origin`, `actor_id`, `vault_id`, and `rev` metadata.
- Use namespaced frontmatter such as `citadel_id`, `citadel_rev`, and
  `citadel_source`.
- Update frontmatter through Obsidian's frontmatter APIs, not ad hoc YAML edits.
- MVP sync scope must be explicit folders or tags.
- Attachments, embedded files, canvas files, and hidden folders are outside P0.

## Security Rules

- Require HTTPS except for `localhost`.
- Do not add telemetry.
- Redact note content from audit logs.
- Audit actor, path hash, dataset, success/failure, and request ID.
- Treat Citadel search results as untrusted Markdown; insert sanitized text only.
- Keep plugin dependencies minimal.
- Document account requirement, network use, and data sent to Citadel in the
  plugin README.

## Implementation Order

1. Finish the Obsidian-like web shell already started in `kb/static`.
2. Add `obsidian_vault` as a source type and source status row.
3. Add document/revision/hash/conflict primitives.
4. Add `/api/obsidian/*` endpoints with tests.
5. Scaffold `plugins/obsidian-citadel/` from the official sample-plugin shape.
6. Implement plugin auth, `/api/session`, search pane, and explicit note ingest.
7. Add managed one-way pull into `Citadel/Inbox`.
8. Add conflict UI and only then consider bidirectional sync.
