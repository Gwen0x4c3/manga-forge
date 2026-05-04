from __future__ import annotations

from decimal import Decimal

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
    base_episode_number: Decimal = Field(description="Generate the next episode after this number")
    tone: str = Field(default="main", description="main|daily|climax|filler|pit_resolve")
    custom_instructions: str | None = Field(default=None, description="Additional user instructions")


class ScriptGenerateResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"


class RenderRequest(BaseModel):
    episode_id: str
    storyboard_memory_id: str | None = Field(
        default=None, description="Specific storyboard memory ID, uses latest if None"
    )
    image_backend: str | None = Field(default=None, description="Override image backend: openai|custom|mock")
    image_model: str | None = Field(default=None, description="Override image model")
    image_size: str | None = Field(default="1024x1024", description="Image size for generation")


class RenderResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"
    panel_count: int = Field(default=0, description="Total number of panels to render")


class LayoutRequest(BaseModel):
    episode_id: str
    template_override: dict[int, str] | None = Field(
        default=None, description="Override layout template per page: {page_number: layout}"
    )


class LayoutResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"
    page_count: int = Field(default=0, description="Total number of pages to compose")


class GeneratedImageResponse(BaseModel):
    id: str
    generation_run_id: str
    episode_id: str
    panel_id: str | None = None
    image_path: str
    meta: dict | None = None
    created_at: str | None = None

    model_config = {"from_attributes": True}


class ComposedPageResponse(BaseModel):
    page_number: int
    image_path: str
    layout: str


class ContinueFromEpisodeRequest(BaseModel):
    project_id: str
    branch_id: str
    base_episode_number: Decimal = Field(description="Continue from this episode number, new episode will be base_episode_number + 1")
    tone: str = Field(default="main", description="main|daily|climax|filler|pit_resolve")
    custom_instructions: str | None = Field(default=None, description="Additional user instructions")
    title: str | None = Field(default=None, description="Optional title for the new episode")
    image_backend: str | None = Field(default=None, description="Override image backend")
    image_model: str | None = Field(default=None, description="Override image model")
    image_size: str = Field(default="1024x1024", description="Image size for generation")


class ContinueFromEpisodeResponse(BaseModel):
    episode_id: str
    episode_number: Decimal
    task_id: str
    status: str = "queued"


class GenerationRunResponse(BaseModel):
    id: str
    episode_id: str
    stage: str
    status: str
    backend: str | None = None
    model: str | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

    model_config = {"from_attributes": True}
