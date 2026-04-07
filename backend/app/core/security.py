"""Security helpers for API key authentication."""

from __future__ import annotations

import hmac
import os
from typing import Literal

from fastapi import HTTPException, Request, WebSocket, status


Role = Literal["read", "write"]
DEFAULT_DEV_KEY = "janam-dev-key"


def get_api_key() -> str:
    return os.getenv("JANAM_API_KEY", DEFAULT_DEV_KEY)


def get_write_api_key() -> str:
    return os.getenv("JANAM_WRITE_API_KEY", get_api_key())


def get_read_api_key() -> str:
    return os.getenv("JANAM_READ_API_KEY", get_write_api_key())


def should_enforce_explicit_keys() -> bool:
    value = os.getenv("JANAM_ENFORCE_EXPLICIT_KEYS", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_valid_key_configuration() -> None:
    if not should_enforce_explicit_keys():
        return

    write_key = get_write_api_key().strip()
    read_key = get_read_api_key().strip()
    invalid = {
        "",
        DEFAULT_DEV_KEY,
    }
    if write_key in invalid or read_key in invalid:
        raise RuntimeError(
            "Invalid API key configuration: set JANAM_WRITE_API_KEY and JANAM_READ_API_KEY to non-default values."
        )


def verify_api_key(candidate: str | None) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, get_write_api_key()) or hmac.compare_digest(candidate, get_read_api_key())


def resolve_api_key_role(candidate: str | None) -> Role | None:
    if not candidate:
        return None
    if hmac.compare_digest(candidate, get_write_api_key()):
        return "write"
    if hmac.compare_digest(candidate, get_read_api_key()):
        return "read"
    return None


def require_read_api_key(request: Request) -> None:
    api_key = request.headers.get("X-API-Key")
    role = resolve_api_key_role(api_key)
    if role in {"read", "write"}:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )


def require_write_api_key(request: Request) -> None:
    api_key = request.headers.get("X-API-Key")
    role = resolve_api_key_role(api_key)
    if role == "write":
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )


async def require_ws_api_key(websocket: WebSocket, required_role: Role = "read") -> bool:
    api_key = websocket.query_params.get("api_key") or websocket.headers.get("X-API-Key")
    role = resolve_api_key_role(api_key)
    if role is None:
        await websocket.close(code=1008)
        return False

    if required_role == "read" and role in {"read", "write"}:
        return True
    if required_role == "write" and role == "write":
        return True

    await websocket.close(code=1008)
    return False
