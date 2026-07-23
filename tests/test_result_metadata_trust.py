"""Regression: trust_tier/doc_type must see in-progress _citadel metadata."""

from __future__ import annotations

from kb.access import SESSION_TRACES_DATASET
from kb.server import with_result_metadata


def test_with_result_metadata_marks_session_traces() -> None:
    out = with_result_metadata(
        {
            "id": "trace-1",
            "title": "Dead-end route",
            "text": "Nested HTTP to /api/session deadlocked tools/list",
        },
        0,
        SESSION_TRACES_DATASET,
    )
    envelope = out["_citadel"]
    assert envelope["dataset"] == SESSION_TRACES_DATASET
    assert envelope["trust"] == "reference-only"
    assert envelope["doc_type"] == "session-trace"
    assert envelope["trust_tier"] == "reference-only"
