from datetime import datetime

from pydantic import BaseModel, Field


class AssetCreate(BaseModel):
    type: str = Field(..., pattern="^(character|outfit|location|item|style)$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    tags: dict | None = None
    prompt_snippets: dict | None = None
    parent_asset_id: str | None = None


class AssetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    tags: dict | None = None
    prompt_snippets: dict | None = None


class AssetResponse(BaseModel):
    id: str
    project_id: str
    type: str
    name: str
    description: str | None
    tags: dict | None
    prompt_snippets: dict | None
    parent_asset_id: str | None
    embedding: list | None = None
    episode_ids: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetClusterItem(BaseModel):
    asset_id: str
    name: str
    asset_type: str
    similarity: float


class AssetClusterGroup(BaseModel):
    representative_name: str
    asset_type: str
    items: list[AssetClusterItem]


class AssetClusterResponse(BaseModel):
    clusters: list[AssetClusterGroup]
    total_assets: int
    unclustered: int


class AssetMergeRequest(BaseModel):
    source_asset_ids: list[str] = Field(..., min_length=2)
    target_name: str
    target_description: str | None = None
