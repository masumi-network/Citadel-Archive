from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb.access import AccessStore, seat_dataset
from kb.config import CitadelConfig
from kb.models import IngestResult
from kb.promotion import PromotionEngine, _coerce_classification
import kb.promotion as promotion

SEAT = seat_dataset("alice")
CENTRAL = "masumi-network"  # CitadelConfig.github_sync_dataset default

# A blocking-severity AWS access key (critical) for the secret-gate test.
# Assembled at runtime so no literal key is committed (GitHub push protection
# scans literals); the joined string still trips the scanner at test time.
SECRET_TEXT = "deploy creds " + "AKIA" + "ABCDEFGHIJKLMNOP" + " rotate me"


class FakeCitadel:
    def __init__(self, config: CitadelConfig, nodes: list[str]) -> None:
        self.config = config
        self._nodes = nodes

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        # Same nodes for every seed query; the engine dedupes by text.
        return [{"text": node} for node in self._nodes]


class FakeLearning:
    """Records every learn() call so tests can assert on the write targets."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def learn(self, data: str, **kwargs: Any) -> IngestResult:
        self.calls.append({"data": data, "dataset": kwargs.get("dataset"), "tier": kwargs.get("tier"), "tags": kwargs.get("tags")})
        return IngestResult(True, "accepted", kwargs.get("dataset") or CENTRAL, tuple(kwargs.get("tags") or ()))

    @property
    def central_writes(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["dataset"] == CENTRAL]


def _config(**overrides: Any) -> CitadelConfig:
    base: dict[str, Any] = {"promotion_enabled": True}
    base.update(overrides)
    return CitadelConfig(**base)


def _engine(tmp_path: Path, nodes: list[str], config: CitadelConfig | None = None) -> tuple[PromotionEngine, FakeLearning, AccessStore]:
    config = config or _config()
    learning = FakeLearning()
    store = AccessStore(str(tmp_path / "access.json"))
    engine = PromotionEngine(FakeCitadel(config, nodes), learning, store, config)
    return engine, learning, store


def _stub_llm(monkeypatch: pytest.MonkeyPatch, *, relevant: bool = True, sensitive: bool = False, score: float = 0.9, fail: bool = False) -> None:
    def fake_chat(*args: Any, **kwargs: Any) -> str | None:
        if fail:
            return None
        return json.dumps({"relevant": relevant, "sensitive": sensitive, "score": score, "reason": "stubbed"})

    monkeypatch.setattr(promotion, "openrouter_chat", fake_chat)


def test_coerce_classification_rejects_malformed() -> None:
    assert _coerce_classification({"relevant": True, "sensitive": False, "score": 0.8, "reason": "ok"}) is not None
    assert _coerce_classification({"relevant": "yes", "sensitive": False, "score": 0.8, "reason": "ok"}) is None
    assert _coerce_classification({"relevant": True, "sensitive": False, "score": 2, "reason": "ok"}) is None
    assert _coerce_classification({"relevant": True, "sensitive": False, "score": 0.8}) is None
    assert _coerce_classification("not a dict") is None


async def test_dry_run_proposes_but_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, store = _engine(tmp_path, ["a useful org note about the product roadmap"])
    _stub_llm(monkeypatch, relevant=True, sensitive=False, score=0.9)

    result = await engine.run(SEAT, dry_run=True)

    assert result["dry_run"] is True
    assert result["proposed"] == 1
    assert result["promoted"] == 0
    assert any(p["decision"] == "promote" for p in result["proposals"])
    # The core safety invariant: a dry run performs NO writes at all.
    assert learning.calls == []
    assert store.recent_audit_events(action="promotion.promote") == []


async def test_relevant_clean_item_is_promoted_to_central_with_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, store = _engine(tmp_path, ["a useful org note about the product roadmap"])
    _stub_llm(monkeypatch, relevant=True, sensitive=False, score=0.9)

    result = await engine.run(SEAT, dry_run=False)

    assert result["promoted"] == 1
    # Promotion routed through the org-ready dual-write -> a real Central write.
    assert len(learning.central_writes) == 1
    assert "org-ready" in learning.central_writes[0]["tags"]
    promote_events = store.recent_audit_events(action="promotion.promote")
    assert len(promote_events) == 1
    assert promote_events[0]["success"] is True
    assert promote_events[0]["dataset"] == CENTRAL
    assert promote_events[0]["detail"]["seat"] == SEAT


async def test_sensitive_item_is_not_promoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, store = _engine(tmp_path, ["my personal salary and home address"])
    _stub_llm(monkeypatch, relevant=True, sensitive=True, score=0.95)

    result = await engine.run(SEAT, dry_run=False)

    assert result["promoted"] == 0
    assert learning.central_writes == []
    assert result["proposals"][0]["decision"] == "skip"
    assert result["proposals"][0]["reason"] == "sensitive"


async def test_secret_bearing_item_is_not_promoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, _store = _engine(tmp_path, [SECRET_TEXT])
    # Even if the classifier would say "promote", the secret gate must win.
    _stub_llm(monkeypatch, relevant=True, sensitive=False, score=0.99)

    result = await engine.run(SEAT, dry_run=False)

    assert result["promoted"] == 0
    assert learning.calls == []
    assert result["proposals"][0]["decision"] == "skip"
    assert result["proposals"][0]["reason"] == "secret_content"
    assert result["proposals"][0]["secret_blocked"] is True


async def test_llm_failure_falls_back_to_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, _store = _engine(tmp_path, ["a useful org note about the product roadmap"])
    _stub_llm(monkeypatch, fail=True)

    result = await engine.run(SEAT, dry_run=False)

    assert result["promoted"] == 0
    assert learning.calls == []
    assert result["proposals"][0]["decision"] == "skip"
    assert result["proposals"][0]["reason"] == "llm_unavailable"


async def test_below_threshold_is_not_promoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, _store = _engine(tmp_path, ["a marginal note"])
    _stub_llm(monkeypatch, relevant=True, sensitive=False, score=0.5)

    result = await engine.run(SEAT, dry_run=False)

    assert result["promoted"] == 0
    assert learning.calls == []
    assert result["proposals"][0]["reason"] == "below_threshold"


async def test_disabled_returns_status_and_does_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, learning, _store = _engine(tmp_path, ["anything"], config=_config(promotion_enabled=False))
    _stub_llm(monkeypatch, relevant=True, sensitive=False, score=0.9)

    result = await engine.run(SEAT, dry_run=False)

    assert result["enabled"] is False
    assert result["reason"] == "disabled"
    assert learning.calls == []


async def test_non_seat_dataset_rejected(tmp_path: Path) -> None:
    engine, _learning, _store = _engine(tmp_path, ["anything"])
    with pytest.raises(ValueError):
        await engine.run(CENTRAL, dry_run=True)
