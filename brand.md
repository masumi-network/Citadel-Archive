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

## Web UI palette — _deferred_

The web dashboard still uses a restrained neutral operations palette and no
custom typography. To set up a full web brand palette + typography at any time,
run `/brand-design` (or say "pick brand colors"); it will detect this deferred
state and proceed directly to setup. _Deferred at: 2026-05-20._
