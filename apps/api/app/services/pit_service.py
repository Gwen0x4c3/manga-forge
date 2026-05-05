from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pit import Pit
from app.schemas.pit import PitCreate, PitUpdate


async def list_pits(db: AsyncSession, project_id: str, status: str | None = None, page: int = 1, page_size: int = 50):
    query = select(Pit).where(Pit.project_id == project_id)
    count_query = select(func.count()).select_from(Pit).where(Pit.project_id == project_id)
    if status:
        query = query.where(Pit.status == status)
        count_query = count_query.where(Pit.status == status)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Pit.priority.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def create_pit(db: AsyncSession, project_id: str, data: PitCreate) -> Pit:
    pit = Pit(project_id=project_id, **data.model_dump())
    db.add(pit)
    await db.commit()
    await db.refresh(pit)
    return pit


async def get_pit(db: AsyncSession, pit_id: str) -> Pit | None:
    result = await db.execute(select(Pit).where(Pit.id == pit_id))
    return result.scalar_one_or_none()


async def update_pit(db: AsyncSession, pit: Pit, data: PitUpdate) -> Pit:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(pit, key, value)
    await db.commit()
    await db.refresh(pit)
    return pit
