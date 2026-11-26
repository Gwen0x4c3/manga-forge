from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services import memory_service

router = APIRouter()


class SummaryUpdatePayload(BaseModel):
    long_summary: str


class StoryAskPayload(BaseModel):
    question: str
    branch_id: str | None = None
    max_episode_number: Decimal | None = None


@router.get("/{project_id}/memory/canon")
async def get_canon_rules(project_id: str, db: AsyncSession = Depends(get_db)):
    canon = await memory_service.get_canon_rules(db, project_id)
    if canon is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"canon_rules": canon}


@router.put("/{project_id}/memory/canon")
async def update_canon_rules(
    project_id: str,
    canon_rules: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    result = await memory_service.update_canon_rules(db, project_id, canon_rules)
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"canon_rules": result}


@router.get("/{project_id}/memory/summary")
async def get_long_summary(project_id: str, db: AsyncSession = Depends(get_db)):
    summary = await memory_service.get_long_summary(db, project_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"long_summary": summary}


@router.put("/{project_id}/memory/summary")
async def update_long_summary(
    project_id: str,
    payload: SummaryUpdatePayload,
    db: AsyncSession = Depends(get_db),
):
    summary = await memory_service.update_long_summary(db, project_id, payload.long_summary)
    if summary is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"long_summary": summary}


@router.get("/{project_id}/memory/recent")
async def get_recent_window(
    project_id: str,
    branch_id: str = Query(...),
    window_size: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    window = await memory_service.get_recent_window(db, project_id, branch_id, window_size)
    return {"episodes": window}


@router.post("/{project_id}/memory/search")
async def search_rag(
    project_id: str,
    query: str = Query(...),
    top_k: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    results = await memory_service.search_rag(db, project_id, query, top_k)
    return {"results": results, "query": query}


@router.get("/{project_id}/memory/context")
async def get_generation_context(
    project_id: str,
    branch_id: str = Query(...),
    base_episode_number: Decimal = Query(...),
    custom_instructions: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    context = await memory_service.build_context_for_generation(
        db,
        project_id,
        branch_id,
        base_episode_number,
        custom_instructions=custom_instructions,
    )
    return context


@router.get("/{project_id}/memory/graph")
async def get_story_graph(
    project_id: str,
    branch_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    graph = await memory_service.build_story_graph(db, project_id, branch_id=branch_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return graph


@router.post("/{project_id}/memory/ask")
async def ask_story_bible(
    project_id: str,
    payload: StoryAskPayload,
    db: AsyncSession = Depends(get_db),
):
    from app.core.llm import ensure_llm_configured

    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    ensure_llm_configured()
    try:
        return await memory_service.ask_story_bible(
            db,
            project_id,
            payload.question.strip(),
            branch_id=payload.branch_id,
            max_episode_number=payload.max_episode_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
