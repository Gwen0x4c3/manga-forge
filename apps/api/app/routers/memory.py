from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services import memory_service

router = APIRouter()


@router.get("/{project_id}/memory/canon")
async def get_canon_rules(project_id: str, db: AsyncSession = Depends(get_db)):
    canon = await memory_service.get_canon_rules(db, project_id)
    if canon is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"canon_rules": canon}


@router.put("/{project_id}/memory/canon")
async def update_canon_rules(project_id: str, canon_rules: dict, db: AsyncSession = Depends(get_db)):
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
    query: str,
    top_k: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    results = await memory_service.search_rag(db, project_id, query, top_k)
    return {"results": results, "query": query}


@router.get("/{project_id}/memory/context")
async def get_generation_context(
    project_id: str,
    branch_id: str = Query(...),
    base_episode_number: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    context = await memory_service.build_context_for_generation(
        db, project_id, branch_id, base_episode_number
    )
    return context
