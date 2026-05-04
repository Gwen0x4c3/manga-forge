from __future__ import annotations

from pydantic import BaseModel, Field


class UnderstandRequest(BaseModel):
    episode_id: str


class UnderstandResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"


class ScriptGenerateRequest(BaseModel):
    episode_id: str
    branch_id: str
    base_episode_number: int = Field(description="Generate the next episode after this number")
    tone: str = Field(default="main", description="main|daily|climax|filler|pit_resolve")
    custom_instructions: str | None = Field(default=None, description="Additional user instructions")


class ScriptGenerateResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"


class GenerationRunResponse(BaseModel):
    id: str
    episode_id: str
    stage: str
    status: str
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

    model_config = {"from_attributes": True}
