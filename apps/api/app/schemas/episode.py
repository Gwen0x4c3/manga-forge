from datetime import datetime

from pydantic import BaseModel, Field


class EpisodeImport(BaseModel):
    branch_id: str
    number: int = Field(..., ge=1)
    title: str | None = None
    source: str = Field(default="import_local")


class EpisodeUpdate(BaseModel):
    title: str | None = None
    status: str | None = Field(None, pattern="^(imported|understood|scripted|rendered|published|draft|generating)$")


class EpisodeResponse(BaseModel):
    id: str
    project_id: str
    branch_id: str
    number: int
    title: str | None
    source: str
    status: str
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
