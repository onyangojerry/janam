"""Service layer for Janam report analysis."""

from __future__ import annotations

import logging
from typing import Any

from ..core.brain import JanamBrain
from ..repositories.report_repository import ReportRepository, StoredReport


logger = logging.getLogger("janam.service.analysis")


class JanamAnalysisService:
    def __init__(self, brain: JanamBrain | None = None, repository: ReportRepository | None = None):
        self._brain = brain or JanamBrain(report_format="text")
        self._repository = repository or ReportRepository()

    @property
    def supported_formats(self) -> list[str]:
        return sorted(self._brain.formats)

    def analyze(self, report: str, report_type: str) -> dict[str, Any]:
        logger.info("Analyze report called type=%s length=%s", report_type, len(report))
        return self._brain.analyze_report(report, report_type)

    def analyze_and_store(
        self,
        *,
        report: str,
        report_type: str,
        source: str | None,
        location: str | None,
    ) -> StoredReport:
        result = self.analyze(report, report_type)
        stored = self._repository.create_report(
            report=report,
            report_type=report_type,
            source=source,
            location=location,
            extraction=result["extraction"],
            analysis=result["analysis"],
        )
        logger.info("Report persisted id=%s type=%s severity=%s", stored.id, stored.report_type, stored.analysis.get("severity"))
        return stored

    def get_report(self, report_id: int) -> StoredReport | None:
        record = self._repository.get_report(report_id)
        logger.info("Get report id=%s found=%s", report_id, record is not None)
        return record

    def list_reports(self, limit: int = 25) -> list[StoredReport]:
        records = self._repository.list_reports(limit=limit)
        logger.info("List reports limit=%s count=%s", limit, len(records))
        return records

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
        records = self._repository.search_reports(
            query=query,
            report_type=report_type,
            severity=severity,
            source=source,
            location=location,
            limit=limit,
        )
        logger.info(
            "Search reports query=%s report_type=%s severity=%s source=%s location=%s limit=%s count=%s",
            query,
            report_type,
            severity,
            source,
            location,
            limit,
            len(records),
        )
        return records
