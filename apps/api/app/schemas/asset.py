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
    preview_image_path: str | None = None
    image_count: int = 0
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


class AssetImageResponse(BaseModel):
    id: str
    asset_id: str
    kind: str
    image_path: str
    meta: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetCropFromPageRequest(BaseModel):
    episode_id: str
    page_index: int = Field(ge=0, description="0-based page index in the episode")
    bbox: list[float] = Field(
        ..., min_length=4, max_length=4, description="Normalized [x1, y1, x2, y2] in 0..1 coordinates"
    )
    kind: str = Field(default="reference")
