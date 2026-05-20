from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from kb.models import FeedbackRequest
from kb.service import Citadel

app = FastAPI(
    title="Citadel Archive",
    version="0.1.0",
    description="Self-hosted knowledge-base wrapper around Cognee.",
)


class IngestBody(BaseModel):
    data: str = Field(min_length=1)
    dataset: str | None = None
    tags: list[str] = Field(default_factory=list)
    session_id: str | None = None


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    dataset: str | None = None
    session_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)


class FeedbackBody(BaseModel):
    qa_id: str = Field(min_length=1)
    score: int | None = Field(default=None, ge=-1, le=1)
    text: str | None = None
    session_id: str | None = None
    dataset: str | None = None


class ImproveBody(BaseModel):
    dataset: str | None = None
    session_ids: list[str] | None = None


def get_citadel() -> Citadel:
    if not hasattr(app.state, "citadel"):
        app.state.citadel = Citadel.from_env()
    return app.state.citadel


@app.get("/healthz")
async def healthz() -> dict[str, str | bool]:
    return {"ok": True, "service": "citadel"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    config = get_citadel().config
    return {
        "ok": True,
        "service": "citadel",
        "tenant_id": config.tenant_id,
        "default_dataset": config.default_dataset,
        "auto_improve": config.auto_improve,
        "build_global_context_index": config.build_global_context_index,
    }


@app.post("/ingest")
async def ingest(body: IngestBody) -> Any:
    try:
        result = await get_citadel().ingest(
            body.data,
            dataset=body.dataset,
            tags=body.tags,
            session_id=body.session_id,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return jsonable_encoder(result)


@app.post("/search")
async def search(body: SearchBody) -> Any:
    try:
        results = await get_citadel().search(
            body.query,
            dataset=body.dataset,
            session_id=body.session_id,
            top_k=body.top_k,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return jsonable_encoder({"results": results})


@app.post("/feedback")
async def feedback(body: FeedbackBody) -> Any:
    try:
        result = await get_citadel().feedback(
            FeedbackRequest(
                qa_id=body.qa_id,
                score=body.score,
                text=body.text,
                session_id=body.session_id,
                dataset=body.dataset,
            )
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return jsonable_encoder(result)


@app.post("/improve")
async def improve(body: ImproveBody) -> Any:
    try:
        result = await get_citadel().improve(
            dataset=body.dataset,
            session_ids=body.session_ids,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime Cognee configuration.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return jsonable_encoder({"result": result})
