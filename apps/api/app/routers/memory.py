from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.project import Project

router = APIRouter()


@router.get("/{project_id}/memory/canon")
async def get_canon_rules(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"canon_rules": project.canon_rules}


@router.put("/{project_id}/memory/canon")
async def update_canon_rules(project_id: str, canon_rules: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.canon_rules = canon_rules
    await db.commit()
    return {"canon_rules": project.canon_rules}


@router.get("/{project_id}/memory/summary")
async def get_long_summary(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"long_summary": project.long_summary}


@router.post("/{project_id}/memory/search")
async def search_rag(project_id: str, query: str, top_k: int = 5):
    # TODO: Implement RAG search with Qdrant
    return {"results": [], "query": query}
