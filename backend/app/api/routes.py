"""API routes for Janam."""

from __future__ import annotations

import logging
import json
import hashlib
import hmac
import os
import re
from queue import Empty
import asyncio
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect

from ..core.security import require_read_api_key, require_write_api_key, require_ws_api_key, resolve_api_key_role
from ..core.request_context import reset_request_id, set_request_id
from ..repositories.report_repository import ReportRepository
from ..schemas import AlertEventResponse, HealthResponse, IngestEventRequest, LocationAnalyticsResponse, ReportRequest, StoredReportResponse
from ..services.analysis_service import JanamAnalysisService
from ..services.alert_stream_service import AlertStreamService


router = APIRouter()
logger = logging.getLogger("janam.api.routes")

_SENSITIVE_TEXT_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[redacted-email]"),
    (re.compile(r"\+?\d[\d\s().-]{7,}\d"), "[redacted-phone]"),
]

_SENSITIVE_PAYLOAD_KEYS = {
    "email",
    "mail",
    "phone",
    "mobile",
    "msisdn",
    "sender",
    "sender_id",
    "author",
    "from",
    "name",
    "first_name",
    "last_name",
    "address",
    "ip",
}


def _extract_init_request_id(message: str) -> str | None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("event") != "init":
        return None

    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        return request_id.strip()
    return None


def _infer_upload_report_type(upload: UploadFile) -> str:
    content_type = (upload.content_type or "").lower()
    filename = (upload.filename or "").lower()

    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("text/"):
        return "text"

    if filename.endswith((".wav", ".mp3", ".m4a", ".ogg", ".flac")):
        return "audio"
    if filename.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
        return "image"
    if filename.endswith((".txt", ".md", ".rtf", ".json")):
        return "text"

    return "text"


def _build_ingest_report_text(payload: IngestEventRequest) -> str:
    text = (payload.message_text or "").strip()
    if text:
        return text

    if payload.media_url:
        return f"Incoming {payload.media_type} evidence from {payload.platform}."

    raise ValueError("Ingest event requires either message_text or media_url")


def _pick_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _anonymization_enabled() -> bool:
    return os.getenv("JANAM_ANONYMIZE_INGEST", "true").strip().lower() not in {"0", "false", "no"}


def _anonymization_salt() -> str:
    configured = os.getenv("JANAM_ANONYMIZATION_SALT", "").strip()
    if configured:
        return configured
    return os.getenv("JANAM_WRITE_API_KEY", "janam-anon-fallback")


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(f"{_anonymization_salt()}:{value}".encode("utf-8")).hexdigest()
    return digest[:24]


def _scrub_text(text: str) -> str:
    scrubbed = text
    for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
        scrubbed = pattern.sub(replacement, scrubbed)
    return scrubbed


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).strip().lower()
            if key_lower in _SENSITIVE_PAYLOAD_KEYS:
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _sanitize_payload(value)
        return cleaned
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, str):
        return _scrub_text(payload)
    return payload


def _coarsen_coordinate(value: float | None) -> float | None:
    if value is None:
        return None
    decimals = int(os.getenv("JANAM_GPS_ROUND_DECIMALS", "3"))
    return round(value, max(0, min(decimals, 6)))


def _store_raw_payload_for_ingest() -> bool:
    return os.getenv("JANAM_STORE_INGEST_RAW_PAYLOAD", "false").strip().lower() in {"1", "true", "yes"}


def _normalize_n8n_payload(raw_payload: dict[str, Any]) -> IngestEventRequest:
    text_value = _pick_value(raw_payload, ("message_text", "messageText", "text", "message", "body", "content"))
    media_type_value = _pick_value(raw_payload, ("media_type", "mediaType", "type")) or "text"
    media_url_value = _pick_value(raw_payload, ("media_url", "mediaUrl", "url", "attachmentUrl"))
    platform_value = _pick_value(raw_payload, ("platform", "source", "provider")) or "n8n"
    channel_value = _pick_value(raw_payload, ("channel_id", "channelId", "chat_id", "chatId", "conversationId"))
    sender_value = _pick_value(raw_payload, ("sender_id", "senderId", "from", "author", "userId"))
    location_value = _pick_value(raw_payload, ("location", "place", "address"))
    latitude_value = _pick_value(raw_payload, ("latitude", "lat", "gps_lat"))
    longitude_value = _pick_value(raw_payload, ("longitude", "lng", "lon", "gps_lon"))
    external_id_value = _pick_value(raw_payload, ("external_event_id", "externalEventId", "message_id", "messageId", "eventId"))

    try:
        latitude_float = float(latitude_value) if latitude_value is not None else None
    except (TypeError, ValueError):
        latitude_float = None

    try:
        longitude_float = float(longitude_value) if longitude_value is not None else None
    except (TypeError, ValueError):
        longitude_float = None

    return IngestEventRequest(
        platform=str(platform_value).strip() or "n8n",
        channel_id=str(channel_value).strip() if isinstance(channel_value, str) else None,
        sender_id=str(sender_value).strip() if isinstance(sender_value, str) else None,
        message_text=str(text_value).strip() if isinstance(text_value, str) else None,
        media_type=str(media_type_value).strip().lower() if isinstance(media_type_value, str) else "text",
        media_url=str(media_url_value).strip() if isinstance(media_url_value, str) else None,
        source=str(platform_value).strip() if isinstance(platform_value, str) else "n8n",
        location=str(location_value).strip() if isinstance(location_value, str) else None,
        latitude=latitude_float,
        longitude=longitude_float,
        external_event_id=str(external_id_value).strip() if isinstance(external_id_value, str) else None,
        raw_payload=raw_payload,
        anonymous_mode=True,
    )


def _store_and_alert_from_ingest(
    payload: IngestEventRequest,
    *,
    service: JanamAnalysisService,
    alert_stream: AlertStreamService,
) -> StoredReportResponse:
    should_anonymize = payload.anonymous_mode and _anonymization_enabled()

    report_text = _build_ingest_report_text(payload)
    if should_anonymize:
        report_text = _scrub_text(report_text)

    normalized_source = payload.source or ":".join(part for part in [payload.platform.strip(), payload.channel_id] if part)
    if not normalized_source:
        normalized_source = payload.platform.strip()

    if should_anonymize:
        normalized_source = f"{payload.platform.strip()}:anonymous"

    ingest_metadata: dict[str, Any] = {
        "platform": payload.platform,
        "media_type": payload.media_type,
        "media_url": payload.media_url,
        "anonymous_mode": should_anonymize,
    }

    if should_anonymize:
        ingest_metadata["channel_fingerprint"] = _fingerprint(payload.channel_id)
        ingest_metadata["sender_fingerprint"] = _fingerprint(payload.sender_id)
        ingest_metadata["external_event_fingerprint"] = _fingerprint(payload.external_event_id)
        if _store_raw_payload_for_ingest() and payload.raw_payload is not None:
            ingest_metadata["raw_payload"] = _sanitize_payload(payload.raw_payload)
    else:
        ingest_metadata["channel_id"] = payload.channel_id
        ingest_metadata["sender_id"] = payload.sender_id
        ingest_metadata["external_event_id"] = payload.external_event_id
        ingest_metadata["raw_payload"] = payload.raw_payload

    record = service.analyze_and_store(
        report=report_text,
        report_type=payload.media_type,
        source=normalized_source,
        location=payload.location,
        latitude=_coarsen_coordinate(payload.latitude) if should_anonymize else payload.latitude,
        longitude=_coarsen_coordinate(payload.longitude) if should_anonymize else payload.longitude,
        extraction_metadata={
            "ingest": ingest_metadata
        },
    )

    severity = str(record.analysis.get("severity", "low"))
    if severity in {"medium", "high"}:
        alert = alert_stream.build_alert(
            report_id=record.id,
            severity=severity,
            danger_zone=str(record.analysis.get("danger_zone", "unknown")),
            summary=str(record.analysis.get("summary", "No summary available.")),
            source=record.source,
            location=record.location,
            latitude=record.latitude,
            longitude=record.longitude,
        )
        alert_stream.publish(alert)

    return StoredReportResponse(**record.to_dict())


def _verify_n8n_webhook_signature(*, request: Request, raw_body: bytes) -> None:
    secret = os.getenv("JANAM_N8N_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="n8n webhook signing is not configured")

    timestamp_header = request.headers.get("X-Janam-Webhook-Timestamp")
    signature_header = request.headers.get("X-Janam-Webhook-Signature")
    if not timestamp_header or not signature_header:
        raise HTTPException(status_code=401, detail="Missing webhook signature headers")

    try:
        timestamp_value = int(timestamp_header)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp") from exc

    max_skew = int(os.getenv("JANAM_N8N_WEBHOOK_MAX_SKEW_SECONDS", "300"))
    if abs(int(time.time()) - timestamp_value) > max_skew:
        raise HTTPException(status_code=401, detail="Webhook timestamp is outside allowed skew")

    candidate = signature_header.strip()
    if candidate.startswith("sha256="):
        candidate = candidate.split("=", 1)[1]

    signed_payload = f"{timestamp_header}.".encode("utf-8") + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(candidate, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def get_analysis_service(request: Request) -> JanamAnalysisService:
    return request.app.state.analysis_service


def get_alert_stream_service(request: Request) -> AlertStreamService:
    return request.app.state.alert_stream_service


@router.get("/", response_model=dict[str, str])
def root() -> dict[str, str]:
    return {"message": "Janam prototype API is running."}


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="janam-prototype")


@router.get("/formats", response_model=dict[str, list[str]])
def formats(
    service: JanamAnalysisService = Depends(get_analysis_service),
    _auth: None = Depends(require_read_api_key),
) -> dict[str, list[str]]:
    return {"supported_formats": service.supported_formats}


@router.post("/reports/analyze", response_model=StoredReportResponse)
def analyze_report(
    payload: ReportRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    logger.info("POST /reports/analyze type=%s source=%s location=%s", payload.report_type, payload.source, payload.location)
    try:
        record = service.analyze_and_store(
            report=payload.report,
            report_type=payload.report_type,
            source=payload.source,
            location=payload.location,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    except ValueError as exc:
        logger.warning("Invalid analyze request detail=%s", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    severity = str(record.analysis.get("severity", "low"))
    if severity in {"medium", "high"}:
        alert = alert_stream.build_alert(
            report_id=record.id,
            severity=severity,
            danger_zone=str(record.analysis.get("danger_zone", "unknown")),
            summary=str(record.analysis.get("summary", "No summary available.")),
            source=record.source,
            location=record.location,
            latitude=record.latitude,
            longitude=record.longitude,
        )
        alert_stream.publish(alert)
        logger.info("Alert published event_id=%s report_id=%s severity=%s", alert["event_id"], record.id, severity)

    return StoredReportResponse(**record.to_dict())


@router.post("/reports/text", response_model=StoredReportResponse)
def analyze_text(
    payload: ReportRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    payload.report_type = "text"
    return analyze_report(payload, service, alert_stream, _auth)


@router.post("/reports/audio", response_model=StoredReportResponse)
def analyze_audio(
    payload: ReportRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    payload.report_type = "audio"
    return analyze_report(payload, service, alert_stream, _auth)


@router.post("/reports/video", response_model=StoredReportResponse)
def analyze_video(
    payload: ReportRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    payload.report_type = "video"
    return analyze_report(payload, service, alert_stream, _auth)


@router.post("/reports/image", response_model=StoredReportResponse)
def analyze_image(
    payload: ReportRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    payload.report_type = "image"
    return analyze_report(payload, service, alert_stream, _auth)


@router.post("/reports/upload", response_model=StoredReportResponse)
async def upload_report(
    file: UploadFile = File(...),
    source: str | None = Form(default=None),
    location: str | None = Form(default=None),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    note: str | None = Form(default=None),
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    report_type = _infer_upload_report_type(file)
    report_text = (note or "").strip() or f"Uploaded {report_type} file: {file.filename or 'unnamed-file'}"

    record = service.analyze_and_store(
        report=report_text,
        report_type=report_type,
        source=source,
        location=location,
        latitude=latitude,
        longitude=longitude,
        extraction_metadata={
            "upload": {
                "filename": file.filename,
                "content_type": file.content_type,
                "size_bytes": len(file_bytes),
                "ingest_mode": "multipart-upload",
            }
        },
    )

    severity = str(record.analysis.get("severity", "low"))
    if severity in {"medium", "high"}:
        alert = alert_stream.build_alert(
            report_id=record.id,
            severity=severity,
            danger_zone=str(record.analysis.get("danger_zone", "unknown")),
            summary=str(record.analysis.get("summary", "No summary available.")),
            source=record.source,
            location=record.location,
            latitude=record.latitude,
            longitude=record.longitude,
        )
        alert_stream.publish(alert)

    return StoredReportResponse(**record.to_dict())


@router.post("/ingest/events", response_model=StoredReportResponse)
def ingest_event(
    payload: IngestEventRequest,
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    logger.info("POST /ingest/events platform=%s media_type=%s", payload.platform, payload.media_type)
    try:
        return _store_and_alert_from_ingest(payload, service=service, alert_stream=alert_stream)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@router.post("/ingest/n8n", response_model=StoredReportResponse)
async def ingest_n8n_event(
    request: Request,
    payload: dict[str, Any],
    service: JanamAnalysisService = Depends(get_analysis_service),
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_write_api_key),
) -> StoredReportResponse:
    logger.info("POST /ingest/n8n")
    try:
        raw_body = await request.body()
        _verify_n8n_webhook_signature(request=request, raw_body=raw_body)
        normalized = _normalize_n8n_payload(payload)
        return _store_and_alert_from_ingest(normalized, service=service, alert_stream=alert_stream)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/alerts", response_model=list[AlertEventResponse])
def list_alerts(
    limit: int = 25,
    alert_stream: AlertStreamService = Depends(get_alert_stream_service),
    _auth: None = Depends(require_read_api_key),
) -> list[AlertEventResponse]:
    logger.info("GET /alerts limit=%s", limit)
    return [AlertEventResponse(**event) for event in alert_stream.recent(limit=limit)]


@router.get("/reports", response_model=list[StoredReportResponse])
def list_reports(
    limit: int = 25,
    service: JanamAnalysisService = Depends(get_analysis_service),
    _auth: None = Depends(require_read_api_key),
) -> list[StoredReportResponse]:
    logger.info("GET /reports limit=%s", limit)
    return [StoredReportResponse(**record.to_dict()) for record in service.list_reports(limit=limit)]


@router.get("/analytics/locations", response_model=list[LocationAnalyticsResponse])
def location_analytics(
    limit: int = 5000,
    _auth: None = Depends(require_read_api_key),
) -> list[LocationAnalyticsResponse]:
    safe_limit = max(1, min(limit, 20000))
    repository = ReportRepository()
    aggregated = repository.location_analytics(limit=safe_limit)
    return [LocationAnalyticsResponse(**item) for item in aggregated]


@router.get("/reports/search", response_model=list[StoredReportResponse])
def search_reports(
    q: str | None = None,
    report_type: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    location: str | None = None,
    limit: int = 25,
    service: JanamAnalysisService = Depends(get_analysis_service),
    _auth: None = Depends(require_read_api_key),
) -> list[StoredReportResponse]:
    safe_limit = max(1, min(limit, 200))
    logger.info(
        "GET /reports/search q=%s report_type=%s severity=%s source=%s location=%s limit=%s",
        q,
        report_type,
        severity,
        source,
        location,
        safe_limit,
    )
    records = service.search_reports(
        query=q,
        report_type=report_type,
        severity=severity,
        source=source,
        location=location,
        limit=safe_limit,
    )
    return [StoredReportResponse(**record.to_dict()) for record in records]


@router.get("/reports/{report_id}", response_model=StoredReportResponse)
def get_report(
    report_id: int,
    service: JanamAnalysisService = Depends(get_analysis_service),
    _auth: None = Depends(require_read_api_key),
) -> StoredReportResponse:
    logger.info("GET /reports/%s", report_id)
    record = service.get_report(report_id)
    if record is None:
        logger.warning("Report not found id=%s", report_id)
        raise HTTPException(status_code=404, detail="Report not found")
    return StoredReportResponse(**record.to_dict())


@router.websocket("/ws/updates")
async def realtime_updates(websocket: WebSocket) -> None:
    if not await require_ws_api_key(websocket, required_role="write"):
        return

    ws_role = resolve_api_key_role(websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key"))
    limiter = websocket.app.state.rate_limiter_write if ws_role == "write" else websocket.app.state.rate_limiter_read
    client_host = websocket.client.host if websocket.client else "unknown"
    ws_key = f"ws:{client_host}:/ws/updates:{ws_role or 'anonymous'}"
    allowed, remaining, reset_in = limiter.consume_with_info(ws_key)
    if not allowed:
        logger.warning("rate_limit_exceeded ws=/ws/updates role=%s", ws_role or "anonymous")
        await websocket.close(code=1013)
        return

    service = JanamAnalysisService()
    current_request_id = websocket.query_params.get("request_id") or str(uuid4())
    token = set_request_id(current_request_id)
    await websocket.accept()
    await websocket.send_json(
        {
            "event": "connected",
            "request_id": current_request_id,
            "rate_limit": {
                "limit": limiter.limit,
                "remaining": remaining,
                "reset_in_seconds": reset_in,
                "role": ws_role or "anonymous",
            },
        }
    )
    logger.info("Websocket connected endpoint=/ws/updates")
    try:
        while True:
            message = await websocket.receive_text()

            handshake_request_id = _extract_init_request_id(message)
            if handshake_request_id:
                reset_request_id(token)
                current_request_id = handshake_request_id
                token = set_request_id(current_request_id)
                await websocket.send_json({"event": "correlation_updated", "request_id": current_request_id})
                logger.info("Websocket correlation updated endpoint=/ws/updates")
                continue

            try:
                analysis = service.analyze(message, "text")
                await websocket.send_json({"event": "analysis", "analysis": analysis["analysis"]})
            except Exception as exc:  # pragma: no cover - websocket safety net
                logger.exception("Websocket analysis error")
                await websocket.send_json({"event": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        logger.info("Websocket disconnected endpoint=/ws/updates")
        return
    finally:
        reset_request_id(token)


# websocket router
@router.websocket("/ws/alerts")
async def alert_stream(websocket: WebSocket) -> None:
    if not await require_ws_api_key(websocket, required_role="read"):
        return

    ws_role = resolve_api_key_role(websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key"))
    limiter = websocket.app.state.rate_limiter_write if ws_role == "write" else websocket.app.state.rate_limiter_read
    client_host = websocket.client.host if websocket.client else "unknown"
    ws_key = f"ws:{client_host}:/ws/alerts:{ws_role or 'anonymous'}"
    allowed, remaining, reset_in = limiter.consume_with_info(ws_key)
    if not allowed:
        logger.warning("rate_limit_exceeded ws=/ws/alerts role=%s", ws_role or "anonymous")
        await websocket.close(code=1013)
        return

    current_request_id = websocket.query_params.get("request_id") or str(uuid4())
    token = set_request_id(current_request_id)
    await websocket.accept()
    alert_service = websocket.app.state.alert_stream_service
    queue = alert_service.subscribe()
    await websocket.send_json(
        {
            "event": "connected",
            "request_id": current_request_id,
            "rate_limit": {
                "limit": limiter.limit,
                "remaining": remaining,
                "reset_in_seconds": reset_in,
                "role": ws_role or "anonymous",
            },
        }
    )

    try:
        init_message = await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
        handshake_request_id = _extract_init_request_id(init_message)
        if handshake_request_id:
            reset_request_id(token)
            current_request_id = handshake_request_id
            token = set_request_id(current_request_id)
            await websocket.send_json({"event": "correlation_updated", "request_id": current_request_id})
            logger.info("Websocket correlation updated endpoint=/ws/alerts")
    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        logger.info("Websocket disconnected endpoint=/ws/alerts")
        alert_service.unsubscribe(queue)
        reset_request_id(token)
        return

    logger.info("Websocket connected endpoint=/ws/alerts")
    try:
        while True:
            try:
                event = queue.get_nowait()
                await websocket.send_json(event)
            except Empty:
                await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.info("Websocket disconnected endpoint=/ws/alerts")
    finally:
        alert_service.unsubscribe(queue)
        reset_request_id(token)


@router.websocket("/ws/cases")
async def case_stream(websocket: WebSocket) -> None:
    if not await require_ws_api_key(websocket, required_role="read"):
        return

    ws_role = resolve_api_key_role(websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key"))
    limiter = websocket.app.state.rate_limiter_write if ws_role == "write" else websocket.app.state.rate_limiter_read
    client_host = websocket.client.host if websocket.client else "unknown"
    ws_key = f"ws:{client_host}:/ws/cases:{ws_role or 'anonymous'}"
    allowed, remaining, reset_in = limiter.consume_with_info(ws_key)
    if not allowed:
        logger.warning("rate_limit_exceeded ws=/ws/cases role=%s", ws_role or "anonymous")
        await websocket.close(code=1013)
        return

    current_request_id = websocket.query_params.get("request_id") or str(uuid4())
    token = set_request_id(current_request_id)
    await websocket.accept()
    await websocket.send_json(
        {
            "event": "connected",
            "request_id": current_request_id,
            "rate_limit": {
                "limit": limiter.limit,
                "remaining": remaining,
                "reset_in_seconds": reset_in,
                "role": ws_role or "anonymous",
            },
        }
    )

    repository = ReportRepository()
    last_seen = 0
    logger.info("Websocket connected endpoint=/ws/cases")
    try:
        while True:
            new_reports = repository.list_reports_since(last_seen, limit=100)
            for report in new_reports:
                await websocket.send_json({"event": "case", "report": report.to_dict()})
                if report.id > last_seen:
                    last_seen = report.id

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        logger.info("Websocket disconnected endpoint=/ws/cases")
    finally:
        reset_request_id(token)
