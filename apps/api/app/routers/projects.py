from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectResponse, ProjectUpdate
from app.services import project_service

router = APIRouter()


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await project_service.list_projects(db, keyword=keyword, page=page, page_size=page_size)
    return ProjectListResponse(items=[ProjectResponse.model_validate(p) for p in items], total=total)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = await project_service.create_project(db, data)
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    project = await project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project = await project_service.update_project(db, project, data)
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await project_service.delete_project(db, project)
