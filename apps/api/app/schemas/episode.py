from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class EpisodeImport(BaseModel):
    branch_id: str
    number: Decimal = Field(..., gt=0, description="Sort order, system-managed")
    label: str = Field(default="", description="Author's original episode number, e.g. '36', '36.5', '番外1'")
    title: str | None = None
    source: str = Field(default="import_local")
    category: str = Field(default="regular", pattern="^(regular|special|extra)$")


class EpisodeUpdate(BaseModel):
    title: str | None = None
    status: str | None = Field(None, pattern="^(imported|understood|scripted|rendered|published|draft|generating)$")
    category: str | None = Field(None, pattern="^(regular|special|extra)$")
    label: str | None = None


class EpisodeResponse(BaseModel):
    id: str
    project_id: str
    branch_id: str
    number: Decimal
    label: str
    title: str | None
    source: str
    status: str
    category: str
    parent_episode_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EpisodePageResponse(BaseModel):
    id: str
    episode_id: str
    page_index: int
    image_path: str
    width: int | None
    height: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EpisodeMemoryResponse(BaseModel):
    id: str
    episode_id: str
    type: str
    content: dict
    created_at: datetime

    model_config = {"from_attributes": True}
