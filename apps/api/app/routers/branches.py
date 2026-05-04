from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.branch import BranchCreate, BranchResponse
from app.services import branch_service

router = APIRouter()


@router.get("/{project_id}/branches", response_model=list[BranchResponse])
async def list_branches(project_id: str, db: AsyncSession = Depends(get_db)):
    branches = await branch_service.list_branches(db, project_id)
    return [BranchResponse.model_validate(b) for b in branches]


@router.post("/{project_id}/branches", response_model=BranchResponse, status_code=201)
async def create_branch(project_id: str, data: BranchCreate, db: AsyncSession = Depends(get_db)):
    branch = await branch_service.create_branch(db, project_id, data)
    return BranchResponse.model_validate(branch)


@router.get("/branches/{branch_id}", response_model=BranchResponse)
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)):
    branch = await branch_service.get_branch(db, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return BranchResponse.model_validate(branch)
