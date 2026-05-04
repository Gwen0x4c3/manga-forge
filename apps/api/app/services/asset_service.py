from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetUpdate


async def list_assets(
    db: AsyncSession, project_id: str, asset_type: str | None = None, page: int = 1, page_size: int = 20
):
    query = select(Asset).where(Asset.project_id == project_id)
    count_query = select(func.count()).select_from(Asset).where(Asset.project_id == project_id)
    if asset_type:
        query = query.where(Asset.type == asset_type)
        count_query = count_query.where(Asset.type == asset_type)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Asset.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def create_asset(db: AsyncSession, project_id: str, data: AssetCreate) -> Asset:
    asset = Asset(project_id=project_id, **data.model_dump())
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def get_asset(db: AsyncSession, asset_id: str) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def update_asset(db: AsyncSession, asset: Asset, data: AssetUpdate) -> Asset:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(asset, key, value)
    await db.commit()
    await db.refresh(asset)
    return asset


async def delete_asset(db: AsyncSession, asset: Asset) -> None:
    await db.delete(asset)
    await db.commit()
