from __future__ import annotations

from pydantic import BaseModel, Field


class ConsistencyIssue(BaseModel):
    category: str = Field(description="canon|character|state|plot|asset")
    severity: str = Field(description="critical|warning|info")
    location: str = Field(default="", description="Page/panel reference, e.g. 'page 2 panel 2-1'")
    description: str = Field(description="What is inconsistent")
    suggestion: str | None = Field(default=None, description="How to fix it")


class ConsistencyReport(BaseModel):
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    overall: str = Field(default="pass", description="pass|warning|fail")
