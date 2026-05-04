from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.asset import AssetCreate, AssetResponse, AssetUpdate
from app.services import asset_service

router = APIRouter()


@router.get("/{project_id}/assets", response_model=dict)
async def list_assets(
    project_id: str,
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await asset_service.list_assets(db, project_id, asset_type=type, page=page, page_size=page_size)
    return {"items": [AssetResponse.model_validate(a) for a in items], "total": total}


@router.post("/{project_id}/assets", response_model=AssetResponse, status_code=201)
async def create_asset(project_id: str, data: AssetCreate, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.create_asset(db, project_id, data)
    return AssetResponse.model_validate(asset)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetResponse.model_validate(asset)


@router.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(asset_id: str, data: AssetUpdate, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    asset = await asset_service.update_asset(db, asset, data)
    return AssetResponse.model_validate(asset)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await asset_service.delete_asset(db, asset)
