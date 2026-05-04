from datetime import datetime

from pydantic import BaseModel, Field


class PitCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    priority: int = Field(default=0)
    introduced_episode_id: str
    trigger_hint: str | None = None


class PitUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    status: str | None = Field(None, pattern="^(open|resolved|abandoned)$")
    trigger_hint: str | None = None


class PitResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: str | None
    priority: int
    introduced_episode_id: str
    resolved_episode_id: str | None
    status: str
    trigger_hint: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
