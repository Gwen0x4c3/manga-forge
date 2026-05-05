from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


async def list_projects(db: AsyncSession, keyword: str | None = None, page: int = 1, page_size: int = 20):
    query = select(Project)
    count_query = select(func.count()).select_from(Project)
    if keyword:
        query = query.where(Project.title.ilike(f"%{keyword}%"))
        count_query = count_query.where(Project.title.ilike(f"%{keyword}%"))
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Project.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


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
