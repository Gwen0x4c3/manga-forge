from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.asset import (
    AssetClusterResponse,
    AssetCreate,
    AssetCropFromPageRequest,
    AssetImageResponse,
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
    return await asset_service.cluster_assets(
        db, project_id, asset_type=type, similarity_threshold=similarity_threshold
    )


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


@router.get("/assets/{asset_id}/images", response_model=dict)
async def list_asset_images(asset_id: str, db: AsyncSession = Depends(get_db)):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    images = await asset_service.list_asset_images(db, asset_id)
    return {"items": [AssetImageResponse.model_validate(img) for img in images]}


@router.post("/assets/{asset_id}/images", response_model=AssetImageResponse, status_code=201)
async def upload_asset_image(
    asset_id: str,
    kind: str = Form("reference"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        image = await asset_service.upload_asset_image(
            db,
            asset,
            content,
            file.filename or "reference.png",
            kind=kind,
            content_type=file.content_type or "image/png",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AssetImageResponse.model_validate(image)


@router.post("/assets/{asset_id}/crop-from-page", response_model=AssetImageResponse, status_code=201)
async def crop_asset_from_page(
    asset_id: str,
    request: AssetCropFromPageRequest,
    db: AsyncSession = Depends(get_db),
):
    asset = await asset_service.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    try:
        image = await asset_service.crop_asset_image_from_page(
            db=db,
            asset=asset,
            episode_id=request.episode_id,
            page_index=request.page_index,
            bbox=request.bbox,
            kind=request.kind,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AssetImageResponse.model_validate(image)


@router.post("/asset-images/{image_id}/set-primary", response_model=AssetImageResponse)
async def set_primary_asset_image(image_id: str, db: AsyncSession = Depends(get_db)):
    image = await asset_service.get_asset_image(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Asset image not found")
    updated = await asset_service.set_primary_asset_image(db, image)
    return AssetImageResponse.model_validate(updated)


@router.delete("/asset-images/{image_id}", status_code=204)
async def delete_asset_image(image_id: str, db: AsyncSession = Depends(get_db)):
    image = await asset_service.get_asset_image(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Asset image not found")
    await asset_service.delete_asset_image(db, image)
