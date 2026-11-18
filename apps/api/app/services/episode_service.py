from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.episode import Episode
from app.models.episode_memory import EpisodeMemory
from app.models.episode_page import EpisodePage
from app.models.import_job_item import ImportJobItem
from app.models.pit import Pit
from app.schemas.episode import EpisodeImport, EpisodeUpdate


async def list_episodes(
    db: AsyncSession, project_id: str, branch_id: str | None = None, page: int = 1, page_size: int = 50
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
    payload = data.model_dump()
    if not payload.get("label"):
        num = payload["number"]
        payload["label"] = str(int(num)) if num == int(num) else str(num)
    episode = Episode(project_id=project_id, **payload)
    db.add(episode)
    await db.commit()
    await db.refresh(episode)
    return episode


async def get_episode(db: AsyncSession, episode_id: str) -> Episode | None:
    result = await db.execute(select(Episode).where(Episode.id == episode_id).limit(1))
    return result.scalar_one_or_none()


async def find_episode(db: AsyncSession, project_id: str, branch_id: str, number: Decimal) -> Episode | None:
    result = await db.execute(
        select(Episode)
        .where(
            Episode.project_id == project_id,
            Episode.branch_id == branch_id,
            Episode.number == number,
        )
        .order_by(Episode.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_next_episode_number(db: AsyncSession, project_id: str, branch_id: str) -> Decimal:
    result = await db.execute(
        select(func.max(Episode.number)).where(
            Episode.project_id == project_id,
            Episode.branch_id == branch_id,
        )
    )
    max_number = result.scalar()
    if max_number is None:
        return Decimal("1")
    int_part = int(max_number)
    return Decimal(int_part + 1)


async def update_episode(db: AsyncSession, episode: Episode, data: EpisodeUpdate) -> Episode:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(episode, key, value)
    await db.commit()
    await db.refresh(episode)
    return episode


async def delete_episode(db: AsyncSession, episode: Episode) -> None:
    """Safely delete an episode while cleaning up FK references in pits, import items, and assets."""
    ep_id = episode.id
    project_id = episode.project_id

    # 1. Re-open pits resolved by this episode, and remove pits introduced solely by this episode
    await db.execute(
        update(Pit).where(Pit.resolved_episode_id == ep_id).values(resolved_episode_id=None, status="open")
    )
    await db.execute(delete(Pit).where(Pit.introduced_episode_id == ep_id))

    # 2. Unlink import_job_items referencing this episode
    await db.execute(update(ImportJobItem).where(ImportJobItem.episode_id == ep_id).values(episode_id=None))

    # 3. Clean episode_id from Asset.episode_ids JSON dict
    assets = (await db.execute(select(Asset).where(Asset.project_id == project_id))).scalars().all()
    for asset in assets:
        if asset.episode_ids and ep_id in asset.episode_ids:
            cleaned = {k: v for k, v in asset.episode_ids.items() if k != ep_id}
            asset.episode_ids = cleaned

    await db.delete(episode)
    await db.commit()


async def get_episode_pages(db: AsyncSession, episode_id: str) -> list[EpisodePage]:
    result = await db.execute(
        select(EpisodePage).where(EpisodePage.episode_id == episode_id).order_by(EpisodePage.page_index)
    )
    return list(result.scalars().all())


async def get_episode_memories(db: AsyncSession, episode_id: str) -> list[EpisodeMemory]:
    result = await db.execute(
        select(EpisodeMemory).where(EpisodeMemory.episode_id == episode_id).order_by(EpisodeMemory.created_at.asc())
    )
    return list(result.scalars().all())
