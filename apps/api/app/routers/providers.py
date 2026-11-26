from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.provider_runtime import VALID_ROLES
from app.database import get_db
from app.schemas.provider import (
    ModelProviderResponse,
    ProviderCreateRequest,
    ProviderOverviewResponse,
    ProviderTestRequest,
    ProviderTestResponse,
    ProviderUpdateRequest,
    RoleBindingItem,
    RoleBindingUpdateRequest,
)
from app.services import provider_service

router = APIRouter()


@router.get("", response_model=ProviderOverviewResponse)
async def get_providers_overview(db: AsyncSession = Depends(get_db)):
    return await provider_service.get_overview(db)


@router.post("", response_model=ModelProviderResponse)
async def create_provider(payload: ProviderCreateRequest, db: AsyncSession = Depends(get_db)):
    return await provider_service.create_provider(db, payload)


@router.put("/{provider_id}", response_model=ModelProviderResponse)
async def update_provider(
    provider_id: str,
    payload: ProviderUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    updated = await provider_service.update_provider(db, provider_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Provider not found")
    return updated


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    ok = await provider_service.delete_provider(db, provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"deleted": True}


@router.post("/test", response_model=ProviderTestResponse)
async def test_provider(payload: ProviderTestRequest, db: AsyncSession = Depends(get_db)):
    return await provider_service.test_provider(db, payload)


@router.put("/roles/{role}", response_model=RoleBindingItem)
async def update_role_binding(
    role: str,
    payload: RoleBindingUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
    try:
        return await provider_service.update_role_binding(db, role, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
