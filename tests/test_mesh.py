from __future__ import annotations

from kb.config import CitadelConfig
from kb.mesh import MeshState
from kb.models import FeedbackResult, IngestResult

CONFIG = CitadelConfig(tenant_id="test", default_dataset="notes")


async def test_record_ingest_adds_document_node_and_event() -> None:
    mesh = MeshState()
    result = IngestResult(True, "accepted", "notes", ("ops",))

    await mesh.record_ingest(CONFIG, result, data="Runbook: rotate keys", dataset="notes", tags=["ops"])
    snapshot = await mesh.snapshot(CONFIG)

    assert snapshot["stats"]["documents"] == 1
    document_nodes = [node for node in snapshot["nodes"] if node["type"] == "document"]
    assert document_nodes[0]["label"] == "Runbook: rotate keys"
    assert snapshot["events"][0]["type"] == "ingest"
    assert snapshot["events"][0]["details"]["dataset"] == "notes"


async def test_rejected_ingest_records_reject_event_without_document() -> None:
    mesh = MeshState()
    result = IngestResult(False, "too_short", "notes", ())

    await mesh.record_ingest(CONFIG, result, data="x", dataset="notes", tags=[])
    snapshot = await mesh.snapshot(CONFIG)

    assert snapshot["stats"]["documents"] == 0
    assert snapshot["events"][0]["type"] == "reject"
    assert snapshot["events"][0]["details"]["reason"] == "too_short"


async def test_revision_counter_increments_per_event() -> None:
    mesh = MeshState()

    await mesh.record_search(CONFIG, query="alpha", dataset="notes", result_count=1)
    await mesh.record_feedback(
        CONFIG,
        qa_id="qa-1",
        dataset="notes",
        result=FeedbackResult(recorded=True, improved=False),
    )
    await mesh.record_error(CONFIG, operation="search", error="boom")
    snapshot = await mesh.snapshot(CONFIG)

    assert snapshot["revision"] == 3
    assert snapshot["stats"]["searches"] == 1
    assert snapshot["stats"]["feedback"] == 1
    assert snapshot["stats"]["errors"] == 1
    assert [event["id"] for event in snapshot["events"]] == [3, 2, 1]


async def test_events_deque_is_bounded_at_160() -> None:
    mesh = MeshState()

    for index in range(165):
        await mesh.record_error(CONFIG, operation="op", error=f"failure {index}")
    snapshot = await mesh.snapshot(CONFIG)

    assert len(snapshot["events"]) == 160
    assert snapshot["revision"] == 165
    assert snapshot["stats"]["errors"] == 165
    # Newest first; the oldest five events fell off the bounded deque.
    assert snapshot["events"][0]["details"]["error"] == "failure 164"
    assert snapshot["events"][-1]["details"]["error"] == "failure 5"


async def test_error_details_are_clipped_to_280_characters() -> None:
    mesh = MeshState()

    await mesh.record_error(CONFIG, operation="ingest", error="x" * 500)
    snapshot = await mesh.snapshot(CONFIG)

    assert len(snapshot["events"][0]["details"]["error"]) == 280


async def test_subscribers_receive_published_events() -> None:
    mesh = MeshState()
    queue = mesh.subscribe()

    await mesh.record_search(CONFIG, query="alpha", dataset="notes", result_count=0)
    event = queue.get_nowait()

    assert event["type"] == "search"
    mesh.unsubscribe(queue)
    assert queue not in mesh.subscribers


async def test_snapshot_contains_base_indexes() -> None:
    mesh = MeshState()

    snapshot = await mesh.snapshot(CONFIG)

    assert {index["id"] for index in snapshot["indexes"]} == {
        "graph",
        "vector",
        "feedback",
        "global",
    }
