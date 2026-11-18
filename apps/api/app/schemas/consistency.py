from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.understanding import _coerce_nested_json


class ConsistencyIssue(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_json_strings(cls, data: Any) -> Any:
        return _coerce_nested_json(data)

    category: str = Field(description="canon|character|state|plot|asset")
    severity: str = Field(description="critical|warning|info")
    location: str = Field(default="", description="Page/panel reference, e.g. 'page 2 panel 2-1'")
    description: str = Field(description="What is inconsistent")
    suggestion: str | None = Field(default=None, description="How to fix it")


class ConsistencyReport(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _unwrap_json_strings(cls, data: Any) -> Any:
        return _coerce_nested_json(data)

    issues: list[ConsistencyIssue] = Field(default_factory=list)
    overall: str = Field(default="pass", description="pass|warning|fail")
