"""Request and response schemas for Janam."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReportType = Literal["text", "audio", "video"]


class ReportRequest(BaseModel):
    report: str = Field(..., min_length=1, description="The report content to analyze.")
    report_type: ReportType = Field(default="text", description="The type of report content.")
    source: str | None = Field(default=None, description="Optional source label.")
    location: str | None = Field(default=None, description="Optional location label.")


class HealthResponse(BaseModel):
    status: str
    service: str


class AnalysisResponse(BaseModel):
    request: dict[str, Any]
    result: dict[str, Any]


class StoredReportResponse(BaseModel):
    id: int
    report: str
    report_type: str
    source: str | None = None
    location: str | None = None
    extraction: dict[str, Any]
    analysis: dict[str, Any]
    created_at: str


class AlertEventResponse(BaseModel):
    event_id: str
    report_id: int
    severity: str
    danger_zone: str
    summary: str
    source: str | None = None
    location: str | None = None
    created_at: str
