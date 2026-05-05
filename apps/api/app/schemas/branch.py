from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    base_branch_id: str | None = None
    base_episode_id: str | None = None


class BranchResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str | None
    is_default: bool
    base_branch_id: str | None
    base_episode_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BranchDetailResponse(BranchResponse):
    episode_count: int = 0
    latest_episode_number: Decimal | None = None


class ForkRequest(BaseModel):
    episode_id: str
    branch_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class DiffRequest(BaseModel):
    source_branch_id: str
    target_branch_id: str
    episode_number: Decimal | None = None


class EpisodeDiffItem(BaseModel):
    number: Decimal
    label: str
    source_status: str | None = None
    target_status: str | None = None
    title_source: str | None = None
    title_target: str | None = None
    summary_source: str | None = None
    summary_target: str | None = None


class AssetDiffItem(BaseModel):
    name: str
    asset_type: str
    in_source: bool = False
    in_target: bool = False
    description_source: str | None = None
    description_target: str | None = None


class PitDiffItem(BaseModel):
    title: str
    status_source: str | None = None
    status_target: str | None = None


class DiffResponse(BaseModel):
    episodes: list[EpisodeDiffItem] = []
    assets: list[AssetDiffItem] = []
    pits: list[PitDiffItem] = []
    canon_diff: dict | None = None


class MergeItem(BaseModel):
    item_type: str = Field(..., pattern="^(episode|asset|pit|canon_rule)$")
    source_id: str
    action: str = Field(..., pattern="^(adopt|skip)$")


class MergeRequest(BaseModel):
    source_branch_id: str
    target_branch_id: str
    items: list[MergeItem]


class MergeResponse(BaseModel):
    merged_items: list[str] = []
    skipped_items: list[str] = []
    errors: list[str] = []
