# Brand — Citadel

Citadel's brand currently lives in the **CLI** (`citadel-archive`). The web-UI
color palette and typography remain deferred (see the note at the bottom); the
terminal is the shipped brand surface.

## The mark — castle banner

A compact crenellated fortress: battlements, walls, two windows. Shown on bare
`citadel`, and as the header of `citadel status` and `citadel onboard` on a TTY.

```
  ▙ ▟ ▙ ▟ ▙ ▟ ▙ ▟
  ███████████████   CITADEL
  ██ ▟▀▙   ▟▀▙ ██   the organization vault
  ██ █ █   █ █ ██
  ███████████████
```

- **Wordmark:** `CITADEL` (bold).
- **Tagline:** `the organization vault` (dim).
- Source of truth: [`kb/banner.py`](kb/banner.py).

## Terminal palette (ANSI)

| Element | Style |
|---|---|
| Castle walls | cyan (`\033[36m`) |
| Wordmark | bold + cyan |
| Tagline | dim |
| Status OK `●` | green |
| Status fail `○` | red |
| Verdict ("Not fully connected") | yellow |

Color is **TTY-aware**: applied only on a real terminal, and suppressed when
output is piped, under `--json`, or when `NO_COLOR` / `TERM=dumb` is set — so
headless/agent output stays clean and parseable. (`banner.supports_color`.)

## Voice

Terse, operational, honest. The CLI mirrors the system's guarantees in how it
speaks:

- **Personal-by-default** — capture lands in your private Node unless explicitly promoted.
- **Fail-silent** — hooks never block your `git push` or session close.
- **No surprises** — masked tokens, explicit exit codes, errors on stderr.

Words we use: Node, Central, seat, Approved Capture Roots, Capture Root Tags,
promotion. See [`CONTEXT.md`](CONTEXT.md) for the full domain glossary.

---

## Web UI palette — _set 2026-06-29_

The web dashboard is themed to **Masumi Network's brand** — magenta `#FA008C`
on a dark, faint-emerald-neutral base. Tokens live in `kb/static/styles.css`
`:root`; everything derives from them.

| Role | Token | Value | Rationale |
|---|---|---|---|
| Brand accent | `--primary` | `#FA008C` | Masumi's declared `theme-color` (masumi.network) |
| Accent hover/glow | `--primary-strong` | `#FF5CB0` | lighter magenta |
| Success / indexed | `--success` | `#34D399` | emerald — day-to-day "healthy/indexed" status |
| Info / search | `--info` | `#22D3EE` | cyan — nod to Citadel's CLI brand |
| Danger | `--danger` | `#FA140A` | Masumi's own red |
| Warning / pending | `--warning` | `#FBBF24` | amber |
| Surfaces | `--bg` … `--surface` | `#0B0F0E` → `#131B18` | dark, faint emerald-neutral tint |

Magenta carries brand identity (active nav, primary actions, links); emerald
reads as the "indexed / healthy" status across the timeline. The sidebar is 6
items (Overview · Search · Knowledge · Activity · Write · Admin); merged groups
expose sub-pages via a content sub-tab bar. Typography unchanged (Inter body;
monospace reserved for data — timestamps, IDs, reasons).
