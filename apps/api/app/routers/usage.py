from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.usage import UsageRecordListResponse, UsageSummaryResponse
from app.services import usage_service

router = APIRouter()


@router.get("/summary", response_model=UsageSummaryResponse)
async def get_usage_summary(
    project_id: str | None = Query(None),
    episode_id: str | None = Query(None),
    days: int | None = Query(None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    return await usage_service.get_usage_summary(
        db,
        project_id=project_id,
        episode_id=episode_id,
        days=days,
    )


@router.get("/records", response_model=UsageRecordListResponse)
async def list_usage_records(
    project_id: str | None = Query(None),
    episode_id: str | None = Query(None),
    kind: str | None = Query(None, description="llm|embedding|image"),
    model: str | None = Query(None),
    operation: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await usage_service.list_usage_records(
        db,
        project_id=project_id,
        episode_id=episode_id,
        kind=kind,
        model=model,
        operation=operation,
        status=status,
        page=page,
        page_size=page_size,
    )
