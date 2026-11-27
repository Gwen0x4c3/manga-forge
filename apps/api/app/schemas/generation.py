from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class UnderstandRequest(BaseModel):
    episode_id: str
    concurrency: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Intra-episode vision concurrency (1 = strict sequential, 2-8 = concurrent windows/crops)",
    )


class UnderstandResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"
    concurrency: int = 1


class BatchUnderstandRequest(BaseModel):
    project_id: str
    branch_id: str | None = Field(default=None, description="Target branch ID (defaults to main branch)")
    force: bool = Field(
        default=False,
        description="Re-understand all episodes in order if True; only status='imported' if False",
    )
    concurrency: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="Intra-episode vision concurrency override (episodes still run strictly sequentially)",
    )


class BatchUnderstandResponse(BaseModel):
    task_id: str
    project_id: str
    branch_id: str
    episode_ids: list[str] = Field(default_factory=list)
    total: int = 0
    status: str = "queued"
    concurrency: int = 1


class UnderstandProgressResponse(BaseModel):
    project_id: str
    branch_id: str | None = None
    active: bool = False
    overall_pct: float = 0.0
    total_episodes: int = 0
    understood_count: int = 0
    imported_count: int = 0
    active_runs_count: int = 0
    concurrency: int = 1
    current_episode_id: str | None = None
    current_episode_label: str | None = None
    phase: str | None = None
    phase_label: str | None = None
    episode_pct: int = 0
    batch_index: int | None = None
    batch_completed: int | None = None
    batch_total: int | None = None
    batch_failed: int = 0
    active_episode_ids: list[str] = Field(default_factory=list)
    queued_episode_ids: list[str] = Field(default_factory=list)
    elapsed_sec: int | None = None
    recent_error: str | None = None


class StoryboardUpdateRequest(BaseModel):
    storyboard: dict


class ScriptGenerateRequest(BaseModel):
    episode_id: str
    branch_id: str
    base_episode_number: Decimal = Field(description="Generate the next episode after this number")
    tone: str = Field(default="main", description="main|daily|climax|filler|pit_resolve")
    custom_instructions: str | None = Field(default=None, description="Additional user instructions")
    context_profile: str | None = Field(
        default=None,
        pattern="^(quality|balanced|cost)$",
        description="Context budget profile: quality (200K+) | balanced (128K) | cost (32K)",
    )


class ScriptGenerateResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"


class RenderRequest(BaseModel):
    episode_id: str
    storyboard_memory_id: str | None = Field(
        default=None, description="Specific storyboard memory ID, uses latest if None"
    )
    image_backend: str | None = Field(default=None, description="Override image backend: openai|gemini|custom|mock")
    image_model: str | None = Field(default=None, description="Override image model")
    image_size: str | None = Field(default="1024x1024", description="Image size for generation")


class RenderResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"
    panel_count: int = Field(default=0, description="Total number of panels to render")


class PanelRerenderRequest(BaseModel):
    prompt: str | None = Field(
        default=None, description="Override prompt for this panel; defaults to storyboard prompt"
    )
    negative_prompt: str | None = None
    reference_asset_ids: list[str] | None = Field(
        default=None, description="Explicit asset IDs to attach as visual references"
    )
    image_backend: str | None = Field(
        default=None, description="Override image backend: openai|gemini|comfyui|antigravity|custom|mock"
    )
    image_model: str | None = None
    image_size: str | None = Field(default="1024x1024")


class PanelInpaintRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Inpaint prompt describing the edited region")
    mask_base64: str = Field(..., min_length=8, description="Base64-encoded PNG mask (white=edit, black=keep)")
    image_backend: str | None = None
    image_model: str | None = None


class LayoutRequest(BaseModel):
    episode_id: str
    template_override: dict[int, str] | None = Field(
        default=None, description="Override layout template per page: {page_number: layout}"
    )
    writing_mode: str = Field(
        default="horizontal",
        pattern="^(horizontal|vertical)$",
        description="Speech bubble lettering mode: horizontal or vertical (traditional CJK manga)",
    )
    sync: bool = Field(
        default=False,
        description="Execute layout composition synchronously in-process and return composed pages immediately",
    )


class LayoutResponse(BaseModel):
    task_id: str
    episode_id: str
    status: str = "queued"
    page_count: int = Field(default=0, description="Total number of pages to compose")
    pages: list[dict] | None = None


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
    base_episode_number: Decimal = Field(
        description="Continue from this episode number, new episode will be base_episode_number + 1"
    )
    tone: str = Field(default="main", description="main|daily|climax|filler|pit_resolve")
    custom_instructions: str | None = Field(default=None, description="Additional user instructions")
    title: str | None = Field(default=None, description="Optional title for the new episode")
    image_backend: str | None = Field(default=None, description="Override image backend")
    image_model: str | None = Field(default=None, description="Override image model")
    image_size: str = Field(default="1024x1024", description="Image size for generation")
    context_profile: str | None = Field(
        default=None,
        pattern="^(quality|balanced|cost)$",
        description="Context budget profile: quality (200K+) | balanced (128K) | cost (32K)",
    )


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
    params: dict | None = None
    retrieved_context: dict | None = None
    error: str | None = None
    commit_message: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

    model_config = {"from_attributes": True}
