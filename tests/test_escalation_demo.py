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
