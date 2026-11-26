from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


async def list_projects(db: AsyncSession, keyword: str | None = None, page: int = 1, page_size: int = 50):
    from app.models.episode import Episode
    from app.models.episode_page import EpisodePage

    query = select(Project)
    count_query = select(func.count()).select_from(Project)
    if keyword:
        query = query.where(Project.title.ilike(f"%{keyword}%"))
        count_query = count_query.where(Project.title.ilike(f"%{keyword}%"))
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Project.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    projects = list((await db.execute(query)).scalars().all())

    if projects:
        pids = [p.id for p in projects]
        ep_rows = (
            (
                await db.execute(
                    select(Episode).where(Episode.project_id.in_(pids)).order_by(Episode.number.asc())
                )
            )
            .scalars()
            .all()
        )
        ep_count: dict[str, int] = {}
        understood_count: dict[str, int] = {}
        first_ep_by_proj: dict[str, str] = {}
        for ep in ep_rows:
            ep_count[ep.project_id] = ep_count.get(ep.project_id, 0) + 1
            if ep.status in ("understood", "scripted", "rendered", "published"):
                understood_count[ep.project_id] = understood_count.get(ep.project_id, 0) + 1
            if ep.project_id not in first_ep_by_proj:
                first_ep_by_proj[ep.project_id] = ep.id

        cover_by_ep: dict[str, str] = {}
        first_ep_ids = list(first_ep_by_proj.values())
        if first_ep_ids:
            pg_rows = (
                (
                    await db.execute(
                        select(EpisodePage)
                        .where(EpisodePage.episode_id.in_(first_ep_ids))
                        .order_by(EpisodePage.page_index.asc())
                    )
                )
                .scalars()
                .all()
            )
            for pg in pg_rows:
                if pg.episode_id not in cover_by_ep:
                    cover_by_ep[pg.episode_id] = pg.image_path

        for p in projects:
            p.episode_count = ep_count.get(p.id, 0)  # type: ignore[attr-defined]
            p.understood_count = understood_count.get(p.id, 0)  # type: ignore[attr-defined]
            fep = first_ep_by_proj.get(p.id)
            p.cover_image_path = cover_by_ep.get(fep) if fep else None  # type: ignore[attr-defined]

    return projects, total


async def create_project(db: AsyncSession, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    await db.flush()
    from app.models.branch import Branch

    branch = Branch(project_id=project.id, name="main", is_default=True)
    db.add(branch)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(db: AsyncSession, project_id: str) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def update_project(db: AsyncSession, project: Project, data: ProjectUpdate) -> Project:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project: Project) -> None:
    await db.delete(project)
    await db.commit()
