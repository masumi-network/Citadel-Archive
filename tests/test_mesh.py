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
    assert snapshot["events"][0]["timeline"]["kind"] == "chunk_indexed"
    assert snapshot["stats"]["indexed_chunks"] == 1


async def test_rejected_ingest_records_reject_event_without_document() -> None:
    mesh = MeshState()
    result = IngestResult(False, "too_short", "notes", ())

    await mesh.record_ingest(CONFIG, result, data="x", dataset="notes", tags=[])
    snapshot = await mesh.snapshot(CONFIG)

    assert snapshot["stats"]["documents"] == 0
    assert snapshot["events"][0]["type"] == "reject"
    assert snapshot["events"][0]["details"]["reason"] == "too_short"


async def test_record_repo_content_sync_adds_source_and_event() -> None:
    mesh = MeshState()
    result = {
        "org": "masumi-network",
        "checked_at": "2026-06-16T00:00:00Z",
        "repos_scanned": 2,
        "files_ingested": 5,
        "files_skipped": 1,
        "improved": True,
        "repositories": [
            {"repo": "masumi-network/sokosumi-cli", "ingested": 3, "skipped": 0},
        ],
    }

    await mesh.record_repo_content_sync(CONFIG, result)
    snapshot = await mesh.snapshot(CONFIG)

    repo_nodes = [node for node in snapshot["nodes"] if node["type"] == "repository"]
    assert any(node["label"] == "sokosumi-cli" for node in repo_nodes)
    assert snapshot["events"][-1]["type"] == "repo_content_sync"
    assert snapshot["events"][-1]["details"]["files_ingested"] == 5


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


async def test_timeline_tracks_chunks_and_resume_filters() -> None:
    mesh = MeshState()

    await mesh.record_ingest(
        CONFIG,
        IngestResult(True, "accepted", "notes", ("ops",)),
        data="Runbook: rotate keys",
        dataset="notes",
        tags=["ops"],
    )
    await mesh.record_enrichment(
        CONFIG,
        dataset="notes",
        chunks=3,
        used_llm=False,
        reason="fallback",
    )
    await mesh.record_search(CONFIG, query="rotate", dataset="notes", result_count=2)

    resumed = await mesh.timeline(after_id=1, limit=1)
    chunk_events = await mesh.timeline(kind="chunk_indexed", limit=5)

    assert resumed["latest_event_id"] == 3
    assert resumed["truncated"] is True
    assert [event["id"] for event in resumed["events"]] == [3]
    assert [event["id"] for event in chunk_events["events"]] == [2, 1]
    assert chunk_events["stats"]["indexed_chunks"] == 4
    assert chunk_events["stats"]["last_indexed_at"] == chunk_events["events"][0]["created_at"]
