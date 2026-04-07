"""Logging configuration for Janam."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import traceback

from .request_context import get_request_id


def _default_log_path() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "logs" / "janam.log"


def get_log_path() -> Path:
    configured = os.getenv("JANAM_LOG_PATH")
    return Path(configured) if configured else _default_log_path()


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info)).strip()

        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    janam_handlers = [handler for handler in root_logger.handlers if getattr(handler, "_janam_handler", False)]
    for handler in janam_handlers:
        root_logger.removeHandler(handler)
        handler.close()

    formatter = JsonLogFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    setattr(console_handler, "_janam_handler", True)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    setattr(file_handler, "_janam_handler", True)
    root_logger.addHandler(file_handler)

    logging.getLogger("janam").info("Logging configured. file=%s", log_path)
