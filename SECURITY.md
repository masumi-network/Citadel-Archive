# Security

Report sensitive issues privately to the repository maintainers (do not open a
public issue with tokens or vault exports).

## Data boundaries

Citadel separates a **public application repository** from a **private live vault**
and a **private backup mirror**. See [docs/public-and-private.md](docs/public-and-private.md).

**Never commit:** `ctdl_` tokens, `.env`, database credentials, or exported vault content.

**Rotate immediately** if a token or admin key may have been exposed.

## Agent-facing summary

https://citadel-archive-production.up.railway.app/skills/boundary
