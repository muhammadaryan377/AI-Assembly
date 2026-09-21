from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class RuleInput(BaseModel):
    topic: str
    conditions: dict[str, Any] = Field(default_factory=dict)
    action: str
    rationale: str = ""
    source_quote: str = ""
    expert: str = "Unknown expert"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class GuidanceRequest(BaseModel):
    topic: str
    observations: dict[str, Any] = Field(default_factory=dict)


class ResolutionInput(BaseModel):
    conflict_id: str
    resolution: str
    differentiating_condition: str = ""
