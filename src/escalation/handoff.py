"""Live session human escalation and control handoff coordinator.

Enables seamless transition of control from automated agent/replay to a human operator
on the EXACT SAME live browser session, preserving state, cookies, and context.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from playwright.async_api import Page
from pydantic import BaseModel, Field

from src.agent.observer import observe_surface
from src.guardrails.redactor import redact_data


class HumanActionRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = "human"
    action: str
    target_role: str | None = None
    target_name: str | None = None
    value: str | None = None
    result: str = "success"
    url_after: str = ""


class EscalationSession:
    """Manages control transfer between automation and human operator."""

    def __init__(
        self,
        page: Page,
        reason: str,
        step_index: int | None = None,
        evidence_dir: str = "evidence/escalation",
    ) -> None:
        self.page = page
        self.reason = reason
        self.step_index = step_index
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.actions_taken: list[HumanActionRecord] = []
        self.is_paused = True
        self.log_file = self.evidence_dir / "escalation_log.jsonl"

    async def get_state_summary(self) -> dict[str, Any]:
        """Observes current state for the operator console."""
        obs = await observe_surface(self.page)
        screenshot_path = self.evidence_dir / f"handoff_step_{self.step_index or 0}.png"
        try:
            await self.page.screenshot(path=str(screenshot_path))
        except Exception:
            pass

        return {
            "reason": self.reason,
            "step_index": self.step_index,
            "url": self.page.url,
            "title": obs["title"],
            "interactive_elements": obs["interactive_elements"],
            "screenshot_path": str(screenshot_path),
        }

    async def execute_human_action(
        self,
        action: str,
        role: str | None = None,
        name: str | None = None,
        text: str | None = None,
        url: str | None = None,
    ) -> HumanActionRecord:
        """Applies a human operator action directly to the live browser session."""
        result_msg = "success"
        try:
            if action == "click":
                if role and name:
                    try:
                        loc = self.page.get_by_role(role, name=name)
                        await loc.first.click(timeout=3000)
                    except Exception:
                        loc = self.page.get_by_text(name, exact=False)
                        await loc.first.click(timeout=3000)
                elif name:
                    loc = self.page.get_by_text(name, exact=False)
                    await loc.first.click(timeout=3000)

            elif action == "type":
                if text is not None:
                    if role and name:
                        try:
                            loc = self.page.get_by_role(role, name=name)
                            await loc.first.fill(text, timeout=3000)
                        except Exception:
                            loc = self.page.get_by_placeholder(name, exact=False)
                            await loc.first.fill(text, timeout=3000)
                    elif name:
                        loc = self.page.locator(f"[name='{name}']")
                        await loc.first.fill(text, timeout=3000)

            elif action == "navigate":
                if url:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=10000)

            elif action == "wait":
                await self.page.wait_for_timeout(2000)

            else:
                result_msg = f"Unknown action: {action}"

        except Exception as e:
            result_msg = f"Error: {e}"

        record = HumanActionRecord(
            actor="human",
            action=action,
            target_role=role,
            target_name=name,
            value=text or url,
            result=result_msg,
            url_after=self.page.url,
        )
        self.actions_taken.append(record)

        # Audit log the human action
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(redact_data(record.model_dump(mode="json")), ensure_ascii=False) + "\n")

        return record

    def resume(self) -> None:
        """Signals resumption of automated control."""
        self.is_paused = False
