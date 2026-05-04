from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.pit import PitCreate, PitResponse, PitUpdate
from app.services import pit_service

router = APIRouter()


@router.get("/{project_id}/pits", response_model=dict)
async def list_pits(
    project_id: str,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await pit_service.list_pits(db, project_id, status=status, page=page, page_size=page_size)
    return {"items": [PitResponse.model_validate(p) for p in items], "total": total}


@router.post("/{project_id}/pits", response_model=PitResponse, status_code=201)
async def create_pit(project_id: str, data: PitCreate, db: AsyncSession = Depends(get_db)):
    pit = await pit_service.create_pit(db, project_id, data)
    return PitResponse.model_validate(pit)


@router.get("/pits/{pit_id}", response_model=PitResponse)
async def get_pit(pit_id: str, db: AsyncSession = Depends(get_db)):
    pit = await pit_service.get_pit(db, pit_id)
    if not pit:
        raise HTTPException(status_code=404, detail="Pit not found")
    return PitResponse.model_validate(pit)


@router.put("/pits/{pit_id}", response_model=PitResponse)
async def update_pit(pit_id: str, data: PitUpdate, db: AsyncSession = Depends(get_db)):
    pit = await pit_service.get_pit(db, pit_id)
    if not pit:
        raise HTTPException(status_code=404, detail="Pit not found")
    pit = await pit_service.update_pit(db, pit, data)
    return PitResponse.model_validate(pit)


@router.post("/pits/{pit_id}/resolve", response_model=PitResponse)
async def resolve_pit(pit_id: str, resolved_episode_id: str, db: AsyncSession = Depends(get_db)):
    pit = await pit_service.get_pit(db, pit_id)
    if not pit:
        raise HTTPException(status_code=404, detail="Pit not found")
    pit = await pit_service.update_pit(db, pit, PitUpdate(status="resolved"))
    pit.resolved_episode_id = resolved_episode_id
    await db.commit()
    await db.refresh(pit)
    return PitResponse.model_validate(pit)
