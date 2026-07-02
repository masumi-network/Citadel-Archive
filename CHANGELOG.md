# Changelog

All notable changes to `citadel-archive` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/); this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`citadel token set [TOKEN]`** — set/rotate the seat token this machine uses
  without re-running onboard: verifies the token against the Node first (a
  rejected token writes **nothing**; `--skip-verify` overrides), then updates
  the shell rc in place and reminds you to `source` it.
- **`citadel update`** (alias `upgrade`) — self-update that answers pipx's
  "already seems to be installed" dead end: pipx installs run
  `pipx upgrade --pip-args=--no-cache-dir`, editable/source checkouts are left
  alone (told to `git pull`), anything else gets printed instructions.

- **Checkbox tool selection on onboard** — the coding-tools step is one
  arrow-key multi-select (↑/↓ · space · enter; numeric fallback off-TTY)
  instead of a Y/n question per tool, with the spinner while the selection is
  wired.
- **Stale-shell auth hint** — when `ingest`/`search`/`capture` get a 401/403
  and the shell rc holds a different token than the env, the error now says
  the actual fix: `source ~/.zshrc`.

### Changed

- **`citadel onboard` token flow** — an already-configured token (env or shell
  rc, detected even in a fresh shell) is shown masked with a keep-or-replace
  prompt instead of being silently reused; verification + the identity panel
  moved to the *front* of the run; a Node-rejected token offers an immediate
  re-paste loop instead of "saved anyway" after all the other prompts.
- **Capture-roots wizard defaults** — the dir you ran `citadel` from (repo
  toplevel on onboard, cwd on setup) is offered as a press-Enter default, and a
  root like `/masumi` that doesn't exist offers the home-relative dir that does
  (`~/masumi`) instead of recording a dead root.
- **Brand-color hero** — the opening art is now just the CITADEL wordmark in
  brand colors: a Masumi-magenta → cyan gradient on truecolor terminals, bold
  cyan elsewhere. The compact castle banner (the mark) stays as the in-command
  header and gains an arched gate; the home screen falls back to it on narrow
  terminals and shows the installed version.

## [0.2.1] — 2026-06-29

### Added

- **`citadel ingest` cognifies inline by default** — server-side cognify on the
  ingest path so the note is immediately searchable. `--no-cognify` skips it
  (faster; data appears in search later). Ingest prints the destination + scope
  (private seat vs shared org dataset).
- **`citadel seat token <slug>`** — mint a fresh seat-scoped token for an
  **existing** seat (re-link a lost/rotated token), distinct from `seat create`.
- **Write-scope clarity on every mint** — `seat create`, `seat token`, and
  `token create` each print the token's write-scope; `token create` warns that
  standalone tokens are **not** seat-scoped.
- **`citadel doctor` (+`--fix`)** — diagnoses setup drift (token-in-rc-not-env,
  MCP/capture Node mismatch, missing hooks/`.mcp.json`, Node-rejected token);
  `--fix` repairs the safe ones.
- **`citadel onboard` token verify + identity panel** — verifies the pasted
  token against the Node and shows seat / role / access before wiring anything.

### Changed

- **`citadel ingest` / `citadel search` are HTTP-backed by default** — they
  route to your seat via the token (no `[server]` extra needed). `--local` runs
  the in-process server stack instead (needs `[server]`). Both keep `--json`.
- **Friendlier failure modes** — narrow-terminal truncation, friendly errors for
  bare subcommand groups / typos / missing args, and clean Ctrl-C (exit 130).
- **`install.sh` upgrade path** uses `pipx install --force … --pip-args=--no-cache-dir`
  so upgrades never pull a stale cached wheel.

### Removed

- **TUI removed entirely** — there is no `citadel tui` command and the `[tui]`
  (textual) extra is dropped. Its data moved into `citadel status` as a
  "Knowledge mesh" section (documents / nodes / edges / searches).

### Server

- **`/ingest` gained an inline `cognify` flag** so the Node can cognify on the
  ingest request (backing `citadel ingest`'s default).
- **Evolve auto-sync interval shortened 6h → 1h** (`CITADEL_EVOLVE_INTERVAL_SECONDS=3600`):
  GitHub / Linear / repo sync + cognify now run hourly.

## [0.2.0] — 2026-06-29

### Added

- **Guided first-run onboarding** — bare `citadel` on an interactive TTY
  auto-enters onboarding once, then shows the home screen on later runs. Skip
  with `--no-onboard` / `CITADEL_NO_ONBOARD`; `install.sh` runs onboarding via
  `/dev/tty`.
- **Multi-tool MCP wiring** — `citadel mcp add <tool>` / `citadel mcp list`.
  Auto-writes Cursor, Codex, Gemini, and Windsurf (token stays in the shell rc
  via an env reference) and prints a paste-in snippet for Claude user-scope,
  Cline, and Zed (which store the token in plaintext). Pi has no native MCP
  (info note only).
- **Admin `seat` / `token` commands** (need `CITADEL_ADMIN_KEY`) —
  `citadel seat create "Name" slug` mints a seat + a seat-scoped writer token
  (a teammate ingests only into their `seat:slug`); `citadel seat list`;
  `citadel token create` mints standalone/service-account tokens and
  `citadel token revoke <id>` revokes by id.
- **`citadel onboard --node-url`** — target a custom Node during onboarding. The
  onboard now also installs the Claude `SessionStart` hook alongside the
  existing `SessionEnd` hook, the git pre-push hook, and `.mcp.json`.
- **`citadel --version` / `citadel version`**.

### Changed

- **Stdlib CLI UX overhaul** — shared ✓/✗ glyphs, an animated cyan spinner +
  banner reveal, and hardened argparse error/exit handling across the CLI.

## [0.1.3] — 2026-06-28

### Added

- **`citadel promotion`** — drive seat → Central promotion from the teammate CLI
  (zero-dep, like `citadel capture`): `run` triggers an on-demand promotion pass
  for your seat, `list` shows the pending approval queue, and `approve` / `reject`
  act on a queued item. All support `--json` for agents and CI.

### Server

- **Promotion Agent + Approval queue** now ship in the `[server]` extra: the
  capture → Central promotion engine (GitHub-org / Central reference checks,
  Capture Root Tag gate, secret scan + LLM on every candidate, reject dedupe,
  promotion-metadata tags), seat-scoped `POST /api/promote/run`,
  `GET /api/promotion/pending` + approve/reject, the dashboard Promotion Queue
  panel, and MCP tools `citadel_promotion_pending` / `_approve` / `_reject`.

## [0.1.2] — 2026-06-27

### Changed

- **Friendly unknown-command error** — a mistyped command (e.g. `citadel stauts`)
  now shows `✗ unknown command` + a fuzzy "did you mean? `citadel status`"
  suggestion, instead of the raw argparse usage dump.

## [0.1.1] — 2026-06-27

### Added

- **Branded home screen** — bare `citadel` now shows the large castle hero
  (figlet `CITADEL`) plus a curated, colorized command menu, replacing the raw
  argparse usage dump.
- **`install.sh` bootstrap** — `curl … | sh` entry point that detects Python
  3.10+, **asks before installing it** if missing (brew/apt/dnf/pacman), then
  installs pipx + the CLI.

## [0.1.0] — 2026-06-27

First published release. Ships the lightweight teammate CLI alongside the
self-hosted Organization Vault server.

### Added

- **`citadel onboard`** — one-command, idempotent teammate setup: writes the
  seat token to your shell rc (masked, env-only), installs the git pre-push and
  Claude Code `SessionEnd` autosync hooks, adds the Citadel MCP server to
  `.mcp.json`, and offers Approved Capture Roots. Self-contained — no vendored
  skill directory required.
- **`citadel status`** — connection + identity + local-setup health check
  (Node `/healthz`, `/api/session` whoami, search smoke, hooks/MCP/capture
  roots). `--json` for AI agents; exits non-zero when not connected.
- **`citadel tui`** — live terminal dashboard (optional `[tui]` extra).
- **`citadel setup` / `citadel capture`** — declare Approved Capture Roots
  (`~/.citadel/capture.json`) with Capture Root Tags (`personal` / `org-work`),
  and POST per-root summaries to your Node.
- **Bundled autosync hooks** (`kb.hooks.sync_push`, `kb.hooks.sync_session`) —
  stdlib-only, fail-silent, HTTPS-only, personal-by-default; installed by
  `citadel onboard` and runnable as `python -m kb.hooks.*`.
- Server **Capture Policy** baseline API + admin UI; seat **Node Write Policy**
  enforced on all HTTP + MCP write paths.

### Packaging

- Distribution renamed to **`citadel-archive`** (the installed command stays
  `citadel`). Base install is a lightweight client (`python-dotenv` only); the
  server stack is the **`[server]`** extra and the dashboard the **`[tui]`**
  extra. Importing the client never pulls the server stack (guarded by test).
- PyPI **Trusted Publishing** workflow (`.github/workflows/publish.yml`) — tag
  `v*` to build + publish, no stored tokens. See `PUBLISHING.md`.

### Security

- `post_capture` / hooks enforce HTTPS-only and refuse redirects (the seat
  Bearer token is never re-sent to another host); payloads are size-capped.
- The seat token lives in exactly one place (the shell rc); `.mcp.json`
  references it as `${CITADEL_MCP_ACCESS_TOKEN}` and it is never echoed.
- The pre-push allowlist fails **closed** on a corrupt config.

[0.2.1]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.2.1
[0.2.0]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.2.0
[0.1.3]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.1.3
[0.1.2]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.1.2
[0.1.1]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.1.1
[0.1.0]: https://github.com/masumi-network/Citadel-Archive/releases/tag/v0.1.0
