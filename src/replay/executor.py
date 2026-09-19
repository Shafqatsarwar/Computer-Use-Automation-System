"""Deterministic Replay Engine (NO LLM in the loop).

Executes a CapabilityArtifact deterministically against a live browser surface:
- Uses multi-strategy locators with explicit fallback chains
- Substitutes parameterized inputs
- Verifies step checkpoints and success conditions
- Evaluates runtime error taxonomy and business outcomes
- Emits structured ReplayResult and comprehensive audit evidence
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid
from dotenv import load_dotenv

load_dotenv()

from playwright.async_api import Page, async_playwright

from src.artifact.schema import CapabilityArtifact, ReplayResult, Step
from src.guardrails.allowlist import AllowlistGuardrail, PolicyViolationError, default_allowlist
from src.guardrails.redactor import redact_data, redact_text
from src.guardrails.risk import requires_approval_for_replay
from src.replay.locators import LocatorNotFoundError, resolve_locator
from src.replay.outcomes import check_known_outcomes


class ReplayEngine:
    """Production execution engine for registered capability artifacts."""

    def __init__(self, guardrail: AllowlistGuardrail | None = None) -> None:
        self.guardrail = guardrail or default_allowlist

    async def execute(
        self,
        artifact: CapabilityArtifact,
        params: dict[str, Any] | None = None,
        headless: bool = True,
        evidence_base_dir: str = "evidence",
        existing_page: Page | None = None,
        allow_draft_irreversible: bool = False,
    ) -> ReplayResult:
        """Runs the deterministic replay workflow."""
        run_params = dict(params or {})

        # 1. Validate required input parameters before browser launch
        # Checks run_params, then environment variables, then schema defaults
        for ip in artifact.input_params:
            if ip.name not in run_params:
                env_val = (
                    os.getenv(ip.name.upper())
                    or os.getenv(f"SAUCE_{ip.name.upper()}")
                    or os.getenv(f"SAUCEDEMO_{ip.name.upper()}")
                )
                if env_val:
                    run_params[ip.name] = env_val
                elif ip.default is not None:
                    run_params[ip.name] = ip.default
                elif ip.required:
                    return ReplayResult(
                        status="hard_failure",
                        outcome_code="INVALID_INPUT",
                        expected=f"Required parameter '{ip.name}'",
                        observed="Parameter missing from input dictionary and environment variables",
                        message=f"Missing required parameter: {ip.name}",
                    )

        # Setup evidence directory
        run_id = f"replay_{artifact.id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        evidence_dir = Path(evidence_base_dir) / run_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "screenshots").mkdir(exist_ok=True)
        log_file = evidence_dir / "log.jsonl"

        secret_values = [
            str(run_params[ip.name])
            for ip in artifact.input_params
            if ip.secret and ip.name in run_params
        ]

        def _log_event(event_dict: dict[str, Any]) -> None:
            safe_dict = redact_data(event_dict, extra_secrets=secret_values)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(safe_dict, ensure_ascii=False) + "\n")

        # Initial log
        _log_event({
            "event": "replay_start",
            "artifact_id": artifact.id,
            "version": artifact.version,
            "target_app": artifact.target_app,
            "params": run_params,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        async def _run_steps_on_page(page: Page) -> ReplayResult:
            step_idx = 1
            extracted_outputs: dict[str, Any] = {}

            # If browser starts at about:blank and artifact defines entry_url,
            # navigate if the first step is not an explicit navigation action.
            if page.url == "about:blank" and artifact.entry_url:
                first_action = artifact.steps[0].action if artifact.steps else None
                if first_action != "navigate":
                    self.guardrail.check_url(artifact.entry_url)
                    await page.goto(artifact.entry_url, wait_until="domcontentloaded", timeout=10000)
                    await page.wait_for_timeout(500)

            for step in artifact.steps:
                # Check policy for irreversible steps
                if requires_approval_for_replay(step.risk, artifact.status) and not allow_draft_irreversible:
                    _log_event({
                        "event": "blocked_irreversible_step",
                        "step_id": step.id,
                        "risk": step.risk,
                        "status": artifact.status,
                    })
                    return ReplayResult(
                        status="hard_failure",
                        outcome_code="APPROVAL_REQUIRED",
                        step_index=step_idx,
                        expected="Approved artifact status or explicit operator override",
                        observed=f"Step '{step.id}' is irreversible on '{artifact.status}' artifact",
                        evidence_path=str(evidence_dir),
                        message="Cannot execute irreversible action on draft artifact without approval",
                    )

                # Resolve parameter value if needed
                action_value = step.value_param
                if step.value_param and step.value_param in run_params:
                    action_value = str(run_params[step.value_param])

                # Check allowlist
                target_url = action_value if step.action == "navigate" else page.url
                try:
                    self.guardrail.check_action(step.action, target_url)
                except PolicyViolationError as pve:
                    _log_event({"event": "policy_violation", "step_id": step.id, "error": str(pve)})
                    return ReplayResult(
                        status="hard_failure",
                        outcome_code="POLICY_VIOLATION",
                        step_index=step_idx,
                        expected="Action allowed by safety policy",
                        observed=str(pve),
                        evidence_path=str(evidence_dir),
                        message=str(pve),
                    )

                # Execute step action
                try:
                    if step.action == "navigate":
                        nav_url = action_value or artifact.entry_url
                        self.guardrail.check_url(nav_url)
                        await page.goto(nav_url, wait_until="domcontentloaded", timeout=10000)
                        await page.wait_for_timeout(500)

                    elif step.action == "click":
                        element = await resolve_locator(page, step.locator, timeout_ms=3000)
                        if element is None:
                            raise LocatorNotFoundError(f"Could not locate element for click at step {step.id}")
                        await element.click(timeout=3000)
                        await page.wait_for_timeout(600)

                    elif step.action == "type":
                        element = await resolve_locator(page, step.locator, timeout_ms=3000)
                        if element is None:
                            raise LocatorNotFoundError(f"Could not locate input field for typing at step {step.id}")
                        await element.fill(action_value or "", timeout=3000)
                        await page.wait_for_timeout(400)

                    elif step.action == "wait_for":
                        await page.wait_for_timeout(1000)

                    elif step.action == "read":
                        if step.locator:
                            element = await resolve_locator(page, step.locator, timeout_ms=3000)
                            if element is None:
                                raise LocatorNotFoundError(f"Could not locate element to read at step {step.id}")

                    # Step executed successfully
                    _log_event({
                        "event": "step_executed",
                        "step_id": step.id,
                        "step_index": step_idx,
                        "action": step.action,
                        "value": action_value,
                        "url_after": page.url,
                    })

                except Exception as step_err:
                    # Capture error screenshot & a11y snapshot
                    err_screenshot = evidence_dir / "screenshots" / f"step_{step_idx}_error.png"
                    try:
                        await page.screenshot(path=str(err_screenshot))
                    except Exception:
                        pass

                    # Check for known business outcomes on the error page
                    outcome = await check_known_outcomes(page, artifact.known_outcomes)
                    if outcome and outcome.matched:
                        _log_event({
                            "event": "known_outcome_detected",
                            "classification": outcome.classification,
                            "outcome_code": outcome.outcome_code,
                            "message": outcome.message,
                        })
                        return ReplayResult(
                            status=outcome.classification,  # "business_outcome" or "hard_failure"
                            outcome_code=outcome.outcome_code,
                            step_index=step_idx,
                            expected="Standard workflow transition",
                            observed=outcome.message,
                            evidence_path=str(evidence_dir),
                            message=outcome.message,
                        )

                    # No known outcome matched -> report hard failure
                    return ReplayResult(
                        status="hard_failure",
                        outcome_code="LOCATOR_NOT_FOUND" if isinstance(step_err, LocatorNotFoundError) else "STEP_EXECUTION_FAILED",
                        step_index=step_idx,
                        expected=f"Successful execution of step {step.id}",
                        observed=str(step_err),
                        evidence_path=str(evidence_dir),
                        message=f"Step {step.id} failed: {step_err}",
                    )

                # Check step checkpoint if defined with resilient polling window (up to 4.0s)
                if step.checkpoint:
                    checkpoint_passed = False
                    start_poll = time.time()
                    while time.time() - start_poll < 4.0:
                        if step.checkpoint.startswith("url_contains:"):
                            expected_frag = step.checkpoint[len("url_contains:"):].strip()
                            if expected_frag in page.url:
                                checkpoint_passed = True
                                break
                        elif step.checkpoint.startswith("text_visible:"):
                            expected_text = step.checkpoint[len("text_visible:"):].strip()
                            body = await page.inner_text("body")
                            if expected_text.lower() in body.lower():
                                checkpoint_passed = True
                                break

                        # Fast-fail if a known business outcome appeared during the transition
                        outcome = await check_known_outcomes(page, artifact.known_outcomes)
                        if outcome and outcome.matched:
                            break
                        await page.wait_for_timeout(250)

                    if not checkpoint_passed:
                        # Before failing, check if this is a known business outcome
                        outcome = await check_known_outcomes(page, artifact.known_outcomes)
                        if outcome and outcome.matched:
                            _log_event({
                                "event": "known_outcome_at_checkpoint",
                                "classification": outcome.classification,
                                "outcome_code": outcome.outcome_code,
                                "message": outcome.message,
                            })
                            return ReplayResult(
                                status=outcome.classification,
                                outcome_code=outcome.outcome_code,
                                step_index=step_idx,
                                expected=step.checkpoint,
                                observed=outcome.message,
                                evidence_path=str(evidence_dir),
                                message=outcome.message,
                            )

                        return ReplayResult(
                            status="hard_failure",
                            outcome_code="CHECKPOINT_FAILED",
                            step_index=step_idx,
                            expected=step.checkpoint,
                            observed=f"Current URL: {page.url}",
                            evidence_path=str(evidence_dir),
                            message=f"Checkpoint assertion failed at step {step.id}",
                        )

                step_idx += 1

            # Assert overall success checkpoint with resilient polling window
            if artifact.success_checkpoint:
                success_passed = False
                start_poll = time.time()
                while time.time() - start_poll < 4.0:
                    if artifact.success_checkpoint.startswith("url_contains:"):
                        exp_url = artifact.success_checkpoint[len("url_contains:"):].strip()
                        if exp_url in page.url:
                            success_passed = True
                            break
                    elif artifact.success_checkpoint.startswith("text_visible:"):
                        exp_text = artifact.success_checkpoint[len("text_visible:"):].strip()
                        body = await page.inner_text("body")
                        if exp_text.lower() in body.lower():
                            success_passed = True
                            break
                    await page.wait_for_timeout(250)

                if not success_passed:
                    return ReplayResult(
                        status="hard_failure",
                        outcome_code="SUCCESS_CHECKPOINT_FAILED",
                        expected=artifact.success_checkpoint,
                        observed=f"Final URL: {page.url}",
                        evidence_path=str(evidence_dir),
                        message="Workflow finished but final success checkpoint was not met.",
                    )

            # Extract declared outputs
            for out in artifact.outputs:
                try:
                    elem = await resolve_locator(page, out.extract_from, timeout_ms=2000)
                    if elem:
                        text_val = (await elem.inner_text()).strip()
                        extracted_outputs[out.name] = text_val
                except Exception as e:
                    extracted_outputs[out.name] = f"Extraction failed: {e}"

            # Capture final success screenshot
            final_screenshot = evidence_dir / "screenshots" / "final_success.png"
            await page.screenshot(path=str(final_screenshot))

            _log_event({
                "event": "replay_success",
                "outputs": extracted_outputs,
                "final_url": page.url,
            })

            return ReplayResult(
                status="success",
                outputs=extracted_outputs,
                step_index=step_idx,
                evidence_path=str(evidence_dir),
                message="Capability replayed successfully with verified checkpoints.",
            )

        # Execution context management
        if existing_page is not None:
            return await _run_steps_on_page(existing_page)

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
                result = await _run_steps_on_page(page)
                return result
            finally:
                await context.close()
                await browser.close()
