"""Realtime alert stream service."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from queue import Queue
import threading
from typing import Any
from uuid import uuid4


class AlertStreamService:
    def __init__(self, history_size: int = 100):
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._subscribers: set[Queue[dict[str, Any]]] = set()
        self._lock = threading.Lock()

    def build_alert(
        self,
        *,
        report_id: int,
        severity: str,
        danger_zone: str,
        summary: str,
        source: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        return {
            "event_id": str(uuid4()),
            "report_id": report_id,
            "severity": severity,
            "danger_zone": danger_zone,
            "summary": summary,
            "source": source,
            "location": location,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def publish(self, alert: dict[str, Any]) -> None:
        with self._lock:
            self._history.append(alert)
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            subscriber.put(alert)

    def subscribe(self) -> Queue[dict[str, Any]]:
        queue: Queue[dict[str, Any]] = Queue()
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            history = list(self._history)
        return history[-limit:]
