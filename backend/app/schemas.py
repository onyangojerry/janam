"""Request and response schemas for Janam."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ReportType = Literal["text", "audio", "image", "video"]
IngestMediaType = Literal["text", "audio", "image", "video"]


class ReportRequest(BaseModel):
    report: str = Field(..., min_length=1, description="The report content to analyze.")
    report_type: ReportType = Field(default="text", description="The type of report content.")
    source: str | None = Field(default=None, description="Optional source label.")
    location: str | None = Field(default=None, description="Optional location label.")
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Optional latitude from GPS.")
    longitude: float | None = Field(default=None, ge=-180, le=180, description="Optional longitude from GPS.")


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
    latitude: float | None = None
    longitude: float | None = None
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
    latitude: float | None = None
    longitude: float | None = None
    created_at: str


class LocationAnalyticsResponse(BaseModel):
    location: str
    latitude: float | None = None
    longitude: float | None = None
    total_reports: int
    high_count: int
    medium_count: int
    low_count: int
    last_report_at: str


class CaseStreamEventResponse(BaseModel):
    event: Literal["case"]
    report: StoredReportResponse


class IngestEventRequest(BaseModel):
    platform: str = Field(..., min_length=1, description="Upstream platform label, e.g. whatsapp/signal/matrix.")
    channel_id: str | None = Field(default=None, description="Conversation or channel identifier.")
    sender_id: str | None = Field(default=None, description="Sender/user identifier from upstream platform.")
    message_text: str | None = Field(default=None, description="Normalized text content from upstream payload.")
    media_type: IngestMediaType = Field(default="text", description="Media type represented by this event.")
    media_url: str | None = Field(default=None, description="Optional URL to media object from source system.")
    source: str | None = Field(default=None, description="Optional explicit source label override.")
    location: str | None = Field(default=None, description="Optional location label from connector.")
    latitude: float | None = Field(default=None, ge=-90, le=90, description="Optional latitude from connector.")
    longitude: float | None = Field(default=None, ge=-180, le=180, description="Optional longitude from connector.")
    external_event_id: str | None = Field(default=None, description="External event/message identifier.")
    raw_payload: dict[str, Any] | None = Field(default=None, description="Raw connector payload for traceability.")
    anonymous_mode: bool = Field(default=True, description="When true, identity fields are anonymized before persistence.")
