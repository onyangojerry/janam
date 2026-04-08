"""Core analysis logic for Janam."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any


class JanamBrain:
    def __init__(self, report_format: str = "text"):
        self.report_format = report_format
        self.formats = {"text", "audio", "image", "video"}

    def _normalize_report(self, report: str) -> str:
        return re.sub(r"\s+", " ", report.strip()).lower()

    def _keyword_hits(self, report: str, keywords: set[str]) -> list[str]:
        normalized = self._normalize_report(report)
        hits: list[str] = []
        for keyword in keywords:
            pattern = rf"\b{re.escape(keyword)}\b"
            if re.search(pattern, normalized):
                hits.append(keyword)
        return hits

    def extraction_tool(self, report: str, report_type: str) -> dict[str, Any]:
        if report_type not in self.formats:
            raise ValueError(f"Unsupported report type: {report_type}")

        normalized_report = self._normalize_report(report)
        payload: dict[str, Any] = {
            "report_type": report_type,
            "raw_report": report,
            "normalized_report": normalized_report,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

        if report_type == "audio":
            payload["source_hint"] = "audio-transcript-prototype"
        elif report_type == "image":
            payload["source_hint"] = "image-caption-prototype"
        elif report_type == "video":
            payload["source_hint"] = "video-description-prototype"
        else:
            payload["source_hint"] = "text-prototype"

        return payload

    def info_extractor(self, report: str, report_type: str) -> dict[str, Any]:
        return self.extraction_tool(report, report_type)

    def report_analysis_tool(self, extracted_report: dict[str, Any]) -> dict[str, Any]:
        report_text = extracted_report.get("normalized_report", "")

        crime_categories = {
            "violence": {"attack", "fight", "assault", "shooting", "stab", "violent"},
            "theft": {"theft", "steal", "stolen", "robbery", "robbed", "burglary"},
            "harassment": {"harass", "stalking", "threat", "abuse", "bully"},
            "weapon": {"gun", "firearm", "knife", "weapon", "bomb"},
            "property_damage": {"vandalism", "damage", "arson", "fire", "graffiti"},
            "fraud": {"fraud", "scam", "forgery", "identity theft", "fake"},
        }

        detected_categories: list[str] = []
        detected_keywords: list[str] = []

        for category, keywords in crime_categories.items():
            hits = self._keyword_hits(report_text, keywords)
            if hits:
                detected_categories.append(category)
                detected_keywords.extend(hits)

        keyword_counter = Counter(detected_keywords)
        risk_score = min(1.0, 0.15 + (0.2 * len(detected_categories)) + (0.05 * sum(keyword_counter.values())))

        high_risk_signals = {"violence", "weapon"}

        if risk_score >= 0.6 or high_risk_signals.issubset(set(detected_categories)):
            severity = "high"
            danger_zone = "red"
            next_steps = [
                "Escalate to emergency responders immediately.",
                "Preserve evidence and timestamps.",
                "Notify nearby users or operators in real time.",
            ]
        elif risk_score >= 0.45:
            severity = "medium"
            danger_zone = "amber"
            next_steps = [
                "Flag for human review.",
                "Increase local monitoring.",
                "Collect additional evidence or corroboration.",
            ]
        else:
            severity = "low"
            danger_zone = "green"
            next_steps = ["No immediate escalation required.", "Continue passive monitoring."]

        return {
            "analysis_type": "crime-risk-prototype",
            "risk_score": round(risk_score, 2),
            "severity": severity,
            "danger_zone": danger_zone,
            "detected_categories": detected_categories,
            "detected_keywords": sorted(set(detected_keywords)),
            "summary": self._build_summary(detected_categories, severity),
            "next_steps": next_steps,
            "source": extracted_report.get("report_type", self.report_format),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(self, detected_categories: list[str], severity: str) -> str:
        if not detected_categories:
            return "No clear crime indicators detected in the submitted report."
        categories = ", ".join(sorted(set(detected_categories)))
        return f"Potential {categories} indicators detected. Risk severity assessed as {severity}."

    def analyze_report(self, report: str, report_type: str) -> dict[str, Any]:
        extracted = self.info_extractor(report, report_type)
        analysis = self.report_analysis_tool(extracted)
        return {"extraction": extracted, "analysis": analysis}
