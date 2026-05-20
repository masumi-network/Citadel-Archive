from __future__ import annotations

from typing import Any, Protocol


class CogneeGateway(Protocol):
    async def remember(
        self,
        data: Any,
        *,
        dataset_name: str,
        session_id: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Any:
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


class CogneePublicClient:
    async def remember(
        self,
        data: Any,
        *,
        dataset_name: str,
        session_id: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> Any:
        import cognee

        metadata = {"citadel_tags": list(tags)} if tags else None

        if hasattr(cognee, "remember"):
            kwargs: dict[str, Any] = {}
            if metadata:
                kwargs["external_metadata"] = metadata

            return await cognee.remember(
                data,
                dataset_name=dataset_name,
                session_id=session_id,
                **kwargs,
            )

        kwargs = {"dataset_name": dataset_name}
        if metadata:
            kwargs["metadata"] = metadata

        added = await cognee.add(data, **kwargs)
        cognified = await cognee.cognify(datasets=[dataset_name])
        return {"added": added, "cognified": cognified}

    async def recall(
        self,
        query: str,
        *,
        dataset: str,
        session_id: str | None = None,
        top_k: int = 10,
    ) -> list[Any]:
        import cognee

        if hasattr(cognee, "recall"):
            return await cognee.recall(
                query,
                datasets=[dataset],
                session_id=session_id,
                top_k=top_k,
            )

        return await cognee.search(
            query_text=query,
            datasets=[dataset],
            top_k=top_k,
        )

    async def add_feedback(
        self,
        *,
        session_id: str,
        qa_id: str,
        score: int | None,
        text: str | None,
    ) -> bool:
        import cognee

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
        import cognee

        return await cognee.improve(
            dataset=dataset,
            session_ids=session_ids,
            build_global_context_index=build_global_context_index,
        )
