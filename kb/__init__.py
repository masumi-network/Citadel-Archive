"""Citadel package.

`Citadel` and `CitadelConfig` are exposed lazily (PEP 562) so that importing a
lightweight client module (`kb.cli`, `kb.status`, …) does not eagerly pull in the
server stack. This keeps the base `citadel-archive` install (without the
`[server]` extra) importable. `from kb import Citadel` still works on demand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kb.config import CitadelConfig
    from kb.service import Citadel

__all__ = ["Citadel", "CitadelConfig"]


def __getattr__(name: str) -> Any:
    if name == "Citadel":
        from kb.service import Citadel

        return Citadel
    if name == "CitadelConfig":
        from kb.config import CitadelConfig

        return CitadelConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
