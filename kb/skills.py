from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Short public paths → bundled agent skills (no auth required).
SKILL_FILES: dict[str, Path] = {
    "connect": REPO_ROOT
    / "plugins/citadel-archive-mcp/skills/citadel-mcp-connector/SKILL.md",
    "vault": REPO_ROOT / "plugins/citadel-archive-mcp/skills/citadel-vault/SKILL.md",
    "boundary": REPO_ROOT
    / "plugins/citadel-archive-mcp/skills/citadel-data-boundary/SKILL.md",
}

SKILL_ALIASES: dict[str, str] = {
    "mcp": "connect",
    "mcp-connector": "connect",
    "citadel-mcp-connector": "connect",
    "citadel-vault": "vault",
    "policy": "boundary",
    "privacy": "boundary",
    "public-private": "boundary",
    "citadel-data-boundary": "boundary",
}


def resolve_skill_slug(slug: str) -> str | None:
    normalized = slug.strip().lower().removesuffix(".md")
    if normalized in SKILL_FILES:
        return normalized
    return SKILL_ALIASES.get(normalized)


def skill_path(slug: str) -> Path | None:
    resolved = resolve_skill_slug(slug)
    if resolved is None:
        return None
    path = SKILL_FILES[resolved]
    return path if path.is_file() else None


def skill_catalog() -> list[dict[str, object]]:
    """Metadata for the public /skills index (canonical slugs only)."""
    aliases_by_slug: dict[str, list[str]] = {slug: [] for slug in SKILL_FILES}
    for alias, target in SKILL_ALIASES.items():
        if target in aliases_by_slug:
            aliases_by_slug[target].append(alias)
    rows: list[dict[str, object]] = []
    for slug in sorted(SKILL_FILES):
        rows.append(
            {
                "slug": slug,
                "description": _SKILL_DESCRIPTIONS.get(slug, ""),
                "aliases": sorted(aliases_by_slug[slug]),
            }
        )
    return rows


_SKILL_DESCRIPTIONS: dict[str, str] = {
    "connect": "Set up Citadel MCP in Claude Code, Codex, Cursor, or any MCP agent.",
    "vault": "Search, ingest, and use the Organization Vault after MCP is connected.",
    "boundary": "Public vs private data boundaries for Citadel code, vault, and tokens.",
}
