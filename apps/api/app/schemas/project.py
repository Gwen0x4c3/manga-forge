from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    language: str = Field(default="zh", pattern="^(zh|ja|en)$")


class ProjectUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    language: str | None = Field(None, pattern="^(zh|ja|en)$")
    canon_rules: dict | None = None
    long_summary: str | None = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str | None
    language: str
    canon_rules: dict | None
    long_summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
