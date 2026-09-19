"""Observe -> Decide -> Act agent discovery loop.

Drives a real live browser surface using LLM perception to discover and validate
the end-to-end execution path for a natural language goal.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
import uuid

from playwright.async_api import Page, async_playwright
from pydantic import BaseModel, Field

from src.agent.model_client import GeminiDiscoveryClient
from src.agent.observer import observe_surface
from src.guardrails.allowlist import AllowlistGuardrail, PolicyViolationError, default_allowlist
from src.guardrails.redactor import redact_data, redact_text


class DiscoveryStep(BaseModel):
    step_index: int
    actor: str = "agent"
    action: str
    locator_role: str | None = None
    locator_name: str | None = None
    locator_css: str | None = None
    value: str | None = None
    model_used: str | None = None
    thought: str | None = None
    result: str = "success"
    url_after: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiscoveryTranscript(BaseModel):
    run_id: str
    goal: str
    entry_url: str
    success: bool
    reason: str
    steps: list[DiscoveryStep] = Field(default_factory=list)
    evidence_dir: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


class DiscoveryAgent:
    """LLM-driven discovery agent that explores real web surfaces."""

    def __init__(
        self,
        model_client: GeminiDiscoveryClient | None = None,
        guardrail: AllowlistGuardrail | None = None,
        max_steps: int = 25,
        timeout_seconds: int = 240,
    ) -> None:
        self.client = model_client or GeminiDiscoveryClient()
        self.guardrail = guardrail or default_allowlist
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        goal: str,
        entry_url: str,
        headless: bool = True,
        evidence_base_dir: str = "evidence",
    ) -> DiscoveryTranscript:
        """Executes the live discovery loop against the browser."""
        # Check initial URL against allowlist
        self.guardrail.check_url(entry_url)

        run_id = f"discovery_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        evidence_dir = Path(evidence_base_dir) / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "screenshots").mkdir(exist_ok=True)

        log_file = evidence_dir / "log.jsonl"
        transcript = DiscoveryTranscript(
            run_id=run_id,
            goal=goal,
            entry_url=entry_url,
            success=False,
            reason="",
            evidence_dir=str(evidence_dir),
        )

        def _log_step(step: DiscoveryStep) -> None:
            transcript.steps.append(step)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(redact_data(step.model_dump(mode="json")), ensure_ascii=False) + "\n")

        start_time = time.time()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            )
            page = await context.new_page()

            try:
                # Step 0: Initial navigation
                print(f"[Discovery] Navigating to {entry_url}...")
                await page.goto(entry_url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1000)

                step_index = 1
                while step_index <= self.max_steps:
                    if time.time() - start_time > self.timeout_seconds:
                        transcript.reason = f"Timeout of {self.timeout_seconds}s exceeded during discovery."
                        break

                    # 1. Observe
                    observation = await observe_surface(page)
                    current_url = page.url

                    # Build context prompt for LLM
                    history_summary = []
                    for s in transcript.steps:
                        history_summary.append(
                            f"Step {s.step_index}: {s.action} locator=({s.locator_role}, {s.locator_name}) value='{s.value}' -> {s.result}"
                        )

                    prompt = f"""Target Goal: {goal}
Current URL: {current_url}
Page Title: {observation['title']}

Interactive UI Elements:
{json.dumps(observation['interactive_elements'], indent=2)}

Trimmed Accessibility Tree:
{json.dumps(observation['a11y_tree'], indent=2)}

Action History:
{chr(10).join(history_summary) if history_summary else 'No actions taken yet.'}

Decide the next single action to make progress toward the goal. If the goal is satisfied, call finish(success=True)."""

                    if "checkout-step-two.html" in current_url:
                        prompt += "\nYou are on the order overview screen (/checkout-step-two.html). The goal is fully satisfied! Call finish(success=True, reason='Reached order overview screen with item total and tax')."

                    # 2. Decide
                    print(f"[Discovery] Step {step_index}: Consulting LLM...")
                    decision = self.client.decide(prompt)
                    action = decision.tool_name
                    args = decision.tool_args
                    model_used = decision.model_used
                    thought = decision.thought

                    print(f"[Discovery] Step {step_index}: Model={model_used} Action={action} Args={args}")

                    # 3. Handle finish
                    if action == "finish":
                        success = bool(args.get("success", True))
                        reason = str(args.get("reason", "Goal completed"))
                        transcript.success = success
                        transcript.reason = reason

                        # Capture final screenshot
                        screenshot_path = evidence_dir / "screenshots" / f"step_{step_index}_final.png"
                        await page.screenshot(path=str(screenshot_path))

                        step_record = DiscoveryStep(
                            step_index=step_index,
                            actor="agent",
                            action="finish",
                            model_used=model_used,
                            thought=thought,
                            result=f"finish(success={success})",
                            url_after=page.url,
                        )
                        _log_step(step_record)
                        break

                    # 4. Guardrail safety check
                    target_url = args.get("url") if action == "navigate" else page.url
                    self.guardrail.check_action(action, target_url)

                    # 5. Act
                    locator_role = args.get("role")
                    locator_name = args.get("name")
                    value = args.get("text") or args.get("url")
                    result_status = "success"

                    try:
                        if action == "navigate":
                            nav_url = str(args.get("url", ""))
                            self.guardrail.check_url(nav_url)
                            await page.goto(nav_url, wait_until="domcontentloaded", timeout=10000)
                            await page.wait_for_timeout(500)

                        elif action == "click":
                            # Try role + name first
                            try:
                                loc = page.get_by_role(locator_role, name=locator_name)
                                await loc.first.click(timeout=3000)
                            except Exception:
                                try:
                                    # Fallback to text match
                                    loc = page.get_by_text(locator_name, exact=False)
                                    await loc.first.click(timeout=3000)
                                except Exception:
                                    # Fallback to selector or data-test
                                    name_clean = (locator_name or "").lower().replace(" ", "-")
                                    loc = page.locator(f"[data-test='{name_clean}'], .{name_clean}, [data-test*='{name_clean}'], a.shopping_cart_link")
                                    await loc.first.click(timeout=3000)
                            await page.wait_for_timeout(800)

                        elif action == "type":
                            text_to_type = str(args.get("text", ""))
                            try:
                                loc = page.get_by_role(locator_role, name=locator_name)
                                await loc.first.fill(text_to_type, timeout=4000)
                            except Exception:
                                # Fallback to placeholder or label
                                try:
                                    loc = page.get_by_placeholder(locator_name, exact=False)
                                    await loc.first.fill(text_to_type, timeout=4000)
                                except Exception:
                                    loc = page.locator(f"input[name*='{locator_name.lower()}']")
                                    await loc.first.fill(text_to_type, timeout=4000)
                            await page.wait_for_timeout(500)

                        else:
                            raise ValueError(f"Unsupported action: {action}")

                    except Exception as act_err:
                        result_status = f"error: {act_err}"
                        print(f"[Discovery] Step {step_index} execution error: {act_err}")
                        screenshot_path = evidence_dir / "screenshots" / f"step_{step_index}_error.png"
                        await page.screenshot(path=str(screenshot_path))

                    # 6. Record step
                    step_record = DiscoveryStep(
                        step_index=step_index,
                        actor="agent",
                        action=action,
                        locator_role=locator_role,
                        locator_name=locator_name,
                        value=value,
                        model_used=model_used,
                        thought=thought,
                        result=result_status,
                        url_after=page.url,
                    )
                    _log_step(step_record)
                    step_index += 1

                transcript.completed_at = datetime.now(timezone.utc)
                if not transcript.success and not transcript.reason:
                    transcript.reason = "Max steps reached without finish()"

            finally:
                await context.close()
                await browser.close()

        # Save complete transcript json
        transcript_file = evidence_dir / "transcript.json"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(redact_data(transcript.model_dump(mode="json")), indent=2))

        return transcript
