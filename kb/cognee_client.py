from __future__ import annotations

import asyncio
import logging
import os
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Strong refs to detached background cognify tasks so the loop does not GC them
# mid-flight (and so they can be awaited/observed in tests).
_BACKGROUND_COGNIFY_TASKS: set[Any] = set()


def _suppress_inline_cognify() -> bool:
    """True when this process must ADD only and never cognify (Kuzu write).

    Set on the evolve Phase-1 subprocess so it cannot write Kuzu while the web
    process owns the single writer (#47); the web cognifies in Phase 2.
    """
    return os.getenv("CITADEL_SUPPRESS_INLINE_COGNIFY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _session_recall_enabled() -> bool:
    """Whether to read cognee's per-session QA cache before the durable store.

    The session cache is the deprecated, pre-#54 corrupt path: it stored writes as
    the literal "[DataItem]" placeholder and is no longer written to (durable
    writes go to the chunk/vector store). Reading it first only resurfaces that
    stale garbage in search/linear_search (#15/#52/#26), so it is OFF by default.
    """
    return os.getenv("CITADEL_COGNEE_SESSION_RECALL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _search_timing_enabled() -> bool:
    """Whether to log a per-search wall-time breakdown (#50, node profiling).

    Off by default; set ``CITADEL_SEARCH_TIMING=true`` to emit setup vs recall vs
    total elapsed ms per search at INFO so the ~6-9s node latency can be attributed
    on the live node later. Embedding + vector recall + cognee's per-read history
    writes all happen INSIDE the single ``cognee.search`` call, so they are lumped
    into the ``recall`` bucket — splitting them further needs cognee-internal
    instrumentation, not something the client boundary can see.
    """
    return os.getenv("CITADEL_SEARCH_TIMING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class CogneeGateway(Protocol):
    async def remember(
        self,
        data: Any,
        *,
        dataset_name: str,
        session_id: str | None = None,
        tags: tuple[str, ...] = (),
        defer_cognify: bool = False,
    ) -> Any:
        ...

    def schedule_cognify(self, datasets: list[str]) -> None:
        ...

    async def recall(
        self,
        query: str,
        *,
        dataset: str,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> list[Any]:
        ...

    async def add_feedback(
        self,
        *,
        session_id: str,
        qa_id: str,
        score: int | None,
        text: str | None,
    ) -> bool:
        ...

    async def improve(
        self,
        *,
        dataset: str,
        session_ids: list[str] | None = None,
        build_global_context_index: bool = False,
    ) -> Any:
        ...

    async def cognify(self, *, datasets: list[str], force: bool = False) -> Any:
        ...

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        ...

    async def graph_data(self) -> tuple[list[Any], list[Any]]:
        ...

    async def delete_graph_nodes(self, node_ids: list[str]) -> int:
        ...


class CogneePublicClient:
    def __init__(self) -> None:
        self._startup_migrations_done = False
        # Serializes graph writes within this process — Kuzu is a single-writer
        # embedded DB, so two overlapping cognify calls (an inline ingest cognify,
        # the evolve scheduler, /api/cognify/run) must not collide (#47). One client
        # per Citadel; the app uses a single Citadel singleton, so this is the
        # process-wide writer gate. The evolve scheduler also holds it across its
        # Phase-1 subprocess so the web never cognifies while the subprocess owns
        # the on-disk Kuzu lock.
        self.writer_lock = asyncio.Lock()

    def _copy_env_if_missing(self, target: str, *sources: str) -> None:
        if os.getenv(target):
            return
        for source in sources:
            value = os.getenv(source)
            if value:
                os.environ[target] = value
                return

    def _derive_db_env_from_database_url(self) -> None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            return
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            return

        os.environ.setdefault("DB_PROVIDER", "postgres")
        if parsed.hostname:
            os.environ.setdefault("DB_HOST", parsed.hostname)
        if parsed.port:
            os.environ.setdefault("DB_PORT", str(parsed.port))
        if parsed.path and parsed.path != "/":
            os.environ.setdefault("DB_NAME", unquote(parsed.path.lstrip("/")))
        if parsed.username:
            os.environ.setdefault("DB_USERNAME", unquote(parsed.username))
        if parsed.password:
            os.environ.setdefault("DB_PASSWORD", unquote(parsed.password))

    def _ensure_cognee_database_env(self) -> None:
        self._derive_db_env_from_database_url()
        if os.getenv("VECTOR_DB_PROVIDER", "").lower() == "pgvector":
            self._copy_env_if_missing("VECTOR_DB_HOST", "DB_HOST")
            self._copy_env_if_missing("VECTOR_DB_PORT", "DB_PORT")
            self._copy_env_if_missing("VECTOR_DB_NAME", "DB_NAME")
            self._copy_env_if_missing("VECTOR_DB_USERNAME", "DB_USERNAME")
            self._copy_env_if_missing("VECTOR_DB_PASSWORD", "DB_PASSWORD")

        if os.getenv("GRAPH_DATABASE_PROVIDER", "").lower() == "postgres":
            self._copy_env_if_missing("GRAPH_DATABASE_HOST", "DB_HOST")
            self._copy_env_if_missing("GRAPH_DATABASE_PORT", "DB_PORT")
            self._copy_env_if_missing("GRAPH_DATABASE_NAME", "DB_NAME")
            self._copy_env_if_missing("GRAPH_DATABASE_USERNAME", "DB_USERNAME")
            self._copy_env_if_missing("GRAPH_DATABASE_PASSWORD", "DB_PASSWORD")

    def _ensure_llm_api_key(self) -> None:
        if not os.getenv("LLM_API_KEY") and os.getenv("OPENROUTER_API_KEY"):
            os.environ["LLM_API_KEY"] = os.environ["OPENROUTER_API_KEY"]

    def _prepare_cognee_environment(self) -> None:
        self._ensure_llm_api_key()
        self._ensure_cognee_database_env()

    def _configured_search_type(self, cognee: Any) -> Any | None:
        raw_value = os.getenv("CITADEL_COGNEE_SEARCH_TYPE", "CHUNKS").strip().upper()
        if raw_value in {"", "AUTO", "RECALL"}:
            return None
        search_type = getattr(cognee, "SearchType", None)
        if search_type is None:
            return None
        return getattr(search_type, raw_value, getattr(search_type, "CHUNKS", None))

    def _is_no_data_error(self, exc: Exception) -> bool:
        return exc.__class__.__name__ == "NoDataError" or "No data found in the system" in str(exc)

    async def _create_cognee_database(self) -> None:
        from cognee.infrastructure.databases.relational import get_relational_engine

        db_engine = get_relational_engine()
        await db_engine.create_database()

    def _data_with_metadata(self, data: Any, metadata: dict[str, Any] | None) -> Any:
        if not metadata:
            return data
        try:
            from cognee.tasks.ingestion.data_item import DataItem
        except Exception:
            return data

        def attach(item: Any) -> Any:
            if isinstance(item, DataItem):
                merged = {**(item.external_metadata or {}), **metadata}
                return DataItem(
                    data=item.data,
                    label=item.label,
                    external_metadata=merged,
                    data_id=item.data_id,
                )
            return DataItem(data=item, external_metadata=metadata)

        if isinstance(data, list):
            return [attach(item) for item in data]
        return attach(data)

    async def _ensure_cognee_ready(self, cognee: Any) -> None:
        if self._startup_migrations_done:
            return
        run_startup_migrations = getattr(cognee, "run_startup_migrations", None)
        if run_startup_migrations is not None:
            try:
                await run_startup_migrations()
            except Exception as exc:
                logger.warning(
                    "Cognee startup migrations failed with %s; creating database and retrying",
                    exc.__class__.__name__,
                )
                await self._create_cognee_database()
                await run_startup_migrations()
        self._startup_migrations_done = True
        logger.info("Cognee startup migrations completed")

    async def remember(
        self,
        data: Any,
        *,
        dataset_name: str,
        session_id: str | None = None,
        tags: tuple[str, ...] = (),
        defer_cognify: bool = False,
    ) -> Any:
        self._prepare_cognee_environment()
        import cognee

        await self._ensure_cognee_ready(cognee)
        metadata = {"citadel_tags": list(tags)} if tags else None
        # Durable knowledge writes always go to cognee's permanent graph
        # (add+cognify), never its per-session cache. When a session_id was
        # supplied, cognee routed the write into the session cache, which (a)
        # stored an unserializable payload as the literal "[DataItem]"
        # placeholder instead of the real text, (b) never cognified it inline so
        # ingest reported items_processed:0, and (c) re-embedded a growing
        # scaffolded "Session ID:/Question:/Answer:" blob every sync cycle.
        # session_id is still accepted (callers pass it as provenance) but no
        # longer diverts the write away from the durable path.
        data = self._data_with_metadata(data, metadata)

        # Add is a fast write to the relational + vector stores; it does NOT touch
        # the Kuzu graph (cognify is the graph write). Metadata rides in the
        # DataItem (external_metadata) via _data_with_metadata, never as an add()
        # keyword — cognee rejects external_metadata as a kwarg.
        added = await cognee.add(data, dataset_name=dataset_name)

        # The cognify is a single-writer Kuzu write, so it must be coordinated (#47).
        # We previously used cognee.remember(run_in_background=True), but that
        # fire-and-forget cognify is NOT behind our writer lock and fires in EVERY
        # process — so the evolve Phase-1 subprocess and the web cognified Kuzu at
        # the same time, the hourly "Lock is held by PID N" crash.
        #
        # 1) In the Phase-1 evolve subprocess (CITADEL_SUPPRESS_INLINE_COGNIFY=true)
        #    we ADD ONLY and never write Kuzu — the web cognifies everything in
        #    Phase 2 as the sole writer.
        # 2) Otherwise we schedule our OWN background cognify that serializes on the
        #    writer lock (kept non-blocking for the caller, #56), so concurrent
        #    in-process ingests and the evolve scheduler never collide.
        if _suppress_inline_cognify():
            return {"added": added, "cognify": "suppressed"}
        if defer_cognify:
            # The caller (e.g. a bulk Linear resync) coalesces ONE cognify over every
            # dataset it touched at the end, instead of scheduling one-per-write — a
            # 200-issue resync otherwise fires 200 background cognifies that storm the
            # writer lock and starve the request (#46/#52). Add-only here; the caller
            # calls schedule_cognify() once when the batch is done.
            return {"added": added, "cognify": "deferred"}
        self._schedule_background_cognify(dataset_name)
        return {"added": added, "background_cognify": True}

    def _schedule_background_cognify(self, dataset_name: str) -> None:
        """Schedule a tracked, writer-lock-guarded cognify so ingest stays fast.

        Replaces cognee's fire-and-forget run_in_background cognify with one that
        acquires our writer lock (via cognify()) — serializing the Kuzu write and
        surfacing failures instead of swallowing them (#47/#56).
        """
        self.schedule_cognify([dataset_name])

    def schedule_cognify(self, datasets: list[str]) -> None:
        """Schedule ONE tracked, writer-lock-guarded background cognify.

        Lets a bulk writer (the Linear resync) coalesce a single cognify over every
        dataset it touched instead of one-per-write, so the request is not starved by
        a storm of per-issue cognifies (#46/#52). The single cognify still serializes
        on the writer lock (single Kuzu writer, #47) and logs — never crashes — on
        failure. No-op with no running loop (sync caller) or no datasets.
        """
        wanted = list(dict.fromkeys(datasets))  # de-dup, preserve order
        if not wanted:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop (sync caller); nothing to schedule

        async def _run() -> None:
            try:
                await self.cognify(datasets=wanted)
            except Exception:  # noqa: BLE001 - background task: log, never crash the loop
                logger.exception("background cognify for datasets %s failed", wanted)

        task = loop.create_task(_run())
        _BACKGROUND_COGNIFY_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_COGNIFY_TASKS.discard)

    async def recall(
        self,
        query: str,
        *,
        dataset: str,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> list[Any]:
        timing = _search_timing_enabled()
        t_start = perf_counter() if timing else 0.0
        self._prepare_cognee_environment()
        import cognee

        await self._ensure_cognee_ready(cognee)
        t_ready = perf_counter() if timing else 0.0
        # The per-session QA cache is the deprecated pre-#54 path and now serves only
        # stale "[DataItem]" scaffolds, so it is OFF by default — durable recall goes
        # straight to the chunk/vector store (#15/#52). Re-enable per-session reads
        # with CITADEL_COGNEE_SESSION_RECALL=true only if the cache is ever repaired.
        if session_id and hasattr(cognee, "recall") and _session_recall_enabled():
            try:
                session_results = await cognee.recall(
                    query,
                    session_id=session_id,
                    top_k=top_k,
                    scope="session",
                )
            except Exception as exc:
                if not self._is_no_data_error(exc):
                    raise
                session_results = []
            if session_results:
                return session_results

        query_type = self._configured_search_type(cognee)
        if query_type is None and hasattr(cognee, "recall"):
            try:
                results = await cognee.recall(
                    query,
                    datasets=[dataset],
                    session_id=session_id,
                    top_k=top_k,
                )
            except Exception as exc:
                if self._is_no_data_error(exc):
                    results = []
                else:
                    raise
            if timing:
                self._log_search_timing(
                    t_start, t_ready, dataset=dataset, top_k=top_k, query_type=None
                )
            return results

        # NOTE (#50): we deliberately do NOT pass cognee's only_context=True here.
        # For the CHUNKS query_type this node uses, only_context flips the return
        # value from the list-of-chunk-payload dicts the callers rely on
        # (result_provenance/_citadel envelope, dedup, drill-down) to a single
        # newline-joined string — a real shape change (verified against cognee 1.2.2
        # source). It also would NOT remove the write-per-read: for CHUNKS cognee
        # persists no session QA at all, and the per-search writes that remain
        # (log_query/log_result history) are unconditional and not gated by
        # only_context. See the timing instrument to attribute the residual latency.
        search_kwargs = {
            "query_text": query,
            "datasets": [dataset],
            "session_id": session_id,
            "top_k": top_k,
        }
        if query_type is not None:
            search_kwargs["query_type"] = query_type
        try:
            results = await cognee.search(**search_kwargs)
        except Exception as exc:
            if self._is_no_data_error(exc):
                results = []
            else:
                raise
        if timing:
            self._log_search_timing(
                t_start, t_ready, dataset=dataset, top_k=top_k, query_type=query_type
            )
        return results

    def _log_search_timing(
        self,
        t_start: float,
        t_ready: float,
        *,
        dataset: str,
        top_k: int,
        query_type: Any,
    ) -> None:
        """Emit one setup/recall/total wall-time line for a search (#50).

        ``setup`` = env prep + cognee import + startup migrations; ``recall`` = the
        single cognee search/recall call (embedding + vector recall + cognee's
        per-read history writes, not separable from here); ``total`` = both.
        """
        now = perf_counter()
        logger.info(
            "search timing: setup=%.1fms recall=%.1fms total=%.1fms dataset=%s top_k=%s query_type=%s",
            (t_ready - t_start) * 1000.0,
            (now - t_ready) * 1000.0,
            (now - t_start) * 1000.0,
            dataset,
            top_k,
            getattr(query_type, "name", query_type),
        )

    async def graph_data(self) -> tuple[list[Any], list[Any]]:
        """Return raw nodes and edges from Cognee's graph engine.

        Nodes arrive as ``(node_id, properties)`` tuples and edges as
        ``(source_id, target_id, relationship_name, properties)`` tuples, per
        ``cognee.infrastructure.databases.graph.graph_db_interface``.
        """
        self._prepare_cognee_environment()
        import cognee

        await self._ensure_cognee_ready(cognee)
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        nodes, edges = await engine.get_graph_data()
        return list(nodes), list(edges)

    async def delete_graph_nodes(self, node_ids: list[str]) -> int:
        """Delete nodes by id from BOTH the graph and the chunk vector store (#15).

        The same UUID identifies a DocumentChunk in the Kuzu graph AND in the
        DocumentChunk_text vector collection that CHUNKS search reads — so deleting
        only the graph node leaves the chunk searchable. Remove both. Serializes on
        the writer lock like cognify (single Kuzu writer, #47).
        """
        if not node_ids:
            return 0
        self._prepare_cognee_environment()
        import cognee

        await self._ensure_cognee_ready(cognee)
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        async with self.writer_lock:
            await engine.delete_nodes(node_ids)
            await self._delete_vector_points(node_ids)
        return len(node_ids)

    async def _delete_vector_points(self, node_ids: list[str]) -> None:
        """Drop the same ids from the chunk vector collection (best-effort, #15)."""
        try:
            from uuid import UUID

            from cognee.infrastructure.databases.vector import get_vector_engine

            ids: list[Any] = []
            for node_id in node_ids:
                try:
                    ids.append(UUID(str(node_id)))
                except (ValueError, TypeError, AttributeError):
                    continue
            if ids:
                await get_vector_engine().delete_data_points("DocumentChunk_text", ids)
        except Exception:  # noqa: BLE001 - vector cleanup is best-effort
            logger.warning("vector-store cleanup delete skipped/failed", exc_info=True)

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        """Resolve a search-hit node id back to its stored chunk text (#28).

        cognee search hits carry a graph node/chunk id with no backing document
        store, so ``/api/documents`` previously 404'd on every cognee hit. Look
        the node up in the graph and return its text plus the remaining
        properties; ``None`` when the node is missing or carries no text.
        """
        try:
            nodes, _ = await self.graph_data()
        except Exception as exc:  # noqa: BLE001
            if self._is_no_data_error(exc):
                return None
            raise
        for node_id, properties in nodes:
            if str(node_id) != str(document_id):
                continue
            props = dict(properties or {})
            text: str | None = None
            text_key: str | None = None
            for key in ("text", "chunk", "content", "raw_content"):
                value = props.get(key)
                if isinstance(value, str) and value.strip():
                    text, text_key = value, key
                    break
            if text is None:
                return None
            return {
                "id": str(document_id),
                "source_type": "cognee",
                "title": props.get("title") or None,
                "body": text,
                "metadata": {k: v for k, v in props.items() if k != text_key},
            }
        return None

    async def cognify(self, *, datasets: list[str], force: bool = False) -> Any:
        """Cognify already-added data in ``datasets``.

        ``cognee.cognify`` defaults to ``incremental_loading=True``, so this only
        processes uncognified data and is idempotent over a dataset. It exists to
        recover data that was added but never cognified (e.g. a prior cognify
        failed with a bad LLM config). Pass ``force=True`` to set
        ``incremental_loading=False`` and reprocess data Cognee has marked
        "already processed" (use when the graph store is empty but the dataset
        reports as processed).
        """
        self._prepare_cognee_environment()
        # Fail loud on a missing LLM key. cognee swallows LLMAPIKeyNotSetError
        # inside its pipeline and returns normally, so a keyless cognify would
        # otherwise report success while indexing nothing (false-green exit 0).
        if not os.getenv("LLM_API_KEY"):
            raise RuntimeError(
                "LLM_API_KEY (or OPENROUTER_API_KEY) is not set; cognify requires an "
                "LLM key to extract the knowledge graph."
            )
        import cognee

        await self._ensure_cognee_ready(cognee)
        # Single Kuzu writer: serialize the graph write against any other in-process
        # cognify so they cannot collide on the lock (#47).
        async with self.writer_lock:
            return await cognee.cognify(datasets=datasets, incremental_loading=not force)

    async def add_feedback(
        self,
        *,
        session_id: str,
        qa_id: str,
        score: int | None,
        text: str | None,
    ) -> bool:
        self._prepare_cognee_environment()
        import cognee

        await self._ensure_cognee_ready(cognee)
        return await cognee.session.add_feedback(
            session_id=session_id,
            qa_id=qa_id,
            feedback_score=score,
            feedback_text=text,
        )

    async def improve(
        self,
        *,
        dataset: str,
        session_ids: list[str] | None = None,
        build_global_context_index: bool = False,
    ) -> Any:
        self._prepare_cognee_environment()
        # Mirror cognify's fail-loud guard: cognee swallows LLMAPIKeyNotSetError
        # internally and returns normally, so a keyless improve would report
        # success while doing nothing (false-green exit 0, #41).
        if not os.getenv("LLM_API_KEY"):
            raise RuntimeError(
                "LLM_API_KEY (or OPENROUTER_API_KEY) is not set; improve requires an "
                "LLM key."
            )
        import cognee

        await self._ensure_cognee_ready(cognee)
        return await cognee.improve(
            dataset=dataset,
            session_ids=session_ids,
            build_global_context_index=build_global_context_index,
        )
