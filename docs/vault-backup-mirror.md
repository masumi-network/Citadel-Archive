# Vault Backup Mirror

The **Vault Backup Mirror** is a private, text-first GitHub repository that holds
redundant copies of vault evidence from the live **Organization Vault** on Railway.
It is the NAS-style backup counterpart to operational storage—not a second search
index and not where agents query by default.

## Repositories

See also [public-and-private.md](public-and-private.md).

| Repository | Visibility | Role |
|---|---|---|
| [Citadel-Archive](https://github.com/masumi-network/Citadel-Archive) | Public | Application, MCP, skills, docs |
| [Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror) | Private | Durable mirror of vault evidence and history |

Live retrieval, embeddings, and the knowledge mesh stay on Railway (Postgres /
pgvector / Kuzu). The mirror is for recovery, audit, diffs, and rebuild inputs.

## What gets mirrored (Phase 1)

- Source snapshots and pointers (not full secret-bearing dumps)
- Repository daily updates
- Vault contributions (ingest summaries / normalized notes)
- Conflict resolutions
- Manifests with hashes, actors, timestamps, and source pointers

## What does not get mirrored

- Secrets, credentials, API tokens, or excluded material
- Embeddings, vector index files, or graph database files
- Large binaries by default (use object storage + manifest refs if needed later)

## Planned layout (export not implemented yet)

```text
manifests/
  latest.json                 # pointer to last successful export
snapshots/
  YYYY-MM-DD/
    manifest.json
    sources/
    contributions/
    conflicts/
```

Commits should be small, reviewable, and diff-friendly (Markdown, JSON, JSONL).

## Current status

Verified on 2026-06-02:

- Repository exists at
  [masumi-network/Vault-Backup-Mirror](https://github.com/masumi-network/Vault-Backup-Mirror).
- Visibility: private.
- Default branch: `main`.
- Initial scaffold commit: `deeb1c9`.
- Top-level scaffold: `.gitignore`, `README.md`, `manifests/`, `snapshots/`.
- Automated export from Railway is not implemented yet; `CITADEL_BACKUP_MIRROR_*`
  settings reserve the integration path.

## Configuration (Citadel Archive)

Set on the Railway web service when mirror export is enabled:

```bash
CITADEL_BACKUP_MIRROR_REPO=masumi-network/Vault-Backup-Mirror
CITADEL_BACKUP_MIRROR_ENABLED=false   # true when export job ships
CITADEL_BACKUP_MIRROR_BRANCH=main
```

The GitHub token used for pushes must have `contents: write` on the private mirror
repo only. Use a dedicated fine-grained or machine token—never commit it.

## Operational notes

- Target size: ~1 GB practical ceiling; review at ~5 GB ([ADR 0001](adr/0001-github-vault-backup-mirror.md)).
- If `snapshots/` has no dated export folders, that is expected until the first
  export run.
- Agents connect via MCP to Railway; admins may browse the mirror in GitHub for audit.

## Related

- [Organization Vault plan](organization-vault-plan.md) §3.3
- [Architecture deepening §3](architecture-deepening-opportunities.md)
