"""API routes for Janam."""

from __future__ import annotations

import logging
import json
from queue import Empty
import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

from ..core.security import require_read_api_key, require_write_api_key, require_ws_api_key, resolve_api_key_role
from ..core.request_context import reset_request_id, set_request_id
from ..schemas import AlertEventResponse, HealthResponse, ReportRequest, StoredReportResponse
from ..services.analysis_service import JanamAnalysisService
from ..services.alert_stream_service import AlertStreamService


router = APIRouter()
logger = logging.getLogger("janam.api.routes")


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
