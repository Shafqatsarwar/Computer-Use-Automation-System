# Computer-Use Automation System

> **interface.ai Engineering Take-Home Challenge**  
> A deterministic browser-automation capability platform. Gemini performs a required, real discovery run once per capability; every subsequent invocation replays with zero LLM calls.

---

## 1. System Overview

The system turns a browser workflow into a typed, reusable capability. The system uses an LLM (Google Gemini) once during discovery to explore the live UI and emit a typed capability artifact. Every subsequent execution in production is a deterministic replay of that artifact with strictly zero LLM calls in the loop.

```text
Discovery Phase (Run once per workflow):
Natural-Language Goal → Gemini Discovery (A11y perception + tool calling) → Typed Capability Artifact
        ↓
Production Execution (Replay many times):
Saved Capability Artifact → Deterministic Replay Engine (Strictly ZERO LLM) → Extracted Outputs / Outcome Taxonomy
        ↓
Human Escalation (When stuck):
Live Browser CDP Session Transfer → Operator Console Takeover → Safe Resume
```

### Central Philosophy
> **The model discovers. The artifact becomes the capability. Deterministic replay is the production execution path.**

### Primary and secondary responsibilities

| Area | Primary behavior | External API required? |
|---|---|---:|
| Deterministic replay | Executes saved artifacts, checks locators/checkpoints, extracts outputs | No |
| Business outcomes | Returns structured results such as `USER_LOCKED_OUT` | No |
| Safety guardrails | Enforces domains, actions, risk policy, and redaction | No |
| Human escalation | Pauses, records operator actions, and resumes the same session | No |
| Capability catalog | Loads and validates local JSON artifacts | No |
| Gemini discovery | Creates a new artifact from a natural-language goal | Yes (one-time per capability) |
| AI verification | Live discovery and verification modal from the dashboard | Yes |

---

## 2. Setup & Installation

### Prerequisites
- Python 3.11+
- Playwright Chromium

```bash
# 1. Clone repository
git clone <repo_url>
cd Computer-Use-Automation-System

# 2. Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Install Playwright browser engine
python -m playwright install chromium

# 4. Optional: configure Gemini only if you will run discovery or AI verification
# PowerShell:
Copy-Item .env.example .env
# Then edit .env and set GEMINI_API_KEY.
# Replay, tests, the catalog, escalation, and the dashboard do not need this key.
```

### Running Offline / Without Live API
The primary workflow is API-free. The deterministic replay engine, dashboard, artifact catalog, escalation flow, and test suite do not require Gemini API access:
```bash
# Run the full unit and integration test suite
pytest tests/ -v

# Run a saved capability without Gemini
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce
```

The password is supplied at runtime and is not stored in the capability artifact.

---

## 3. Demo Path (CLI Commands)

### A. Primary path: deterministic replay (no API)
```bash
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce
```
*Expected Output:* `SUCCESS`, verified checkpoints, and extracted `item_total`, `tax`, and `total` values.

### B. Business outcome verification (no API)
```bash
python -m src.cli replay --artifact checkout_backpack_v1 --params username=locked_out_user password=secret_sauce
```
*Expected Output:* `BUSINESS_OUTCOME` with `USER_LOCKED_OUT`, not an exception.

### C. Human escalation verification (no API)
```bash
python -m src.cli escalate-test
```
*Expected Output:* A broken locator pauses the live session, a human action is recorded, and the workflow resumes.

### D. Discovery (required once, to produce the artifact submitted with this project)
```bash
python -m src.cli discover --goal "Log in, add Sauce Labs Backpack to cart, complete checkout to the overview page, report the total" --url https://www.saucedemo.com
```
This is the LLM-driven discovery command that requires `GEMINI_API_KEY`. It makes real Gemini API calls against the live UI, records `model_used` (`gemini-2.5-flash`) in the discovery transcript, and automatically compiles the resulting `CapabilityArtifact`.

> [!TIP]
> You can append `--headed` to any `replay`, `discover`, or `escalate-test` command to watch the live browser execution directly on your screen.


---

## 4. Web Dashboard & Operator Console (Port 3000)

Launch the full interactive single-page dashboard:
```bash
python -m src.cli serve --port 3000
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser:
- **Deterministic Replay Runner:** Primary manual workflow; executes saved artifacts without Gemini.
- **Capability Catalog:** Visual inspector for registered capability schemas and locator chains.
- **Live Escalation Console:** Real-time session takeover and control handoff.
- **Evidence Vault:** Browse JSONL audit logs and captured screenshots.
- **LegacyBank Proxy:** Embedded legacy banking application with non-clean DOM and table layouts (`/demo/bank/login`).
- **AI Verification:** Fixed secondary utility button for optional Gemini discovery and verification. It is intentionally outside the primary navbar.

---

## 5. Repository Architecture

```text
├── artifacts/              # Versioned Capability Artifacts (JSON)
│   └── checkout_backpack_v1.json
├── docs/
│   └── build-brief.md      # Specification & build brief
├── evidence/               # Per-run JSONL audit logs, screenshots, a11y snapshots
├── guardrails/
│   └── allowlist.yaml      # Permitted domains and actions
├── src/
│   ├── agent/              # LLM Discovery Loop (Gemini + fallback)
│   ├── artifact/           # Pydantic v2 Capability Artifact Schema & Recorder
│   ├── escalation/         # Live session handoff & operator CLI
│   ├── evidence/           # Structured JSONL logger with secret redaction
│   ├── guardrails/         # Allowlist, risk policy, secret & PII redactor
│   ├── replay/             # PRIMARY deterministic Replay Engine (NO LLM/API)
│   ├── web/                # FastAPI backend & Glassmorphic SPA (Port 3000)
│   └── cli.py              # CLI entry point
├── tests/                  # Pytest unit & integration test suite
├── README.md
├── REPORT.md               # 7-section design & architecture write-up
└── requirements.txt
```

---

## 6. Security & Safety Principles

1. **Allowlist Policy:** Strict enforcement before every browser action; blocks unauthorized navigation and unpermitted actions (`eval`, `upload`, `download`).
2. **Secret Redaction:** All sensitive fields (`password`, API keys, tokens) are redacted as `****` at ingestion time and never persisted to logs or capability steps.
3. **Risk Gating:** Irreversible actions (`submit`, `pay`, `confirm`) on `draft` artifacts require human operator authorization.
4. **LLM Boundary:** Gemini is isolated under `src/agent/`. The `src/replay/` package has no Gemini imports and never calls an LLM.
5. **Runtime Secrets:** Credentials are provided through replay parameters, redacted in evidence, and never persisted as artifact defaults. Do not commit `.env` or expose API keys in terminal history, logs, screenshots, or chat.

## 7. Verification Checklist

Run these checks before local deployment:

```powershell
python -m pip check
python -m pytest tests/ -q
python -m src.cli serve --host 127.0.0.1 --port 3000
```

Then open `http://127.0.0.1:3000` and verify the primary replay, locked-out business outcome, artifact catalog, evidence vault, and escalation demo. Use the `AI Verification` button only when Gemini is intentionally configured.
