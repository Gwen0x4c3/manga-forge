from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.branch import (
    BranchCreate,
    BranchDetailResponse,
    BranchResponse,
    DiffRequest,
    DiffResponse,
    ForkRequest,
    MergeRequest,
    MergeResponse,
)
from app.services import branch_service

router = APIRouter()


@router.get("/{project_id}/branches", response_model=list[BranchDetailResponse])
async def list_branches(project_id: str, db: AsyncSession = Depends(get_db)):
    branches = await branch_service.list_branches(db, project_id)
    result = []
    for b in branches:
        episode_count = await branch_service.get_branch_episode_count(db, b.id)
        latest_number = await branch_service.get_branch_latest_episode_number(db, b.id)
        result.append(BranchDetailResponse(
            id=b.id,
            project_id=b.project_id,
            name=b.name,
            description=b.description,
            is_default=b.is_default,
            base_branch_id=b.base_branch_id,
            base_episode_id=b.base_episode_id,
            created_at=b.created_at,
            updated_at=b.updated_at,
            episode_count=episode_count,
            latest_episode_number=latest_number,
        ))
    return result


@router.post("/{project_id}/branches", response_model=BranchResponse, status_code=201)
async def create_branch(project_id: str, data: BranchCreate, db: AsyncSession = Depends(get_db)):
    branch = await branch_service.create_branch(db, project_id, data)
    return BranchResponse.model_validate(branch)


@router.get("/branches/{branch_id}", response_model=BranchDetailResponse)
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await branch_service.get_branch(db, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    episode_count = await branch_service.get_branch_episode_count(db, branch.id)
    latest_number = await branch_service.get_branch_latest_episode_number(db, branch.id)
    return BranchDetailResponse(
        id=branch.id,
        project_id=branch.project_id,
        name=branch.name,
        description=branch.description,
        is_default=branch.is_default,
        base_branch_id=branch.base_branch_id,
        base_episode_id=branch.base_episode_id,
        created_at=branch.created_at,
        updated_at=branch.updated_at,
        episode_count=episode_count,
        latest_episode_number=latest_number,
    )


@router.post("/{project_id}/branches/fork", response_model=BranchResponse, status_code=201)
async def fork_branch(project_id: str, data: ForkRequest, db: AsyncSession = Depends(get_db)):
    try:
        branch = await branch_service.fork_from_episode(db, project_id, data)
        return BranchResponse.model_validate(branch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/branches/diff", response_model=DiffResponse)
async def diff_branches(project_id: str, data: DiffRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await branch_service.diff_branches(db, project_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/branches/merge", response_model=MergeResponse)
async def merge_branches(project_id: str, data: MergeRequest, db: AsyncSession = Depends(get_db)):
    try:
        return await branch_service.merge_branches(db, project_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/branches/{branch_id}", status_code=204)
async def delete_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await branch_service.get_branch(db, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    if branch.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete default branch")
    await branch_service.delete_branch(db, branch)
