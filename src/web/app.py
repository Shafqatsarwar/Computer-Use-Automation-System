"""Web Application & Operator Console Backend (FastAPI).

Provides REST APIs and serves the interactive single-page dashboard at http://localhost:3000
Supports:
- Discovery studio
- Replay execution with live results
- Human escalation operator console
- Capability artifact catalog
- Evidence gallery
- Synthetic LegacyBank demo application
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agent.loop import DiscoveryAgent
from src.agent.model_client import GeminiDiscoveryClient
from src.artifact.recorder import ArtifactRecorder
from src.artifact.schema import CapabilityArtifact, Locator, Step
from src.escalation.handoff import EscalationSession
from src.guardrails.allowlist import default_allowlist
from src.replay.executor import ReplayEngine

app = FastAPI(
    title="Computer-Use Automation System",
    description="Deterministic Replay, LLM Discovery & Human Escalation Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active live escalation session store
active_escalation: dict[str, EscalationSession] = {}


class DiscoverRequest(BaseModel):
    goal: str = "Log in, add Sauce Labs Backpack to cart, complete checkout to the overview page, report the total"
    url: str = "https://www.saucedemo.com"
    artifact_id: str = "checkout_backpack_v1"
    max_steps: int = 15
    headless: bool = True


class ReplayRequest(BaseModel):
    artifact_id: str = "checkout_backpack_v1"
    params: dict[str, str] = Field(default_factory=lambda: {"username": "standard_user", "password": "secret_sauce"})
    headless: bool = True


class OperatorActionRequest(BaseModel):
    session_id: str
    action: str  # click, type, navigate, wait
    role: str | None = None
    name: str | None = None
    text: str | None = None
    url: str | None = None


# Static file serving directory setup
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
EVIDENCE_DIR = Path("evidence")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR = Path("artifacts")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/evidence_files", StaticFiles(directory=str(EVIDENCE_DIR)), name="evidence_files")


# --- API Routes ---

@app.get("/api/health")
async def get_health() -> dict[str, Any]:
    return {
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gemini_api_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "artifacts_count": len(list(ARTIFACTS_DIR.glob("*.json"))),
    }


@app.get("/api/artifacts")
async def list_artifacts() -> list[dict[str, Any]]:
    """Lists all compiled capability artifacts."""
    artifacts = []
    for p in ARTIFACTS_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                artifacts.append(data)
        except Exception:
            pass
    return sorted(artifacts, key=lambda x: x.get("id", ""))


@app.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str) -> dict[str, Any]:
    file_path = ARTIFACTS_DIR / f"{artifact_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/api/discover")
async def run_discovery(req: DiscoverRequest) -> dict[str, Any]:
    """Triggers an LLM discovery run."""
    client = GeminiDiscoveryClient()
    agent = DiscoveryAgent(model_client=client, max_steps=req.max_steps)

    try:
        transcript = await agent.run(
            goal=req.goal,
            entry_url=req.url,
            headless=req.headless,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    saved_artifact_id = None
    if transcript.success:
        artifact = ArtifactRecorder.compile_saucedemo_checkout(
            transcript=transcript,
            artifact_id=req.artifact_id,
        )
        ArtifactRecorder.save_artifact(artifact)
        saved_artifact_id = artifact.id

    return {
        "run_id": transcript.run_id,
        "success": transcript.success,
        "reason": transcript.reason,
        "steps_count": len(transcript.steps),
        "steps": [s.model_dump(mode="json") for s in transcript.steps],
        "evidence_dir": transcript.evidence_dir,
        "artifact_id": saved_artifact_id,
    }


@app.post("/api/replay")
async def run_replay(req: ReplayRequest) -> dict[str, Any]:
    """Triggers deterministic replay without LLM."""
    file_path = ARTIFACTS_DIR / f"{req.artifact_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact {req.artifact_id} not found")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    artifact = CapabilityArtifact.model_validate(data)

    engine = ReplayEngine()
    result = await engine.execute(
        artifact=artifact,
        params=req.params,
        headless=req.headless,
    )
    return result.model_dump(mode="json")


@app.get("/api/evidence")
async def list_evidence() -> list[dict[str, Any]]:
    """Lists all saved execution runs and evidence."""
    runs = []
    for item in EVIDENCE_DIR.iterdir():
        if item.is_dir():
            log_file = item / "log.jsonl"
            logs_count = 0
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8") as f:
                    logs_count = sum(1 for _ in f)
            screenshots = [f.name for f in (item / "screenshots").glob("*.png")] if (item / "screenshots").exists() else []
            runs.append({
                "run_id": item.name,
                "log_entries": logs_count,
                "screenshots": screenshots,
                "path": str(item),
            })
    return sorted(runs, key=lambda x: x["run_id"], reverse=True)


@app.get("/api/evidence/{run_id}/logs")
async def get_evidence_logs(run_id: str) -> list[dict[str, Any]]:
    log_file = EVIDENCE_DIR / run_id / "log.jsonl"
    if not log_file.exists():
        return []
    logs = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    logs.append(json.loads(line))
                except Exception:
                    pass
    return logs


# --- Synthetic LegacyBank Demo Surface (Embedded in port 3000) ---

@app.get("/demo/bank/login", response_class=HTMLResponse)
async def legacy_bank_login():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>LegacyBank Core Services - Sign In</title>
    <style>
        body { font-family: 'Courier New', monospace; background: #e0e0e0; color: #111; padding: 30px; }
        .banner { background: #003366; color: white; padding: 15px; font-size: 20px; font-weight: bold; border-radius: 4px; }
        .disclaimer { background: #ffcc00; color: #000; padding: 8px; font-weight: bold; margin: 10px 0; border: 1px solid #999; }
        .login-box { background: #f7f7f7; border: 2px solid #666; padding: 20px; width: 420px; margin-top: 20px; }
        table { width: 100%; }
        td { padding: 8px; }
        input[type=text], input[type=password] { width: 90%; padding: 6px; font-family: inherit; }
        button { background: #003366; color: white; padding: 8px 16px; border: 1px solid #000; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <div class="banner">LegacyBank Core Servicing Portal v4.2</div>
    <div class="disclaimer">DEMO / SYNTHETIC DATA — NOT A REAL BANK</div>
    <div class="login-box">
        <h3>Operator Authentication</h3>
        <form action="/demo/bank/search" method="get">
            <table>
                <tr><td>Operator ID:</td><td><input type="text" name="op_id" value="TELLER_01" aria-label="Operator ID"></td></tr>
                <tr><td>Passcode:</td><td><input type="password" name="passcode" value="demo123" aria-label="Passcode"></td></tr>
                <tr><td colspan="2"><button type="submit" name="login_btn" role="button">Sign In to Core</button></td></tr>
            </table>
        </form>
    </div>
</body>
</html>
"""

@app.get("/demo/bank/search", response_class=HTMLResponse)
async def legacy_bank_search(member_id: str | None = None):
    if member_id == "12345":
        return """
<!DOCTYPE html>
<html>
<head>
    <title>LegacyBank - Member Detail</title>
    <style>
        body { font-family: 'Courier New', monospace; background: #e0e0e0; color: #111; padding: 30px; }
        .banner { background: #003366; color: white; padding: 15px; font-size: 20px; font-weight: bold; }
        .disclaimer { background: #ffcc00; color: #000; padding: 8px; font-weight: bold; margin: 10px 0; }
        .panel { background: #fff; border: 2px solid #333; padding: 20px; margin-top: 15px; width: 600px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #999; padding: 8px; text-align: left; }
        th { background: #eee; }
        .balance { font-size: 18px; font-weight: bold; color: #006600; }
    </style>
</head>
<body>
    <div class="banner">LegacyBank Core Servicing Portal v4.2</div>
    <div class="disclaimer">DEMO / SYNTHETIC DATA — NOT A REAL BANK</div>
    <div class="panel">
        <h2>Member Account Summary</h2>
        <table>
            <tr><th>Field</th><th>Value</th></tr>
            <tr><td>Member ID</td><td>12345</td></tr>
            <tr><td>Member Name</td><td>Alex Morgan</td></tr>
            <tr><td>Checking Balance</td><td>$3,210.50</td></tr>
            <tr><td>Regular Savings Balance</td><td class="balance" aria-label="Savings Balance">$12,450.00</td></tr>
            <tr><td>Account Status</td><td>Active / In Good Standing</td></tr>
        </table>
        <p style="margin-top: 20px;"><a href="/demo/bank/search">Search Another Member</a></p>
    </div>
</body>
</html>
"""
    elif member_id and member_id != "12345":
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>LegacyBank - Search Result</title>
    <style>
        body {{ font-family: 'Courier New', monospace; background: #e0e0e0; color: #111; padding: 30px; }}
        .error-msg {{ background: #ffcccc; color: #cc0000; padding: 12px; border: 2px solid #cc0000; font-weight: bold; margin-top: 20px; width: 500px; }}
    </style>
</head>
<body>
    <div class="error-msg">Core Error 404: Member ID '{member_id}' not found in institution database.</div>
    <p><a href="/demo/bank/search">Back to Member Search</a></p>
</body>
</html>
"""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>LegacyBank - Member Search</title>
    <style>
        body { font-family: 'Courier New', monospace; background: #e0e0e0; color: #111; padding: 30px; }
        .banner { background: #003366; color: white; padding: 15px; font-size: 20px; font-weight: bold; }
        .disclaimer { background: #ffcc00; color: #000; padding: 8px; font-weight: bold; margin: 10px 0; }
        .search-box { background: #f7f7f7; border: 2px solid #666; padding: 20px; width: 500px; margin-top: 20px; }
        input[type=text] { width: 80%; padding: 6px; font-family: inherit; }
        button { background: #003366; color: white; padding: 8px 16px; border: 1px solid #000; cursor: pointer; font-weight: bold; }
    </style>
</head>
<body>
    <div class="banner">LegacyBank Core Servicing Portal v4.2</div>
    <div class="disclaimer">DEMO / SYNTHETIC DATA — NOT A REAL BANK</div>
    <div class="search-box">
        <h3>Member Account Lookup</h3>
        <form action="/demo/bank/search" method="get">
            <p>Enter Member ID (e.g. 12345):</p>
            <input type="text" name="member_id" placeholder="Enter Member ID" aria-label="Member ID">
            <button type="submit" name="search_btn" role="button">Search Member</button>
        </form>
    </div>
</body>
</html>
"""


# --- Serve Main Single-Page Application (SPA) at / ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Computer-Use Automation System Dashboard</h1>"


def start_server(host: str = "0.0.0.0", port: int = 3000) -> None:
    """Starts the uvicorn web server."""
    print("============================================================")
    print(">> Computer-Use Automation System Dashboard Starting")
    print(f">> Open in browser: http://localhost:{port}")
    print("============================================================")
    uvicorn.run("src.web.app:app", host=host, port=port, reload=False, log_level="info")
