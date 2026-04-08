from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import json
import logging
import sqlite3
import time

from fastapi.testclient import TestClient

from backend.main import create_app


TEST_WRITE_API_KEY = "test-write-key"
TEST_READ_API_KEY = "test-read-key"
TEST_N8N_WEBHOOK_SECRET = "test-n8n-secret"


def _auth_headers(role: str = "write") -> dict[str, str]:
    key = TEST_WRITE_API_KEY if role == "write" else TEST_READ_API_KEY
    return {"X-API-Key": key}


def _set_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("JANAM_API_KEY", TEST_WRITE_API_KEY)
    monkeypatch.setenv("JANAM_WRITE_API_KEY", TEST_WRITE_API_KEY)
    monkeypatch.setenv("JANAM_READ_API_KEY", TEST_READ_API_KEY)


def _signed_n8n_headers(payload: dict[str, object], *, role: str = "write") -> dict[str, str]:
    serialized = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(
        TEST_N8N_WEBHOOK_SECRET.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + serialized,
        hashlib.sha256,
    ).hexdigest()
    headers = _auth_headers(role=role)
    headers["X-Janam-Webhook-Timestamp"] = timestamp
    headers["X-Janam-Webhook-Signature"] = f"sha256={signature}"
    return headers


def test_health_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "janam-prototype"}


def test_formats_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/formats", headers=_auth_headers(role="read"))
        assert response.status_code == 200
        assert response.json() == {"supported_formats": ["audio", "image", "text", "video"]}


def test_analyze_text_endpoint_persists_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/reports/text",
            json={
                "report": "There was a gun and a stabbing during the attack.",
                "report_type": "text",
                "source": "camera-1",
                "location": "zone-a",
                "latitude": 6.5244,
                "longitude": 3.3792,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["report_type"] == "text"
        assert payload["analysis"]["severity"] == "high"
        assert payload["analysis"]["danger_zone"] == "red"
        assert payload["source"] == "camera-1"
        assert payload["latitude"] == 6.5244
        assert payload["longitude"] == 3.3792

        report_id = payload["id"]
        fetch = client.get(f"/reports/{report_id}", headers=_auth_headers())
        assert fetch.status_code == 200
        assert fetch.json()["id"] == report_id
        assert fetch.json()["location"] == "zone-a"
        assert fetch.json()["latitude"] == 6.5244
        assert fetch.json()["longitude"] == 3.3792


def test_list_reports_returns_saved_entries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/reports/analyze",
            json={"report": "A theft happened near the market.", "report_type": "text"},
            headers=_auth_headers(),
        )
        response = client.get("/reports", headers=_auth_headers(role="read"))
        assert response.status_code == 200
        assert len(response.json()) == 1


def test_upload_endpoint_stores_media_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/reports/upload",
            headers=_auth_headers(),
            files={"file": ("street.jpg", b"fake-image-bytes", "image/jpeg")},
            data={
                "source": "citizen-phone",
                "location": "zone-c",
                "latitude": "6.5500",
                "longitude": "3.3500",
                "note": "Image shows suspicious behavior.",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["report_type"] == "image"
        assert payload["location"] == "zone-c"
        assert payload["latitude"] == 6.55
        assert payload["longitude"] == 3.35
        assert payload["extraction"]["upload"]["filename"] == "street.jpg"
        assert payload["extraction"]["upload"]["content_type"] == "image/jpeg"
        assert payload["extraction"]["upload"]["size_bytes"] == len(b"fake-image-bytes")


def test_ingest_event_from_connector_persists_and_alerts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/ingest/events",
            json={
                "platform": "whatsapp-bridge",
                "channel_id": "community-group-1",
                "sender_id": "user-88",
                "message_text": "Armed attack with gun near central station.",
                "media_type": "text",
                "location": "central-station",
                "latitude": 6.45,
                "longitude": 3.41,
                "external_event_id": "wa-msg-9988",
                "raw_payload": {"kind": "message", "priority": "urgent"},
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "whatsapp-bridge:anonymous"
        assert payload["analysis"]["severity"] == "high"
        assert payload["extraction"]["ingest"]["platform"] == "whatsapp-bridge"
        assert payload["extraction"]["ingest"]["anonymous_mode"] is True
        assert payload["extraction"]["ingest"]["external_event_fingerprint"] is not None
        assert payload["extraction"]["ingest"]["sender_fingerprint"] is not None
        assert payload["extraction"]["ingest"]["channel_fingerprint"] is not None
        assert payload["latitude"] == round(6.45, 3)
        assert payload["longitude"] == round(3.41, 3)

        alerts_response = client.get("/alerts", headers=_auth_headers(role="read"))
        assert alerts_response.status_code == 200
        alerts = alerts_response.json()
        assert any(event["report_id"] == payload["id"] for event in alerts)


def test_ingest_event_requires_text_or_media_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/ingest/events",
            json={"platform": "signal-bridge", "media_type": "audio"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400


def test_ingest_n8n_payload_normalization(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    monkeypatch.setenv("JANAM_N8N_WEBHOOK_SECRET", TEST_N8N_WEBHOOK_SECRET)
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "provider": "signal-bridge",
            "chatId": "community-alerts",
            "author": "user-11",
            "text": "Gun attack near junction.",
            "type": "text",
            "lat": "6.4501",
            "lng": "3.4202",
            "eventId": "sig-11",
        }
        response = client.post(
            "/ingest/n8n",
            json=payload,
            headers=_signed_n8n_headers(payload),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "signal-bridge:anonymous"
        assert payload["latitude"] == round(6.4501, 3)
        assert payload["longitude"] == round(3.4202, 3)
        assert payload["extraction"]["ingest"]["channel_fingerprint"] is not None
        assert payload["extraction"]["ingest"]["sender_fingerprint"] is not None
        assert payload["extraction"]["ingest"]["external_event_fingerprint"] is not None


def test_ingest_event_can_opt_out_of_anonymization(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/ingest/events",
            json={
                "platform": "matrix-bridge",
                "channel_id": "ops-room",
                "sender_id": "operator-1",
                "message_text": "Gun attack near station.",
                "media_type": "text",
                "anonymous_mode": False,
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "matrix-bridge:ops-room"
        assert payload["extraction"]["ingest"]["channel_id"] == "ops-room"
        assert payload["extraction"]["ingest"]["sender_id"] == "operator-1"


def test_ingest_n8n_rejects_invalid_signature(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    monkeypatch.setenv("JANAM_N8N_WEBHOOK_SECRET", TEST_N8N_WEBHOOK_SECRET)
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        payload = {"provider": "signal-bridge", "text": "Gun attack near junction.", "type": "text"}
        headers = _signed_n8n_headers(payload)
        headers["X-Janam-Webhook-Signature"] = "sha256=invalid"
        response = client.post("/ingest/n8n", json=payload, headers=headers)
        assert response.status_code == 401


def test_ingest_n8n_rejects_missing_signature_headers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    monkeypatch.setenv("JANAM_N8N_WEBHOOK_SECRET", TEST_N8N_WEBHOOK_SECRET)
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        payload = {"provider": "signal-bridge", "text": "Gun attack near junction.", "type": "text"}
        response = client.post("/ingest/n8n", json=payload, headers=_auth_headers())
        assert response.status_code == 401


def test_location_analytics_aggregates_by_location(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/reports/text",
            json={"report": "Gun attack with weapon.", "report_type": "text", "location": "zone-a", "latitude": 6.1, "longitude": 3.1},
            headers=_auth_headers(),
        )
        client.post(
            "/reports/text",
            json={"report": "Routine neighborhood patrol update.", "report_type": "text", "location": "zone-a", "latitude": 6.1001, "longitude": 3.1001},
            headers=_auth_headers(),
        )
        client.post(
            "/reports/text",
            json={"report": "Burglary reported at night.", "report_type": "text", "location": "zone-b"},
            headers=_auth_headers(),
        )

        response = client.get("/analytics/locations", headers=_auth_headers(role="read"))
        assert response.status_code == 200
        payload = response.json()
        zone_a = next((item for item in payload if item["location"] == "zone-a"), None)
        assert zone_a is not None
        assert zone_a["total_reports"] == 2
        assert zone_a["high_count"] >= 1
        assert zone_a["latitude"] is not None
        assert zone_a["longitude"] is not None


def test_logging_writes_to_file(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "janam.sqlite3"
    log_path = tmp_path / "janam.log"
    monkeypatch.setenv("JANAM_DB_PATH", str(db_path))
    monkeypatch.setenv("JANAM_LOG_PATH", str(log_path))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    for handler in logging.getLogger().handlers:
        flush = getattr(handler, "flush", None)
        if callable(flush):
            flush()

    assert log_path.exists()
    log_content = log_path.read_text(encoding="utf-8").strip()
    assert log_content != ""

    first_entry = json.loads(log_content.splitlines()[0])
    assert "timestamp" in first_entry
    assert "level" in first_entry
    assert "logger" in first_entry
    assert "message" in first_entry
    assert "request_id" in first_entry


def test_alerts_list_contains_high_risk_alert(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/reports/text",
            json={"report": "Gun attack and stabbing reported.", "report_type": "text", "location": "zone-1"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200

        alerts_response = client.get("/alerts", headers=_auth_headers(role="read"))
        assert alerts_response.status_code == 200
        alerts = alerts_response.json()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "high"
        assert alerts[0]["location"] == "zone-1"


def test_websocket_alert_stream_receives_alert_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/alerts?api_key={TEST_READ_API_KEY}") as websocket:
            connected = websocket.receive_json()
            assert connected["event"] == "connected"
            assert "request_id" in connected
            assert connected["rate_limit"]["role"] == "read"
            assert "limit" in connected["rate_limit"]
            assert "remaining" in connected["rate_limit"]
            assert "reset_in_seconds" in connected["rate_limit"]

            create_response = client.post(
                "/reports/analyze",
                json={"report": "There was an armed assault with a weapon.", "report_type": "text"},
                headers=_auth_headers(),
            )
            assert create_response.status_code == 200

            event = websocket.receive_json()
            assert event["severity"] == "high"
            assert event["report_id"] == create_response.json()["id"]


def test_websocket_case_stream_receives_new_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/cases?api_key={TEST_READ_API_KEY}") as websocket:
            connected = websocket.receive_json()
            assert connected["event"] == "connected"

            create_response = client.post(
                "/reports/analyze",
                json={"report": "Armed attack near station.", "report_type": "text", "location": "station"},
                headers=_auth_headers(),
            )
            assert create_response.status_code == 200

            event = websocket.receive_json()
            assert event["event"] == "case"
            assert event["report"]["id"] == create_response.json()["id"]


def test_report_search_by_query_and_location(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/reports/analyze",
            json={"report": "Burglary happened near central market.", "report_type": "text", "location": "market"},
            headers=_auth_headers(),
        )
        client.post(
            "/reports/analyze",
            json={"report": "Traffic congestion update.", "report_type": "text", "location": "highway"},
            headers=_auth_headers(),
        )

        response = client.get("/reports/search", params={"q": "burglary", "location": "market"}, headers=_auth_headers(role="read"))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert "Burglary" in data[0]["report"]


def test_report_search_by_severity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.post(
            "/reports/analyze",
            json={"report": "Armed attack with gun and stabbing.", "report_type": "text"},
            headers=_auth_headers(),
        )
        client.post(
            "/reports/analyze",
            json={"report": "Routine neighborhood update.", "report_type": "text"},
            headers=_auth_headers(),
        )

        response = client.get("/reports/search", params={"severity": "high"}, headers=_auth_headers(role="read"))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["analysis"]["severity"] == "high"


def test_reports_table_has_search_indexes(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "janam.sqlite3"
    monkeypatch.setenv("JANAM_DB_PATH", str(db_path))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("PRAGMA index_list('reports')").fetchall()

    index_names = {row[1] for row in rows}
    assert "idx_reports_report_type" in index_names
    assert "idx_reports_location" in index_names
    assert "idx_reports_source" in index_names
    assert "idx_reports_created_at" in index_names
    assert "idx_reports_lat_lon" in index_names


def test_request_id_header_and_log_correlation(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "janam.sqlite3"
    log_path = tmp_path / "janam.log"
    request_id = "trace-abc-123"
    monkeypatch.setenv("JANAM_DB_PATH", str(db_path))
    monkeypatch.setenv("JANAM_LOG_PATH", str(log_path))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": request_id})
        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == request_id

    for handler in logging.getLogger().handlers:
        flush = getattr(handler, "flush", None)
        if callable(flush):
            flush()

    log_content = log_path.read_text(encoding="utf-8").strip().splitlines()
    parsed = [json.loads(line) for line in log_content]
    assert any(entry.get("request_id") == request_id for entry in parsed)


def test_websocket_request_id_query_param_in_logs(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "janam.sqlite3"
    log_path = tmp_path / "janam.log"
    request_id = "ws-trace-999"
    monkeypatch.setenv("JANAM_DB_PATH", str(db_path))
    monkeypatch.setenv("JANAM_LOG_PATH", str(log_path))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/updates?request_id={request_id}&api_key={TEST_WRITE_API_KEY}") as websocket:
            connected = websocket.receive_json()
            assert connected["event"] == "connected"
            assert connected["request_id"] == request_id
            assert connected["rate_limit"]["role"] == "write"
            assert "limit" in connected["rate_limit"]
            assert "remaining" in connected["rate_limit"]
            assert "reset_in_seconds" in connected["rate_limit"]

            websocket.send_text("armed attack with a gun")
            response = websocket.receive_json()
            assert response["event"] == "analysis"

    for handler in logging.getLogger().handlers:
        flush = getattr(handler, "flush", None)
        if callable(flush):
            flush()

    log_content = log_path.read_text(encoding="utf-8").strip().splitlines()
    parsed = [json.loads(line) for line in log_content]
    assert any(entry.get("request_id") == request_id for entry in parsed)


def test_websocket_initial_handshake_request_id_in_logs(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "janam.sqlite3"
    log_path = tmp_path / "janam.log"
    request_id = "ws-init-555"
    monkeypatch.setenv("JANAM_DB_PATH", str(db_path))
    monkeypatch.setenv("JANAM_LOG_PATH", str(log_path))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/updates?api_key={TEST_WRITE_API_KEY}") as websocket:
            connected = websocket.receive_json()
            assert connected["event"] == "connected"

            websocket.send_text(json.dumps({"event": "init", "request_id": request_id}))
            updated = websocket.receive_json()
            assert updated == {"event": "correlation_updated", "request_id": request_id}

            websocket.send_text("armed attack with gun")
            analysis = websocket.receive_json()
            assert analysis["event"] == "analysis"

    for handler in logging.getLogger().handlers:
        flush = getattr(handler, "flush", None)
        if callable(flush):
            flush()

    log_content = log_path.read_text(encoding="utf-8").strip().splitlines()
    parsed = [json.loads(line) for line in log_content]
    assert any(entry.get("request_id") == request_id for entry in parsed)


def test_protected_endpoint_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/formats")
        assert response.status_code == 401


def test_rate_limit_returns_429(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("JANAM_RATE_LIMIT_WRITE_PER_MINUTE", "2")
    monkeypatch.setenv("JANAM_RATE_LIMIT_READ_PER_MINUTE", "2")

    app = create_app()
    with TestClient(app) as client:
        first = client.get("/formats", headers=_auth_headers())
        second = client.get("/formats", headers=_auth_headers())
        third = client.get("/formats", headers=_auth_headers())

        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        assert third.headers.get("X-RateLimit-Limit") == "2"
        assert third.headers.get("X-RateLimit-Remaining") == "0"
        assert third.headers.get("X-RateLimit-Role") == "write"


def test_success_responses_include_rate_limit_headers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("JANAM_RATE_LIMIT_READ_PER_MINUTE", "5")

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/formats", headers=_auth_headers(role="read"))
        assert response.status_code == 200
        assert response.headers.get("X-RateLimit-Limit") == "5"
        assert response.headers.get("X-RateLimit-Remaining") == "4"
        assert response.headers.get("X-RateLimit-Role") == "read"
        assert response.headers.get("X-RateLimit-Reset") is not None


def test_role_specific_retry_after_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("JANAM_RATE_LIMIT_READ_PER_MINUTE", "1")
    monkeypatch.setenv("JANAM_RATE_LIMIT_WRITE_PER_MINUTE", "1")
    monkeypatch.setenv("JANAM_RETRY_AFTER_READ_SECONDS", "12")
    monkeypatch.setenv("JANAM_RETRY_AFTER_WRITE_SECONDS", "34")

    app = create_app()
    with TestClient(app) as client:
        client.get("/reports", headers=_auth_headers(role="read"))
        read_limited = client.get("/reports", headers=_auth_headers(role="read"))
        assert read_limited.status_code == 429
        assert read_limited.headers.get("Retry-After") == "12"

        client.get("/reports", headers=_auth_headers(role="write"))
        write_limited = client.get("/reports", headers=_auth_headers(role="write"))
        assert write_limited.status_code == 429
        assert write_limited.headers.get("Retry-After") == "34"


def test_read_rate_limit_stricter_than_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("JANAM_RATE_LIMIT_READ_PER_MINUTE", "1")
    monkeypatch.setenv("JANAM_RATE_LIMIT_WRITE_PER_MINUTE", "3")

    app = create_app()
    with TestClient(app) as client:
        read_first = client.get("/reports", headers=_auth_headers(role="read"))
        read_second = client.get("/reports", headers=_auth_headers(role="read"))

        write_first = client.get("/reports", headers=_auth_headers(role="write"))
        write_second = client.get("/reports", headers=_auth_headers(role="write"))
        write_third = client.get("/reports", headers=_auth_headers(role="write"))

        assert read_first.status_code == 200
        assert read_second.status_code == 429
        assert write_first.status_code == 200
        assert write_second.status_code == 200
        assert write_third.status_code == 200


def test_read_key_cannot_write_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/reports/analyze",
            json={"report": "test", "report_type": "text"},
            headers=_auth_headers(role="read"),
        )
        assert response.status_code == 401


def test_write_key_can_access_read_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JANAM_DB_PATH", str(tmp_path / "janam.sqlite3"))
    _set_auth_env(monkeypatch)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/reports", headers=_auth_headers(role="write"))
        assert response.status_code == 200
