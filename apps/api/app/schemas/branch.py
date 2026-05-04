from datetime import datetime

from pydantic import BaseModel, Field


class BranchCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    base_branch_id: str | None = None
    base_episode_id: str | None = None


class BranchResponse(BaseModel):
    id: str
    project_id: str
    name: str
    base_branch_id: str | None
    base_episode_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
