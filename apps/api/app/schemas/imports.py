from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer

from app.schemas.episode import EpisodeResponse
from app.schemas.project import ProjectResponse


class MangaDexDiscoverRequest(BaseModel):
    source_url: str = Field(..., min_length=1)
    branch_id: str
    request_curl: str | None = None
    languages: list[str] | None = None
    group_ids: list[str] | None = None
    fill_project_metadata: bool = True
    overwrite_project_metadata: bool = False


class MangaDexCreateProjectRequest(BaseModel):
    source_url: str = Field(..., min_length=1)
    request_curl: str | None = None
    languages: list[str] | None = None
    group_ids: list[str] | None = None
    fill_project_metadata: bool = True
    overwrite_project_metadata: bool = False


class ImportSelectionRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    action: str = Field(default="select", pattern="^(select|unselect)$")


class ImportStartRequest(BaseModel):
    auto_understand: bool = False
    only_missing: bool = True
    use_data_saver: bool = True
    request_curl: str | None = None


class ImportJobItemResponse(BaseModel):
    id: str
    external_chapter_id: str
    chapter_number: str
    sort_number: Decimal
    volume: str | None
    title: str | None
    translated_language: str
    group_ids: list[str] | None
    group_names: list[str] | None
    page_count: int | None
    selection_status: str
    import_status: str
    episode_id: str | None
    external_url: str | None
    progress: dict | None
    metadata_json: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _redact_request_headers(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return payload
    sanitized = dict(payload)
    request_headers = sanitized.get("request_headers")
    if isinstance(request_headers, dict):
        sanitized["request_headers"] = {
            key: value for key, value in request_headers.items() if str(key).strip().lower() != "authorization"
        } or None
    return sanitized


class ImportJobResponse(BaseModel):
    id: str
    project_id: str
    branch_id: str
    binding_id: str | None
    provider: str
    job_type: str
    status: str
    source_url: str | None
    external_series_id: str | None
    config: dict | None
    metadata_json: dict | None
    progress: dict | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("config", "metadata_json")
    def serialize_secret_safe_payload(self, value: dict | None) -> dict | None:
        return _redact_request_headers(value)


class MangaDexDiscoverResponse(BaseModel):
    project: ProjectResponse
    job: ImportJobResponse
    items: list[ImportJobItemResponse]


class MangaDexCreateProjectResponse(BaseModel):
    project: ProjectResponse
    job: ImportJobResponse
    items: list[ImportJobItemResponse]


class ImportExecutionResponse(BaseModel):
    job: ImportJobResponse
    task_id: str


class ImportJobListResponse(BaseModel):
    items: list[ImportJobResponse]
    total: int


class ImportedEpisodeResponse(BaseModel):
    episode: EpisodeResponse
    external_chapter_id: str
