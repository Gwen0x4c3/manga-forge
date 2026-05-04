from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.episode_page import EpisodePage
from app.schemas.episode import EpisodeImport, EpisodeUpdate


async def list_episodes(
    db: AsyncSession, project_id: str, branch_id: str | None = None, page: int = 1, page_size: int = 20
):
    query = select(Episode).where(Episode.project_id == project_id)
    count_query = select(func.count()).select_from(Episode).where(Episode.project_id == project_id)
    if branch_id:
        query = query.where(Episode.branch_id == branch_id)
        count_query = count_query.where(Episode.branch_id == branch_id)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Episode.number.asc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def create_episode(db: AsyncSession, project_id: str, data: EpisodeImport) -> Episode:
    episode = Episode(project_id=project_id, **data.model_dump())
    db.add(episode)
    await db.commit()
    await db.refresh(episode)
    return episode


async def get_episode(db: AsyncSession, episode_id: str) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id))
    return result.scalar_one_or_none()


async def update_episode(db: AsyncSession, episode: Episode, data: EpisodeUpdate) -> Episode:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(episode, key, value)
    await db.commit()
    await db.refresh(episode)
    return episode


async def get_episode_pages(db: AsyncSession, episode_id: str) -> list[EpisodePage]:
    result = await db.execute(
        select(EpisodePage).where(EpisodePage.episode_id == episode_id).order_by(EpisodePage.page_index)
    )
    return result.scalars().all()


async def get_episode_memories(db: AsyncSession, episode_id: str) -> list[EpisodeMemory]:
    result = await db.execute(select(EpisodeMemory).where(EpisodeMemory.episode_id == episode_id))
    return result.scalars().all()
