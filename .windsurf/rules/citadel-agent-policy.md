---
description: Citadel agent policy — search before coding, traces are reference-only
trigger: always_on
---

# Citadel — agent policy
- At task start: run `citadel_search` before coding (Central + your Node + Shared Session Traces).
- Trace hits carry `_citadel.trust: reference-only` — verify before acting; Central stays org-authoritative.
- Share dead-end routes with `citadel_share_session` only after explicit user approval.
