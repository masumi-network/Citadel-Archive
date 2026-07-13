from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from kb.cognee_client import CogneePublicClient


COGNEE_ENV_KEYS = (
    "DB_PROVIDER",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USERNAME",
    "DB_PASSWORD",
    "VECTOR_DB_HOST",
    "VECTOR_DB_PORT",
    "VECTOR_DB_NAME",
    "VECTOR_DB_USERNAME",
    "VECTOR_DB_PASSWORD",
    "GRAPH_DATABASE_HOST",
    "GRAPH_DATABASE_PORT",
    "GRAPH_DATABASE_NAME",
    "GRAPH_DATABASE_USERNAME",
    "GRAPH_DATABASE_PASSWORD",
)


@pytest.fixture(autouse=True)
def clean_derived_cognee_env(monkeypatch: Any) -> None:
    for key in COGNEE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_cognee_public_client_runs_startup_migrations_once(monkeypatch: Any) -> None:
    calls: list[str] = []

    async def run_startup_migrations() -> None:
        calls.append("migrate")

    async def add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ok": True}]

    monkeypatch.setenv("CITADEL_SUPPRESS_INLINE_COGNIFY", "true")  # add-only, no bg task
    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            run_startup_migrations=run_startup_migrations,
            add=add,
            recall=recall,
        ),
    )
    client = CogneePublicClient()

    await client.remember("note", dataset_name="notes")
    await client.recall("note", dataset="notes")

    assert calls == ["migrate"]


@pytest.mark.asyncio
async def test_cognee_public_client_creates_database_and_retries_migrations(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    async def run_startup_migrations() -> None:
        calls.append("migrate")
        if calls == ["migrate"]:
            raise RuntimeError("missing enum")

    async def add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setenv("CITADEL_SUPPRESS_INLINE_COGNIFY", "true")  # add-only, no bg task
    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            run_startup_migrations=run_startup_migrations,
            add=add,
        ),
    )
    client = CogneePublicClient()

    async def create_database() -> None:
        calls.append("create")

    monkeypatch.setattr(client, "_create_cognee_database", create_database)

    await client.remember("note", dataset_name="notes")

    assert calls == ["migrate", "create", "migrate"]


@pytest.mark.asyncio
async def test_cognee_public_client_does_not_pass_external_metadata_keyword(
    monkeypatch: Any,
) -> None:
    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def add(*args: Any, **kwargs: Any) -> dict[str, Any]:
        received["args"] = args
        received["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setenv("CITADEL_SUPPRESS_INLINE_COGNIFY", "true")  # add-only, no bg task
    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            run_startup_migrations=run_startup_migrations,
            add=add,
        ),
    )
    client = CogneePublicClient()

    await client.remember("note", dataset_name="notes", tags=("github", "daily-sync"))

    # metadata rides in the DataItem, never as an add() keyword (external_metadata
    # is rejected by cognee.add); only dataset_name is passed.
    assert received["kwargs"] == {"dataset_name": "notes"}


@pytest.mark.asyncio
async def test_cognify_raises_without_llm_key(monkeypatch: Any) -> None:
    """cognify must fail loud (not false-green) when no LLM key is configured."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    client = CogneePublicClient()

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        await client.cognify(datasets=["notes"])


@pytest.mark.asyncio
async def test_get_document_resolves_node_text(monkeypatch: Any) -> None:
    # #28: resolve a search-hit node id to its chunk text via the graph store.
    client = CogneePublicClient()

    async def fake_graph_data() -> tuple[list[Any], list[Any]]:
        return ([("node-1", {"text": "hello world", "title": "Greeting", "extra": 1})], [])

    monkeypatch.setattr(client, "graph_data", fake_graph_data)

    doc = await client.get_document("node-1")
    assert doc is not None
    assert doc["id"] == "node-1"
    assert doc["body"] == "hello world"
    assert doc["title"] == "Greeting"
    assert doc["source_type"] == "cognee"
    assert doc["metadata"] == {"title": "Greeting", "extra": 1}  # text key excluded

    assert await client.get_document("missing") is None


@pytest.mark.asyncio
async def test_get_document_returns_none_for_textless_node(monkeypatch: Any) -> None:
    client = CogneePublicClient()

    async def fake_graph_data() -> tuple[list[Any], list[Any]]:
        return ([("node-2", {"title": "no body here"})], [])

    monkeypatch.setattr(client, "graph_data", fake_graph_data)
    assert await client.get_document("node-2") is None


@pytest.mark.asyncio
async def test_get_document_assembles_document_from_chunks(monkeypatch: Any) -> None:
    # Document nodes carry no text — body is stitched from linked DocumentChunk
    # neighbors ordered by chunk_index (not edge order); textless entity
    # neighbors are skipped and edge direction doesn't matter.
    client = CogneePublicClient()

    doc_props = {"name": "text_abc123", "type": "TextDocument"}

    async def fake_graph_data() -> tuple[list[Any], list[Any]]:
        nodes = [
            ("doc-1", doc_props),
            ("chunk-b", {"text": "part two", "chunk_index": 1}),
            ("chunk-a", {"text": "part one", "chunk_index": 0}),
            ("ent-1", {"name": "Entity"}),
        ]
        edges = [
            ("chunk-b", "doc-1", "is_part_of", {}),
            ("doc-1", "ent-1", "mentions", {}),
            ("chunk-a", "doc-1", "is_part_of", {}),
        ]
        return (nodes, edges)

    monkeypatch.setattr(client, "graph_data", fake_graph_data)

    doc = await client.get_document("doc-1")
    assert doc is not None
    assert doc["body"] == "part one\n\npart two"  # chunk_index wins over edge order
    assert doc["title"] == "text_abc123"
    assert doc["source_type"] == "cognee"
    assert doc["chunk_count"] == 2
    assert doc["metadata"] == doc_props


@pytest.mark.asyncio
async def test_get_document_returns_none_for_textless_entity_near_chunks(
    monkeypatch: Any,
) -> None:
    # Entity nodes (name/description only, no text) sit right next to
    # text-bearing DocumentChunk nodes via contains/mentions edges. Chunk
    # assembly must only follow is_part_of edges, or selecting an entity
    # fabricates a "document" stitched from every chunk that mentions it
    # (regressing the textless-node -> None / HTTP 404 contract).
    client = CogneePublicClient()

    async def fake_graph_data() -> tuple[list[Any], list[Any]]:
        nodes = [
            ("ent-1", {"name": "Kuzu", "description": "graph db", "is_a": "tool"}),
            ("chunk-a", {"text": "doc A part one", "chunk_index": 0}),
            ("chunk-b", {"text": "doc B part one", "chunk_index": 0}),
        ]
        edges = [
            ("chunk-a", "ent-1", "contains", {}),
            ("chunk-b", "ent-1", "contains", {}),
        ]
        return (nodes, edges)

    monkeypatch.setattr(client, "graph_data", fake_graph_data)
    assert await client.get_document("ent-1") is None


@pytest.mark.asyncio
async def test_get_document_returns_none_for_document_with_textless_neighbors(
    monkeypatch: Any,
) -> None:
    # A document node whose only neighbors carry no text resolves to None,
    # matching the existing textless-node behavior.
    client = CogneePublicClient()

    async def fake_graph_data() -> tuple[list[Any], list[Any]]:
        nodes = [("doc-1", {"name": "text_abc123"}), ("ent-1", {"name": "Entity"})]
        return (nodes, [("doc-1", "ent-1", "mentions", {})])

    monkeypatch.setattr(client, "graph_data", fake_graph_data)
    assert await client.get_document("doc-1") is None


@pytest.mark.asyncio
async def test_improve_raises_without_llm_key(monkeypatch: Any) -> None:
    """improve must fail loud like cognify — cognee swallows the keyless error (#41)."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    client = CogneePublicClient()

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        await client.improve(dataset="notes")


@pytest.mark.asyncio
async def test_delete_graph_nodes_clears_graph_and_vector(monkeypatch: Any) -> None:
    # #15: delete_graph_nodes removes ids from BOTH the graph and the chunk vector
    # collection (search reads the vector store, so graph-only deletion isn't enough).
    from uuid import UUID

    captured: dict[str, Any] = {}

    class FakeGraphEngine:
        async def delete_nodes(self, node_ids: list[str]) -> None:
            captured["graph"] = list(node_ids)

    class FakeVectorEngine:
        async def delete_data_points(self, collection: str, ids: list[UUID]) -> None:
            captured["collection"] = collection
            captured["vector"] = list(ids)

    async def get_graph_engine() -> FakeGraphEngine:
        return FakeGraphEngine()

    def get_vector_engine() -> FakeVectorEngine:
        return FakeVectorEngine()

    async def run_startup_migrations() -> None:
        return None

    monkeypatch.setitem(sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations))
    monkeypatch.setitem(sys.modules, "cognee.infrastructure", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "cognee.infrastructure.databases", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.infrastructure.databases.graph",
        SimpleNamespace(get_graph_engine=get_graph_engine),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.infrastructure.databases.vector",
        SimpleNamespace(get_vector_engine=get_vector_engine),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    async def _ready(_cognee: Any) -> None:
        return None

    monkeypatch.setattr(client, "_ensure_cognee_ready", _ready)

    uuid_a = "9dbe579d-eccb-51b6-9bba-13982cbaf69f"
    uuid_b = "43fdc0c1-b319-51d3-8fc2-2b670c2acc54"
    assert await client.delete_graph_nodes([uuid_a, uuid_b]) == 2
    assert captured["graph"] == [uuid_a, uuid_b]
    assert captured["collection"] == "DocumentChunk_text"
    assert captured["vector"] == [UUID(uuid_a), UUID(uuid_b)]
    assert await client.delete_graph_nodes([]) == 0  # no-op


@pytest.mark.asyncio
async def test_node_dataset_map_builds_data_id_to_dataset_names(monkeypatch: Any) -> None:
    # Dataset membership lives only in the relational store (datasets ↔
    # dataset_data ↔ data); a Data item can belong to multiple datasets (mirrors).
    from uuid import uuid4

    doc_id = uuid4()
    mirrored_id = uuid4()
    dataset_a = SimpleNamespace(id=uuid4(), name="seat:alice")
    dataset_b = SimpleNamespace(id=uuid4(), name="seat:bob")

    async def run_startup_migrations() -> None:
        return None

    async def get_default_user() -> Any:
        return SimpleNamespace(id="user-1")

    async def get_datasets(user_id: Any) -> list[Any]:
        assert user_id == "user-1"
        return [dataset_a, dataset_b]

    async def get_dataset_data(dataset_id: Any) -> list[Any]:
        if dataset_id == dataset_a.id:
            return [SimpleNamespace(id=doc_id), SimpleNamespace(id=mirrored_id)]
        return [SimpleNamespace(id=mirrored_id)]

    monkeypatch.setitem(
        sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations)
    )
    for parent in ("cognee.modules", "cognee.modules.data", "cognee.modules.users"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.data.methods",
        SimpleNamespace(get_datasets=get_datasets, get_dataset_data=get_dataset_data),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.users.methods",
        SimpleNamespace(get_default_user=get_default_user),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    mapping = await client.node_dataset_map()

    assert mapping == {
        str(doc_id): ["seat:alice"],
        str(mirrored_id): ["seat:alice", "seat:bob"],
    }


@pytest.mark.asyncio
async def test_node_dataset_map_degrades_to_empty_on_failure(monkeypatch: Any) -> None:
    # Attribution is best-effort: relational failures must never break the
    # graph endpoint — the map degrades to {}.
    async def run_startup_migrations() -> None:
        return None

    async def get_default_user() -> Any:
        raise RuntimeError("relational store offline")

    async def get_datasets(user_id: Any) -> list[Any]:
        return []

    async def get_dataset_data(dataset_id: Any) -> list[Any]:
        return []

    monkeypatch.setitem(
        sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations)
    )
    for parent in ("cognee.modules", "cognee.modules.data", "cognee.modules.users"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.data.methods",
        SimpleNamespace(get_datasets=get_datasets, get_dataset_data=get_dataset_data),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.users.methods",
        SimpleNamespace(get_default_user=get_default_user),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    assert await client.node_dataset_map() == {}


@pytest.mark.asyncio
async def test_node_dataset_map_returns_empty_when_no_datasets(monkeypatch: Any) -> None:
    async def run_startup_migrations() -> None:
        return None

    async def get_default_user() -> Any:
        return SimpleNamespace(id="user-1")

    async def get_datasets(user_id: Any) -> list[Any]:
        return []

    async def get_dataset_data(dataset_id: Any) -> list[Any]:
        raise AssertionError("must not be called when there are no datasets")

    monkeypatch.setitem(
        sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations)
    )
    for parent in ("cognee.modules", "cognee.modules.data", "cognee.modules.users"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.data.methods",
        SimpleNamespace(get_datasets=get_datasets, get_dataset_data=get_dataset_data),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.users.methods",
        SimpleNamespace(get_default_user=get_default_user),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    assert await client.node_dataset_map() == {}


@pytest.mark.asyncio
async def test_node_dataset_map_caches_result_across_calls(monkeypatch: Any) -> None:
    # /api/mesh/graph calls this on every poll: the relational read (2+N
    # sequential round-trips) must run once per TTL, not once per request (#50).
    from uuid import uuid4

    doc_id = uuid4()
    reads = 0

    async def run_startup_migrations() -> None:
        return None

    async def get_default_user() -> Any:
        nonlocal reads
        reads += 1
        return SimpleNamespace(id="user-1")

    async def get_datasets(user_id: Any) -> list[Any]:
        return [SimpleNamespace(id="ds-1", name="seat:alice")]

    async def get_dataset_data(dataset_id: Any) -> list[Any]:
        return [SimpleNamespace(id=doc_id)]

    monkeypatch.setitem(
        sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations)
    )
    for parent in ("cognee.modules", "cognee.modules.data", "cognee.modules.users"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.data.methods",
        SimpleNamespace(get_datasets=get_datasets, get_dataset_data=get_dataset_data),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.users.methods",
        SimpleNamespace(get_default_user=get_default_user),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    first = await client.node_dataset_map()
    second = await client.node_dataset_map()

    assert first == second == {str(doc_id): ["seat:alice"]}
    assert reads == 1


@pytest.mark.asyncio
async def test_node_dataset_map_times_out_and_caches_the_failure(
    monkeypatch: Any,
) -> None:
    # A non-erroring relational outage (TCP blackhole, saturated pool) must not
    # stall /api/mesh/graph: the read is time-bounded, degrades to {}, and the
    # failure is remembered for the TTL instead of re-blocking every poll (#50).
    import kb.cognee_client as cognee_client_module

    monkeypatch.setattr(cognee_client_module, "NODE_DATASET_MAP_TIMEOUT_SECONDS", 0.05)
    reads = 0

    async def run_startup_migrations() -> None:
        return None

    async def get_default_user() -> Any:
        nonlocal reads
        reads += 1
        await asyncio.sleep(30)  # simulated blackhole: never errors, never returns
        return SimpleNamespace(id="user-1")

    async def get_datasets(user_id: Any) -> list[Any]:
        return []

    async def get_dataset_data(dataset_id: Any) -> list[Any]:
        return []

    monkeypatch.setitem(
        sys.modules, "cognee", SimpleNamespace(run_startup_migrations=run_startup_migrations)
    )
    for parent in ("cognee.modules", "cognee.modules.data", "cognee.modules.users"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.data.methods",
        SimpleNamespace(get_datasets=get_datasets, get_dataset_data=get_dataset_data),
    )
    monkeypatch.setitem(
        sys.modules,
        "cognee.modules.users.methods",
        SimpleNamespace(get_default_user=get_default_user),
    )

    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    assert await client.node_dataset_map() == {}
    assert await client.node_dataset_map() == {}  # served from the failure cache
    assert reads == 1


@pytest.mark.asyncio
async def test_cognify_serializes_on_writer_lock(monkeypatch: Any) -> None:
    # #47: Kuzu is single-writer, so two overlapping cognify calls must serialize.
    import asyncio

    monkeypatch.setenv("LLM_API_KEY", "k")
    concurrent = 0
    max_seen = 0

    async def fake_cognify(*, datasets: Any, incremental_loading: bool) -> dict[str, Any]:
        nonlocal concurrent, max_seen
        concurrent += 1
        max_seen = max(max_seen, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1
        return {"ok": True}

    async def run_startup_migrations() -> None:
        return None

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(cognify=fake_cognify, run_startup_migrations=run_startup_migrations),
    )
    client = CogneePublicClient()
    monkeypatch.setattr(client, "_prepare_cognee_environment", lambda: None)

    async def _ready(_cognee: Any) -> None:
        return None

    monkeypatch.setattr(client, "_ensure_cognee_ready", _ready)

    await asyncio.gather(client.cognify(datasets=["a"]), client.cognify(datasets=["b"]))
    assert max_seen == 1  # the writer lock prevented concurrent graph writes


@pytest.mark.asyncio
async def test_durable_writes_bypass_session_cache(monkeypatch: Any) -> None:
    """Durable writes never route through cognee's session cache.

    Passing a session_id used to divert the write into the per-session cache,
    which stored the payload as the literal "[DataItem]" placeholder, never
    cognified it (ingest items_processed:0), and re-embedded a growing
    scaffolded blob each cycle. remember() now always sends the write to the
    permanent add+cognify path: cognee.remember is called WITHOUT a session_id,
    and the payload is DataItem-wrapped so citadel_tags metadata survives.
    """
    from dataclasses import dataclass, field

    @dataclass
    class DataItem:
        data: Any
        label: Any = None
        external_metadata: Any = field(default=None)
        data_id: Any = None

    for parent in ("cognee.tasks", "cognee.tasks.ingestion"):
        monkeypatch.setitem(sys.modules, parent, SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "cognee.tasks.ingestion.data_item",
        SimpleNamespace(DataItem=DataItem),
    )

    captured: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def add(data: Any, **kwargs: Any) -> dict[str, Any]:
        captured["data"] = data
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(run_startup_migrations=run_startup_migrations, add=add),
    )
    # Suppress the background cognify so the test is deterministic (and so a real
    # cognify isn't scheduled against the mock); the bypass assertion is on add.
    monkeypatch.setenv("CITADEL_SUPPRESS_INLINE_COGNIFY", "true")
    client = CogneePublicClient()

    # Even with a session_id supplied, the write must NOT be diverted into the
    # session cache: no session_id reaches cognee.add, and the payload is
    # DataItem-wrapped (carrying citadel_tags) for the permanent graph.
    result = await client.remember(
        "real digest",
        dataset_name="masumi-network",
        session_id="masumi-github-daily",
        tags=("github",),
    )
    assert "session_id" not in captured["kwargs"]
    assert captured["kwargs"] == {"dataset_name": "masumi-network"}
    assert isinstance(captured["data"], DataItem)
    assert captured["data"].data == "real digest"
    assert captured["data"].external_metadata == {"citadel_tags": ["github"]}
    assert result == {"added": {"ok": True}, "cognify": "suppressed"}


@pytest.mark.asyncio
async def test_remember_schedules_lock_guarded_background_cognify(monkeypatch: Any) -> None:
    # #47: outside the suppress flag, remember adds then schedules OUR background
    # cognify (lock-guarded), not cognee's fire-and-forget run_in_background.
    import asyncio

    import kb.cognee_client as cc

    monkeypatch.delenv("CITADEL_SUPPRESS_INLINE_COGNIFY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "k")
    cognified: list[Any] = []

    async def run_startup_migrations() -> None:
        return None

    async def add(data: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def cognify(*, datasets: Any, incremental_loading: bool) -> dict[str, Any]:
        cognified.append(list(datasets))
        return {"ok": True}

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(run_startup_migrations=run_startup_migrations, add=add, cognify=cognify),
    )
    client = CogneePublicClient()

    result = await client.remember("note", dataset_name="seat:sarthi", tags=())
    assert result == {"added": {"ok": True}, "background_cognify": True}
    # Drain the scheduled background cognify and confirm it ran via cognify().
    await asyncio.gather(*list(cc._BACKGROUND_COGNIFY_TASKS), return_exceptions=True)
    assert cognified == [["seat:sarthi"]]


@pytest.mark.asyncio
async def test_schedule_cognify_runs_one_cognify_over_all_datasets(monkeypatch: Any) -> None:
    # #46/#52: the coalesced cognify is ONE background task over every dataset the
    # bulk write touched (de-duplicated), not one-per-write.
    import asyncio

    import kb.cognee_client as cc

    monkeypatch.setenv("LLM_API_KEY", "k")
    cognified: list[list[str]] = []

    async def run_startup_migrations() -> None:
        return None

    async def cognify(*, datasets: Any, incremental_loading: bool) -> dict[str, Any]:
        cognified.append(list(datasets))
        return {"ok": True}

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(run_startup_migrations=run_startup_migrations, cognify=cognify),
    )
    client = CogneePublicClient()

    client.schedule_cognify(["central", "seat:a", "central"])  # duplicate central
    await asyncio.gather(*list(cc._BACKGROUND_COGNIFY_TASKS), return_exceptions=True)
    assert cognified == [["central", "seat:a"]]  # one cognify, de-duplicated

    # No datasets → no task scheduled.
    cognified.clear()
    client.schedule_cognify([])
    await asyncio.gather(*list(cc._BACKGROUND_COGNIFY_TASKS), return_exceptions=True)
    assert cognified == []


@pytest.mark.asyncio
async def test_cognee_public_client_uses_chunk_search_by_default(monkeypatch: Any) -> None:
    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        received["recall"] = {"args": args, "kwargs": kwargs}
        return []

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        received["search"] = kwargs
        return [{"ok": True}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            recall=recall,
            search=search,
        ),
    )
    client = CogneePublicClient()

    result = await client.recall("note", dataset="notes")

    assert result == [{"ok": True}]
    assert "recall" not in received
    assert received["search"]["query_type"] == "chunks"
    assert received["search"]["datasets"] == ["notes"]


@pytest.mark.asyncio
async def test_session_recall_off_by_default_and_opt_in(monkeypatch: Any) -> None:
    # #15/#52: the per-session QA cache served stale "[DataItem]" garbage, so the
    # session-scoped recall is OFF by default — search goes straight to the durable
    # chunk store. It only runs when CITADEL_COGNEE_SESSION_RECALL is set.
    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        received["recall"] = {"args": args, "kwargs": kwargs}
        return [{"source": "session"}]

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        received["search"] = kwargs
        return [{"source": "graph"}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            recall=recall,
            search=search,
        ),
    )
    client = CogneePublicClient()

    # Default OFF: the session cache is never read; the durable chunk search runs.
    monkeypatch.delenv("CITADEL_COGNEE_SESSION_RECALL", raising=False)
    result = await client.recall("note", dataset="notes", session_id="source-session")
    assert result == [{"source": "graph"}]
    assert "recall" not in received  # session QA cache never touched
    assert "search" in received

    # Opt-in: session recall runs first only when explicitly enabled.
    received.clear()
    monkeypatch.setenv("CITADEL_COGNEE_SESSION_RECALL", "true")
    result = await client.recall("note", dataset="notes", session_id="source-session")
    assert result == [{"source": "session"}]
    assert received["recall"]["kwargs"]["scope"] == "session"
    assert "search" not in received


@pytest.mark.asyncio
async def test_cognee_public_client_returns_empty_results_for_empty_store(
    monkeypatch: Any,
) -> None:
    class NoDataError(Exception):
        pass

    async def run_startup_migrations() -> None:
        return None

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        raise NoDataError("No data found in the system, please add data first.")

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            search=search,
        ),
    )
    client = CogneePublicClient()

    result = await client.recall("note", dataset="notes")

    assert result == []


@pytest.mark.asyncio
async def test_cognee_public_client_falls_back_when_session_has_no_data(
    monkeypatch: Any,
) -> None:
    class NoDataError(Exception):
        pass

    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        received["recall"] = {"args": args, "kwargs": kwargs}
        raise NoDataError("No data found in the system, please add data first.")

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        received["search"] = kwargs
        return [{"source": "chunks"}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            recall=recall,
            search=search,
        ),
    )
    client = CogneePublicClient()

    # The session-recall fallback only applies when session recall is opted in.
    monkeypatch.setenv("CITADEL_COGNEE_SESSION_RECALL", "true")
    result = await client.recall("note", dataset="notes", session_id="source-session")

    assert result == [{"source": "chunks"}]
    assert received["recall"]["kwargs"]["scope"] == "session"
    assert received["search"]["datasets"] == ["notes"]


@pytest.mark.asyncio
async def test_cognee_public_client_cognify_wraps_cognee_cognify(monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def cognify(**kwargs: Any) -> dict[str, Any]:
        received["kwargs"] = kwargs
        return {"cognified": True}

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            run_startup_migrations=run_startup_migrations,
            cognify=cognify,
        ),
    )
    client = CogneePublicClient()

    result = await client.cognify(datasets=["masumi-network"])

    assert result == {"cognified": True}
    assert received["kwargs"] == {"datasets": ["masumi-network"], "incremental_loading": True}


@pytest.mark.asyncio
async def test_recall_does_not_pass_only_context(monkeypatch: Any) -> None:
    # #50: cognee's only_context=True flips the CHUNKS result from the list-of-dicts
    # the callers rely on (result_provenance/_citadel envelope, dedup, drill-down) to
    # a single newline-joined string, and does NOT suppress the per-read history write
    # for CHUNKS. So it must never be passed on the read path — the result shape stays.
    received: dict[str, Any] = {}

    async def run_startup_migrations() -> None:
        return None

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        received["search"] = kwargs
        return [{"ok": True}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            search=search,
        ),
    )
    client = CogneePublicClient()

    result = await client.recall("note", dataset="notes")

    assert result == [{"ok": True}]  # list-of-dicts shape preserved
    assert "only_context" not in received["search"]


@pytest.mark.asyncio
async def test_search_timing_logs_only_when_enabled(monkeypatch: Any, caplog: Any) -> None:
    # #50: an opt-in, lightweight per-search wall-time line (setup/recall/total) so the
    # residual node latency can be attributed later. Off by default, INFO when enabled.
    import logging

    async def run_startup_migrations() -> None:
        return None

    async def search(**kwargs: Any) -> list[dict[str, Any]]:
        return [{"ok": True}]

    monkeypatch.setitem(
        sys.modules,
        "cognee",
        SimpleNamespace(
            SearchType=SimpleNamespace(CHUNKS="chunks"),
            run_startup_migrations=run_startup_migrations,
            search=search,
        ),
    )
    client = CogneePublicClient()

    monkeypatch.delenv("CITADEL_SEARCH_TIMING", raising=False)
    with caplog.at_level(logging.INFO, logger="kb.cognee_client"):
        await client.recall("note", dataset="notes")
    assert "search timing:" not in caplog.text  # silent by default

    caplog.clear()
    monkeypatch.setenv("CITADEL_SEARCH_TIMING", "true")
    with caplog.at_level(logging.INFO, logger="kb.cognee_client"):
        await client.recall("note", dataset="notes", top_k=7)
    assert "search timing:" in caplog.text
    assert "query_type=chunks" in caplog.text
    assert "top_k=7" in caplog.text


def test_cognee_public_client_derives_db_env_from_database_url(monkeypatch: Any) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db_user:db%23pass@db.example:6543/citadel")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "pgvector")
    for key in (
        "DB_PROVIDER",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USERNAME",
        "DB_PASSWORD",
        "VECTOR_DB_HOST",
        "VECTOR_DB_PORT",
        "VECTOR_DB_NAME",
        "VECTOR_DB_USERNAME",
        "VECTOR_DB_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    CogneePublicClient()._prepare_cognee_environment()

    assert os.environ["DB_PROVIDER"] == "postgres"
    assert os.environ["DB_HOST"] == "db.example"
    assert os.environ["DB_PORT"] == "6543"
    assert os.environ["DB_NAME"] == "citadel"
    assert os.environ["DB_USERNAME"] == "db_user"
    assert os.environ["DB_PASSWORD"] == "db#pass"
    assert os.environ["VECTOR_DB_HOST"] == "db.example"
    assert os.environ["VECTOR_DB_PORT"] == "6543"
    assert os.environ["VECTOR_DB_NAME"] == "citadel"
    assert os.environ["VECTOR_DB_USERNAME"] == "db_user"
    assert os.environ["VECTOR_DB_PASSWORD"] == "db#pass"


def test_cognee_public_client_preserves_explicit_vector_db_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("DB_HOST", "relational.example")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "railway")
    monkeypatch.setenv("DB_USERNAME", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "pgvector")
    monkeypatch.setenv("VECTOR_DB_HOST", "vector.example")

    CogneePublicClient()._prepare_cognee_environment()

    assert os.environ["VECTOR_DB_HOST"] == "vector.example"
    assert os.environ["VECTOR_DB_PORT"] == "5432"
    assert os.environ["VECTOR_DB_NAME"] == "railway"
    assert os.environ["VECTOR_DB_USERNAME"] == "postgres"
    assert os.environ["VECTOR_DB_PASSWORD"] == "secret"


def test_cognee_public_client_derives_postgres_graph_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("DB_HOST", "postgres.example")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "railway")
    monkeypatch.setenv("DB_USERNAME", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("GRAPH_DATABASE_PROVIDER", "postgres")

    CogneePublicClient()._prepare_cognee_environment()

    assert os.environ["GRAPH_DATABASE_HOST"] == "postgres.example"
    assert os.environ["GRAPH_DATABASE_PORT"] == "5432"
    assert os.environ["GRAPH_DATABASE_NAME"] == "railway"
    assert os.environ["GRAPH_DATABASE_USERNAME"] == "postgres"
    assert os.environ["GRAPH_DATABASE_PASSWORD"] == "secret"
