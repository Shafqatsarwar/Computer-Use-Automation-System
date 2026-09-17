"""Structured evidence logger for Computer-Use Automation System.

Writes auditable JSONL execution logs per run with automatic secret & PII redaction.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from src.guardrails.redactor import redact_data


class EvidenceLogger:
    """Manages structured JSONL logs in the run evidence directory."""

    def __init__(self, run_id: str, base_dir: str = "evidence", extra_secrets: list[str] | None = None) -> None:
        self.run_id = run_id
        self.run_dir = Path(base_dir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.run_dir / "log.jsonl"
        self.extra_secrets = extra_secrets or []

    def log(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Appends a structured event object to log.jsonl with redaction applied."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **(data or {}),
        }
        clean_record = redact_data(record, extra_secrets=self.extra_secrets)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(clean_record, ensure_ascii=False) + "\n")
