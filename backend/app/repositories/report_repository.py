"""Persistence layer for analyzed Janam reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from ..core.database import get_connection, is_postgres_backend, to_driver_sql


@dataclass(slots=True)
class StoredReport:
    id: int
    report: str
    report_type: str
    source: str | None
    location: str | None
    latitude: float | None
    longitude: float | None
    extraction: dict[str, Any]
    analysis: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report": self.report,
            "report_type": self.report_type,
            "source": self.source,
            "location": self.location,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "extraction": self.extraction,
            "analysis": self.analysis,
            "created_at": self.created_at,
        }


class ReportRepository:
    def create_report(
        self,
        *,
        report: str,
        report_type: str,
        source: str | None,
        location: str | None,
        latitude: float | None,
        longitude: float | None,
        extraction: dict[str, Any],
        analysis: dict[str, Any],
    ) -> StoredReport:
        created_at = datetime.now(timezone.utc).isoformat()
        with get_connection() as connection:
            insert_sql = to_driver_sql(
                """
                INSERT INTO reports (
                    report,
                    report_type,
                    source,
                    location,
                    latitude,
                    longitude,
                    extraction_json,
                    analysis_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            )
            values = (
                report,
                report_type,
                source,
                location,
                latitude,
                longitude,
                json.dumps(extraction),
                json.dumps(analysis),
                created_at,
            )

            if is_postgres_backend():
                cursor = connection.execute(insert_sql + " RETURNING id", values)
                report_id = int(cursor.fetchone()["id"])
            else:
                cursor = connection.execute(insert_sql, values)
                report_id = int(cursor.lastrowid)

            connection.commit()

        return StoredReport(
            id=report_id,
            report=report,
            report_type=report_type,
            source=source,
            location=location,
            latitude=latitude,
            longitude=longitude,
            extraction=extraction,
            analysis=analysis,
            created_at=created_at,
        )

    def get_report(self, report_id: int) -> StoredReport | None:
        with get_connection() as connection:
            row = connection.execute(to_driver_sql("SELECT * FROM reports WHERE id = ?"), (report_id,)).fetchone()

        if row is None:
            return None

        return StoredReport(
            id=row["id"],
            report=row["report"],
            report_type=row["report_type"],
            source=row["source"],
            location=row["location"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            extraction=json.loads(row["extraction_json"]),
            analysis=json.loads(row["analysis_json"]),
            created_at=row["created_at"],
        )

    def list_reports(self, limit: int = 25) -> list[StoredReport]:
        with get_connection() as connection:
            rows = connection.execute(
                to_driver_sql("SELECT * FROM reports ORDER BY id DESC LIMIT ?"),
                (limit,),
            ).fetchall()

        return [
            StoredReport(
                id=row["id"],
                report=row["report"],
                report_type=row["report_type"],
                source=row["source"],
                location=row["location"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                extraction=json.loads(row["extraction_json"]),
                analysis=json.loads(row["analysis_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def search_reports(
        self,
        *,
        query: str | None = None,
        report_type: str | None = None,
        severity: str | None = None,
        source: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[StoredReport]:
        sql = "SELECT * FROM reports"
        where_clauses: list[str] = []
        params: list[Any] = []

        if query:
            where_clauses.append("LOWER(report) LIKE ?")
            params.append(f"%{query.lower()}%")

        if report_type:
            where_clauses.append("report_type = ?")
            params.append(report_type)

        if source:
            where_clauses.append("LOWER(COALESCE(source, '')) LIKE ?")
            params.append(f"%{source.lower()}%")

        if location:
            where_clauses.append("LOWER(COALESCE(location, '')) LIKE ?")
            params.append(f"%{location.lower()}%")

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with get_connection() as connection:
            rows = connection.execute(to_driver_sql(sql), tuple(params)).fetchall()

        reports = [
            StoredReport(
                id=row["id"],
                report=row["report"],
                report_type=row["report_type"],
                source=row["source"],
                location=row["location"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                extraction=json.loads(row["extraction_json"]),
                analysis=json.loads(row["analysis_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

        if severity:
            severity_lower = severity.lower()
            reports = [report for report in reports if str(report.analysis.get("severity", "")).lower() == severity_lower]

        return reports

    def list_reports_since(self, report_id: int, limit: int = 100) -> list[StoredReport]:
        with get_connection() as connection:
            rows = connection.execute(
                to_driver_sql("SELECT * FROM reports WHERE id > ? ORDER BY id ASC LIMIT ?"),
                (report_id, limit),
            ).fetchall()

        return [
            StoredReport(
                id=row["id"],
                report=row["report"],
                report_type=row["report_type"],
                source=row["source"],
                location=row["location"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                extraction=json.loads(row["extraction_json"]),
                analysis=json.loads(row["analysis_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def location_analytics(self, limit: int = 5000) -> list[dict[str, Any]]:
        with get_connection() as connection:
            rows = connection.execute(
                to_driver_sql(
                    """
                    SELECT location, latitude, longitude, analysis_json, created_at
                    FROM reports
                    WHERE TRIM(COALESCE(location, '')) != ''
                    ORDER BY id DESC
                    LIMIT ?
                    """
                ),
                (limit,),
            ).fetchall()

        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            location = str(row["location"]).strip()
            if not location:
                continue

            severity = str(json.loads(row["analysis_json"]).get("severity", "low")).lower()
            if location not in grouped:
                grouped[location] = {
                    "location": location,
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "total_reports": 0,
                    "high_count": 0,
                    "medium_count": 0,
                    "low_count": 0,
                    "last_report_at": row["created_at"],
                }

            bucket = grouped[location]
            bucket["total_reports"] += 1
            if severity == "high":
                bucket["high_count"] += 1
            elif severity == "medium":
                bucket["medium_count"] += 1
            else:
                bucket["low_count"] += 1

            if row["created_at"] > bucket["last_report_at"]:
                bucket["last_report_at"] = row["created_at"]
            if bucket["latitude"] is None and row["latitude"] is not None:
                bucket["latitude"] = row["latitude"]
            if bucket["longitude"] is None and row["longitude"] is not None:
                bucket["longitude"] = row["longitude"]

        return sorted(grouped.values(), key=lambda item: (item["high_count"], item["total_reports"]), reverse=True)
