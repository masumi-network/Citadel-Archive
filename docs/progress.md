# Citadel Progress

Last updated: 2026-05-28.

## 2026-05-28

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
