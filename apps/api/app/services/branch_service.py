from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branch import Branch
from app.schemas.branch import BranchCreate


async def list_branches(db: AsyncSession, project_id: str) -> list[Branch]:
    result = await db.execute(select(Branch).where(Branch.project_id == project_id))
    return result.scalars().all()


async def create_branch(db: AsyncSession, project_id: str, data: BranchCreate) -> Branch:
    branch = Branch(project_id=project_id, **data.model_dump())
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


async def get_branch(db: AsyncSession, branch_id: str) -> Branch | None:
    result = await db.execute(select(Branch).where(Branch.id == branch_id))
    return result.scalar_one_or_none()
