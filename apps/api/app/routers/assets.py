from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.asset import (
    AssetClusterResponse,
    AssetCreate,
    AssetMergeRequest,
    AssetResponse,
    AssetUpdate,
)
from app.services import asset_service

router = APIRouter()


@router.get("/{project_id}/assets", response_model=dict)
async def list_assets(
    project_id: str,
    type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
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


@router.post("/{project_id}/assets/cluster", response_model=AssetClusterResponse)
async def cluster_assets(
    project_id: str,
    type: str | None = None,
    similarity_threshold: float = Query(0.85, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    return await asset_service.cluster_assets(db, project_id, asset_type=type, similarity_threshold=similarity_threshold)


@router.post("/{project_id}/assets/merge", response_model=AssetResponse, status_code=201)
async def merge_assets(project_id: str, data: AssetMergeRequest, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.merge_assets(db, project_id, data)
    return AssetResponse.model_validate(asset)


@router.get("/assets/{asset_id}/similar", response_model=list)
async def find_similar_assets(
    asset_id: str,
    top_k: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return await asset_service.find_similar_assets(db, asset.project_id, asset_id, top_k=top_k)


@router.post("/assets/{asset_id}/vectorize", response_model=AssetResponse)
async def vectorize_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await asset_service.vectorize_asset(db, asset)
    await db.refresh(asset)
    return AssetResponse.model_validate(asset)
