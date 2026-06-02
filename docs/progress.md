# Citadel Progress

Last updated: 2026-06-02.

## 2026-06-02

- Split repositories for production topology:
  - [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) is public
    (app, MCP, hosted agent skills).
  - [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror) is
    private (Phase 1 Vault Backup Mirror target).
- Documented mirror policy in `docs/vault-backup-mirror.md` and reserved
  `CITADEL_BACKUP_MIRROR_*` configuration for the export job.
- Published public/private boundary: `docs/public-and-private.md`, `SECURITY.md`,
  hosted `/skills/boundary`, and scrubbed personal paths from MCP templates.

## 2026-05-29

- Checked the Organization Vault plan against the local implementation state.
- Started the next dashboard build slice:
  - added Knowledge, Agents, Audit, and Settings workspace pages
  - added reader default routing to Search when no page hash is present
  - wired Knowledge to source, index, digest, and runtime event state
  - wired Agents to service-account access tokens and MCP setup snippets
  - wired Audit to access audit events and runtime vault events
  - wired Settings to readiness and learning-agent status
- Verified static JavaScript syntax with `node --check kb/static/app.js`.
- Verified backend and API behavior with `uv run pytest`.
- Improved dashboard UX:
  - reduced duplicated navigation chrome to a compact workspace ribbon
  - made mobile pages content-first by hiding the sidebar
  - rewrote the dashboard header around current vault state and primary actions
  - added direct dashboard actions for search, source sync, note creation, access,
    source review, and agent management
  - browser-checked desktop and mobile dashboard rendering

## 2026-05-28

- Captured the shareable Organization Vault product plan in
  `docs/organization-vault-plan.md` and started the canonical domain glossary in
  `CONTEXT.md`.
- Resolved Phase 1 access, Agent Messenger, source retention, repository daily
  update, knowledge conflict, and Vault Backup Mirror language across docs.
- Recorded the first architecture-deepening candidates in
  `docs/architecture-deepening-opportunities.md`.
- Rethemed the Citadel web UI toward an Obsidian-style shared vault with a left
  ribbon, vault navigation, linked panes, and darker Obsidian-compatible visual
  tokens.
- Researched the official `obsidianmd` GitHub organization and documented the
  sync/plugin integration path in `docs/obsidian-integration-plan.md`.
- Added the Obsidian vault sync API, source status endpoint, revision/conflict
  store, UI source panel, and private beta plugin scaffold.
- Verified the web UI with browser render checks and backend tests with
  `uv run pytest`.

## 2026-05-26

- Replaced the sensitive 2D knowledge mesh force simulation with a deterministic
  Three.js 3D scene.
- Added restrained orbit and zoom controls, fixed camera bounds, stable node
  placement, and WebGL labels for the mesh.
- Vendored the Three.js browser modules under `kb/static/vendor/` so the hosted
  UI does not depend on a runtime CDN.
- Verified backend tests with `uv run pytest` and checked the 3D canvas with
  Playwright on desktop and mobile viewports.
