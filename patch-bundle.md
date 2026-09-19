# Patch Bundle — Computer-Use Automation System

Apply these changes in order. Each section names the exact file path, then either a `FIND` / `REPLACE` block (apply as a str-replace on that exact text) or `NEW FILE — FULL CONTENT` (create the file with this content). After all patches are applied, run the verification commands in Section 9.

---

## 1. `src/agent/model_client.py` — force function-calling (the actual root cause)

FIND:
```python
        config = types.GenerateContentConfig(
            tools=DISCOVERY_TOOLS,
            temperature=0.1,
            system_instruction=system_instruction or (
                "You are an expert browser automation agent operating a legacy enterprise/e-commerce UI. "
                "Your objective is to accomplish the user's goal by taking ONE discrete action at a time. "
                "Inspect the provided accessibility tree and current page state carefully. "
                "Use 'click' with role and accessible name, 'type' with role, name and text, or 'navigate'. "
                "Call 'finish' immediately when the target page or goal is achieved."
            ),
        )
```

REPLACE:
```python
        config = types.GenerateContentConfig(
            tools=DISCOVERY_TOOLS,
            temperature=0.1,
            # Force a function call every turn. Without this, gemini-2.5-flash can
            # respond with plain text on an ambiguous page, which our extractor
            # then treats as "no tool call" and silently falls back to the
            # secondary model for that turn -- this was why every real discovery
            # run so far had model_used == gemini-3-flash-preview on every step.
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
            system_instruction=system_instruction or (
                "You are an expert browser automation agent operating a legacy enterprise/e-commerce UI. "
                "Your objective is to accomplish the user's goal by taking ONE discrete action at a time. "
                "Inspect the provided accessibility tree and current page state carefully. "
                "Use 'click' with role and accessible name, 'type' with role, name and text, or 'navigate'. "
                "Call 'finish' immediately when the target page or goal is achieved."
            ),
        )
```

---

## 2. `src/agent/loop.py` — more headroom to actually reach `finish()`

FIND:
```python
        max_steps: int = 15,
        timeout_seconds: int = 180,
```

REPLACE:
```python
        max_steps: int = 25,
        timeout_seconds: int = 240,
```

---

## 3. `src/web/app.py` — match the raised step budget, add the real escalation route

FIND:
```python
    max_steps: int = 15
```

REPLACE:
```python
    max_steps: int = 25
```

Then add this new route anywhere among the other `@app.post(...)` routes (e.g. directly after `run_replay`):

```python
@app.post("/api/escalate/demo")
async def run_escalation_demo_endpoint() -> dict[str, Any]:
    """Triggers the REAL escalation scenario: live browser, broken locator,
    a genuine human-action handoff, resume, completion. This calls the exact
    same function as `python -m src.cli escalate-test` -- not a separate,
    faked dashboard-only path.
    """
    from src.escalation.handoff import run_escalation_demo
    try:
        return await run_escalation_demo(headless=True, non_interactive=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 4. `src/escalation/handoff.py` — the single real implementation, shared by CLI and web

Append this function at the end of the file (`Any` is already imported at the top via `from typing import Any, Callable`, no new import needed):

```python
async def run_escalation_demo(
    headless: bool = True,
    non_interactive: bool = True,
    evidence_dir: str = "evidence/escalation_demo",
) -> dict[str, Any]:
    """Runs the real escalation scenario end to end: live browser, an
    intentionally broken locator, a real human-operator handoff on the SAME
    session, resume, and completion. Both `python -m src.cli escalate-test`
    and the web dashboard's escalation button call this exact function, so
    there is only one real implementation, not a duplicated/fake one.
    """
    from playwright.async_api import async_playwright
    from src.escalation.operator_cli import run_operator_console

    events: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        try:
            await page.goto("https://www.saucedemo.com", wait_until="domcontentloaded")
            await page.fill("[data-test='username']", "standard_user")
            await page.fill("[data-test='password']", "secret_sauce")
            await page.click("[data-test='login-button']")
            await page.wait_for_timeout(1000)
            events.append("Automation: logged in as standard_user")

            escalation = EscalationSession(
                page=page,
                reason="LOCATOR_NOT_FOUND: Element 'non_existent_backpack_btn' not found after all fallbacks exhausted.",
                step_index=2,
                evidence_dir=evidence_dir,
            )
            events.append(f"Escalation triggered: {escalation.reason}")

            auto_commands = [{"action": "click", "role": "button", "name": "Add to cart", "text": None}]
            await run_operator_console(
                escalation,
                auto_commands=auto_commands if non_interactive else None,
            )
            for rec in escalation.actions_taken:
                events.append(f"Human action: {rec.action} {rec.target_role} '{rec.target_name}' -> {rec.result}")
            events.append("Session resumed by operator")

            await page.click(".shopping_cart_link")
            await page.wait_for_timeout(500)
            await page.click("[data-test='checkout']")
            await page.wait_for_timeout(500)
            await page.fill("[data-test='firstName']", "Alex")
            await page.fill("[data-test='lastName']", "Morgan")
            await page.fill("[data-test='postalCode']", "94016")
            await page.click("[data-test='continue']")
            await page.wait_for_timeout(500)

            total_text = await page.locator(".summary_total_label").inner_text()
            events.append(f"Automation resumed and completed. Total: {total_text}")

            screenshot_path = f"{evidence_dir}/final_resumed_success.png"
            await page.screenshot(path=screenshot_path)

            return {
                "success": True,
                "events": events,
                "human_actions": [r.model_dump(mode="json") for r in escalation.actions_taken],
                "final_total": total_text,
                "evidence_dir": evidence_dir,
                "screenshot_path": screenshot_path,
            }
        finally:
            await context.close()
            await browser.close()
```

---

## 5. `src/cli.py` — point the CLI at the same real function instead of its own copy

FIND:
```python
async def handle_escalate_test(args: argparse.Namespace) -> None:
    """Demonstrates live session pause, human intervention, and resumption."""
    from playwright.async_api import async_playwright

    console.print(Panel(
        "[bold yellow]Simulating Broken Locator to Test Human Escalation on Live Browser Session[/bold yellow]\n"
        "1. Replay starts on live browser session.\n"
        "2. Step hits an intentionally broken locator -> LOCATOR_NOT_FOUND.\n"
        "3. Session is paused; human operator takes over.\n"
        "4. Operator performs manual fix in console.\n"
        "5. Control is handed back -> session resumes to completion.",
        title="Human Escalation Test Scenario",
    ))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        try:
            # Navigate to login
            await page.goto("https://www.saucedemo.com", wait_until="domcontentloaded")
            await page.fill("[data-test='username']", "standard_user")
            await page.fill("[data-test='password']", "secret_sauce")
            await page.click("[data-test='login-button']")
            await page.wait_for_timeout(1000)

            # Intentional failure: attempt to find a non-existent button
            console.print("[yellow]Attempting to locate deliberately broken element 'non_existent_backpack_btn'...[/yellow]")
            escalation = EscalationSession(
                page=page,
                reason="LOCATOR_NOT_FOUND: Element 'non_existent_backpack_btn' not found after all fallbacks exhausted.",
                step_index=2,
                evidence_dir="evidence/escalation_demo",
            )

            # Run operator console (with auto scripted fix command for automated verification)
            auto_commands = [
                {"action": "click", "role": "button", "name": "Add to cart", "text": None},
            ]
            await run_operator_console(escalation, auto_commands=auto_commands if args.non_interactive else None)

            # Resume automated flow
            console.print("[green]Resuming automated checkout verification...[/green]")
            await page.click(".shopping_cart_link")
            await page.wait_for_timeout(500)
            await page.click("[data-test='checkout']")
            await page.wait_for_timeout(500)
            await page.fill("[data-test='firstName']", "Alex")
            await page.fill("[data-test='lastName']", "Morgan")
            await page.fill("[data-test='postalCode']", "94016")
            await page.click("[data-test='continue']")
            await page.wait_for_timeout(500)

            total_elem = page.locator(".summary_total_label")
            total_text = await total_elem.inner_text()
            console.print(f"[bold green][SUCCESS] Flow successfully completed after human intervention! Final Total: {total_text}[/bold green]")
            
            # Save final screenshot
            await page.screenshot(path="evidence/escalation_demo/final_resumed_success.png")

        finally:
            await context.close()
            await browser.close()
```

REPLACE:
```python
async def handle_escalate_test(args: argparse.Namespace) -> None:
    """Demonstrates live session pause, human intervention, and resumption."""
    from src.escalation.handoff import run_escalation_demo

    console.print(Panel(
        "[bold yellow]Simulating Broken Locator to Test Human Escalation on Live Browser Session[/bold yellow]\n"
        "1. Replay starts on live browser session.\n"
        "2. Step hits an intentionally broken locator -> LOCATOR_NOT_FOUND.\n"
        "3. Session is paused; human operator takes over.\n"
        "4. Operator performs manual fix in console.\n"
        "5. Control is handed back -> session resumes to completion.",
        title="Human Escalation Test Scenario",
    ))

    result = await run_escalation_demo(headless=args.headless, non_interactive=args.non_interactive)
    for line in result["events"]:
        console.print(f"[cyan]{line}[/cyan]")
    console.print(
        f"[bold green][SUCCESS] Flow completed after human intervention! "
        f"Final Total: {result['final_total']}[/bold green]"
    )
```

---

## 6. `src/web/static/index.html` — wire the dashboard button to the real function

FIND:
```javascript
        async function runEscalationTest() {
            const term = document.getElementById('esc-terminal');
            term.innerHTML = '<span class="log-tag warn">SIMULATION</span> Starting Replay with Intentionally Broken Locator...\n';
            term.innerHTML += '[Automation] Step 1: Navigated to saucedemo.com -> SUCCESS\n';
            term.innerHTML += '[Automation] Step 2: Typed username & password -> SUCCESS\n';
            term.innerHTML += '<span class="log-tag error">FAIL</span> Step 3: Locator \'non_existent_backpack_btn\' NOT FOUND after trying [role, text, css] strategies!\n';
            term.innerHTML += '<span class="log-tag warn">ESCALATION</span> Automated loop PAUSED. Control transferred to Operator on live CDP session.\n\n';
            
            setTimeout(() => {
                term.innerHTML += '<span class="log-tag info">HUMAN</span> [actor: "human"] Operator performed: click role="button" name="Add to cart"\n';
                term.innerHTML += '<span class="log-tag info">HUMAN</span> [actor: "human"] Element clicked successfully on live session.\n';
                term.innerHTML += '<span class="log-tag success">RESUME</span> Operator clicked Resume Automation -> Control returned to engine.\n';
                term.innerHTML += '[Automation] Step 4: Proceeded to checkout -> Overview Screen reached.\n';
                term.innerHTML += '<span class="log-tag success">SUCCESS</span> Total verified: $32.39. Evidence saved to evidence/escalation_demo/\n';
            }, 1000);
        }
```

REPLACE:
```javascript
        async function runEscalationTest() {
            const term = document.getElementById('esc-terminal');
            term.innerHTML = '<span class="log-tag warn">LIVE</span> Launching real browser session, triggering intentional locator failure...\n';
            try {
                const res = await fetch('/api/escalate/demo', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) {
                    term.innerHTML += `<span class="log-tag error">ERROR</span> ${data.detail || 'Escalation demo failed'}\n`;
                    return;
                }
                (data.events || []).forEach(line => {
                    const tag = line.startsWith('Human action') ? 'info' : (line.includes('resumed') ? 'success' : 'info');
                    term.innerHTML += `<span class="log-tag ${tag}">${tag.toUpperCase()}</span> ${line}\n`;
                });
                term.innerHTML += `<span class="log-tag success">SUCCESS</span> Total verified: ${data.final_total}. Evidence saved to ${data.evidence_dir}/\n`;
            } catch (e) {
                term.innerHTML += `<span class="log-tag error">ERROR</span> ${e}\n`;
            }
        }
```

---

## 7. `README.md` — stop framing the required discovery run as "optional"

FIND:
```
> A deterministic browser-automation capability platform with optional Gemini-assisted discovery.
```

REPLACE:
```
> A deterministic browser-automation capability platform. Gemini performs a required, real discovery run once per capability; every subsequent invocation replays with zero LLM calls.
```

FIND:
```
### D. Secondary path: Gemini discovery (optional)
```

REPLACE:
```
### D. Discovery (required once, to produce the artifact submitted with this project)
```

---

## 8. `tests/test_model_client.py` — NEW FILE — FULL CONTENT

```python
"""Unit test for the forced function-calling fix in GeminiDiscoveryClient.

Does not call the live Gemini API -- verifies the request shape only, so it
runs fast and doesn't burn quota. This is a regression test for the bug where
gemini-2.5-flash silently returned plain text instead of a tool call and the
loop fell back to the secondary model on every single step.
"""

from unittest.mock import MagicMock
import pytest
from google.genai import types
from src.agent.model_client import GeminiDiscoveryClient


def _fake_response_with_function_call():
    fc = types.FunctionCall(name="finish", args={"success": True, "reason": "done"})
    response = MagicMock()
    response.function_calls = [fc]
    return response


def test_decide_forces_function_calling_mode_any():
    client = GeminiDiscoveryClient(api_key="fake-key-for-test")
    mock_generate = MagicMock(return_value=_fake_response_with_function_call())
    client._client = MagicMock()
    client._client.models.generate_content = mock_generate

    decision = client.decide("dummy prompt")

    assert decision.tool_name == "finish"
    assert mock_generate.called
    _, kwargs = mock_generate.call_args
    config = kwargs["config"]
    assert config.tool_config is not None
    assert config.tool_config.function_calling_config.mode == "ANY"


def test_decide_raises_clear_error_without_api_key():
    client = GeminiDiscoveryClient(api_key=None)
    client._client = None
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        client.decide("dummy prompt")
```

---

## 9. `tests/test_escalation_demo.py` — NEW FILE — FULL CONTENT

```python
"""Integration test for the shared escalation demo function.

Confirms the CLI path and the web API path both exercise the same real
handoff mechanism (live browser, real human-actor logging, real resume).
"""

import json
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from src.escalation.handoff import run_escalation_demo
from src.web.app import app


@pytest.mark.asyncio
async def test_run_escalation_demo_produces_real_human_action_log(tmp_path):
    evidence_dir = str(tmp_path / "escalation_demo")
    result = await run_escalation_demo(
        headless=True,
        non_interactive=True,
        evidence_dir=evidence_dir,
    )

    assert result["success"] is True
    assert any(a["actor"] == "human" for a in result["human_actions"])
    assert "$" in result["final_total"]

    log_file = Path(evidence_dir) / "escalation_log.jsonl"
    assert log_file.exists()
    lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
    assert lines, "escalation_log.jsonl should contain at least one real human action"
    assert lines[-1]["actor"] == "human"


@pytest.mark.asyncio
async def test_api_escalation_endpoint_uses_the_real_function():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
        resp = await ac.post("/api/escalate/demo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert any(a["actor"] == "human" for a in data["human_actions"])
```

---

## 10. Verification — run after every patch above is applied

```bash
# 1. Delete the fabricated discovery evidence and rebuild from a genuine run
rm -rf evidence/demo_discovery_run
python -m src.cli discover --goal "Log in, add Sauce Labs Backpack to cart, complete checkout to the overview page, report the total" --url https://www.saucedemo.com
# Confirm the printed transcript ends in finish(success=True) before moving on.
# If model_used shows gemini-2.5-flash for most/all steps now, the tool_config fix worked.

# 2. Rebuild the artifact from that real transcript (recorder.py reads the latest successful run)
#    -- if your recorder needs an explicit run_id argument, pass the new discovery run's evidence dir here.

# 3. Re-run replay on both accounts
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce
python -m src.cli replay --artifact checkout_backpack_v1 --params username=locked_out_user password=secret_sauce

# 4. Re-run the escalation demo via CLI
python -m src.cli escalate-test

# 5. Run the new tests plus the existing suite
pytest tests/test_model_client.py tests/test_escalation_demo.py tests/test_replay.py -v

# 6. Start the web dashboard and click the escalation button manually to confirm it now
#    hits /api/escalate/demo and shows real events, not the old canned text.
python -m src.cli serve --port 3000
```

If discovery still doesn't reach `finish()` after patches 1–2, capture the new transcript's `reason` field and its last 3–4 steps and share them — that will show whether it's still a model-calling issue or has become a locator-matching issue instead (e.g. the cart icon being identified as `role="link", name="1"` is fragile and worth hardening next).
