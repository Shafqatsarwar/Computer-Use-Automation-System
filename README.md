# Computer-Use Automation System

> **interface.ai Engineering Take-Home Challenge**  
> An agentic computer-use and deterministic replay integration platform for legacy enterprise and financial software without APIs.

---

## 1. System Overview

The **Computer-Use Automation System** solves the core challenge of integrating with legacy enterprise applications (core banking screens, servicing tools, admin consoles) that lack APIs.

```text
Natural-Language Goal
        ↓
Real LLM Discovery Agent (Gemini 2.5 Flash / Gemini 3 Flash)
        ↓
Live Browser Automation (Playwright via A11y Tree + Role/Name perception)
        ↓
Typed, Parameterized Capability Artifact (Pydantic v2 Schema)
        ↓
Deterministic Replay Engine (ZERO LLM in loop, Sub-second, Robust Fallbacks)
        ↓
Outcome & Error Taxonomy (Business Outcomes vs. Recoverable vs. Hard Failures)
        ↓
Human-in-the-Loop Escalation (Live CDP Session Transfer, Pause & Resume)
```

### Central Philosophy
> **The model discovers. The artifact becomes the capability. Deterministic replay is the production execution path.**

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

# 4. Configure environment
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY (from Google AI Studio: https://aistudio.google.com/)
```

### Running Offline / Without Live API
The deterministic replay engine and test suite do not require Gemini API access:
```bash
# Run full unit & integration test suite (15 tests)
pytest tests/ -v
```

---

## 3. Demo Path (CLI Commands)

### A. Run LLM Discovery (Real Gemini API Call against Live UI)
```bash
python -m src.cli discover --goal "Log in, add Sauce Labs Backpack to cart, complete checkout to the overview page, report the total" --url https://www.saucedemo.com
```

### B. Happy-Path Deterministic Replay (Zero LLM)
```bash
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce
```
*Expected Output:* Status `SUCCESS`, verified checkpoints, extracted outputs (`item_total`, `tax`, `total`).

### C. Business Outcome Replay (`locked_out_user`)
```bash
python -m src.cli replay --artifact checkout_backpack_v1 --params username=locked_out_user password=secret_sauce
```
*Expected Output:* Status `BUSINESS_OUTCOME`, outcome code `USER_LOCKED_OUT` (handled cleanly as an expected business state without crashing).

### D. Human Escalation & Live Session Takeover Demo
```bash
python -m src.cli escalate-test
```
*Expected Output:* Automation pauses upon encountering an unresolvable locator, operator console executes manual action on the live browser session (`actor: "human"`), and automation resumes to completion.

---

## 4. Web Dashboard & Operator Console (Port 3000)

Launch the full interactive single-page dashboard:
```bash
python -m src.cli serve --port 3000
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser:
- **Discovery Studio:** Interactive goal launcher and live LLM step tracer.
- **Capability Catalog:** Visual inspector for registered capability schemas and locator chains.
- **Deterministic Replay Runner:** One-click execution with test account selector (`standard_user`, `locked_out_user`, `problem_user`).
- **Live Escalation Console:** Real-time session takeover and control handoff.
- **Evidence Vault:** Browse JSONL audit logs and captured screenshots.
- **LegacyBank Proxy:** Embedded legacy banking application with non-clean DOM and table layouts (`/demo/bank/login`).

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
│   ├── agent/              # LLM Discovery Loop (Gemini 2.5 Flash + fallback)
│   ├── artifact/           # Pydantic v2 Capability Artifact Schema & Recorder
│   ├── escalation/         # Live session handoff & operator CLI
│   ├── evidence/           # Structured JSONL logger with secret redaction
│   ├── guardrails/         # Allowlist, risk policy, secret & PII redactor
│   ├── replay/             # Deterministic Replay Engine (NO LLM)
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
