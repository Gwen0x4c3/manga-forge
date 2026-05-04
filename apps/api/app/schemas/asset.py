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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
