"""Screenshot and Accessibility snapshot capture helpers."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from playwright.async_api import Page
from src.agent.observer import observe_surface
from src.guardrails.redactor import redact_data


async def capture_evidence_artifacts(
    page: Page,
    evidence_dir: str | Path,
    prefix: str = "step",
) -> dict[str, str]:
    """Captures screenshot and a11y JSON tree to the specified evidence folder."""
    target_dir = Path(evidence_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "screenshots").mkdir(exist_ok=True)

    screenshot_file = target_dir / "screenshots" / f"{prefix}.png"
    a11y_file = target_dir / f"{prefix}_a11y.json"

    # Screenshot
    try:
        await page.screenshot(path=str(screenshot_file), full_page=False)
    except Exception as e:
        print(f"[Evidence] Warning capturing screenshot: {e}")

    # A11y snapshot
    try:
        obs = await observe_surface(page)
        with open(a11y_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(redact_data(obs), indent=2))
    except Exception as e:
        print(f"[Evidence] Warning capturing a11y snapshot: {e}")

    return {
        "screenshot": str(screenshot_file),
        "a11y": str(a11y_file),
    }
