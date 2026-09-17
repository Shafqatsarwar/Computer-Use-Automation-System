# Developer Guide — Computer-Use Automation System

This guide covers everything needed to run, develop, debug, and maintain the Computer-Use Automation System.

---

## 1. Run Commands

### 1.1 Environment Setup & Dependencies
```bash
# 1. Create and activate virtual environment
python -m venv .venv
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS / Linux:
source .venv/bin/activate

# 2. Install all required dependencies
pip install -r requirements.txt

# 3. Install Playwright Chromium browser binary
python -m playwright install chromium

# 4. Configure environment variables
cp .env.example .env
# Edit .env and supply your GEMINI_API_KEY
```

### 1.2 Running the Interactive Web Dashboard & Operator Console (Port 3000)
```bash
python -m src.cli serve --port 3000
```
Open **[http://localhost:3000](http://localhost:3000)** in your browser:
- **Discovery Studio:** Run goals with live status, step inspection, and model tracking.
- **Capability Catalog:** Inspect registered artifacts (`checkout_backpack_v1`).
- **Deterministic Replay Runner:** Run replay with custom parameters (`standard_user`, `locked_out_user`).
- **Live Escalation Console:** Session takeover, manual actions (`click`, `type`, `resume`).
- **Evidence Vault:** Browse run history, logs, screenshots, and a11y trees.
- **LegacyBank Proxy:** Embedded non-clean DOM banking portal (`/demo/bank/login`).

### 1.3 Running Deterministic Replay (Zero LLM in Loop)
```bash
# Happy Path Replay (standard_user)
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce

# Business Outcome Handling (locked_out_user)
python -m src.cli replay --artifact checkout_backpack_v1 --params username=locked_out_user password=secret_sauce

# Run in Visible / Headed Browser Window
python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce --no-headless
```

### 1.4 Running LLM Discovery (Real Gemini API)
```bash
python -m src.cli discover --goal "Log in as standard_user with password secret_sauce, add Sauce Labs Backpack to cart, complete checkout to overview page, report the total" --url https://www.saucedemo.com
```

### 1.5 Running Human Escalation & Takeover Simulation
```bash
python -m src.cli escalate-test
```

### 1.6 Running Test Suite
```bash
# Run all 15 unit and integration tests (100% offline, zero API required)
pytest tests/ -v
```

---

## 2. Basic Structure

### 2.1 Repository Directory Map
```text
├── artifacts/
│   └── checkout_backpack_v1.json    # Versioned, typed Capability Artifacts
├── docs/
│   └── build-brief.md                # Source of truth specification & build plan
├── evidence/                         # Per-run JSONL audit logs, screenshots, a11y dumps
│   ├── demo_discovery_run/           # Discovery transcript & log proof
│   ├── demo_replay_happy_path/       # Happy path replay proof
│   ├── demo_replay_locked_out_user/  # Business outcome replay proof
│   └── escalation_demo/              # Human takeover & resume audit log
├── guardrails/
│   └── allowlist.yaml                # Permitted domains & action whitelist
├── src/
│   ├── agent/                        # LLM Discovery Loop (Gemini 2.5 Flash / 3 Flash)
│   │   ├── loop.py                   # Observe -> Decide -> Act loop
│   │   ├── model_client.py           # Gemini SDK client with fallback & 429 retry
│   │   ├── observer.py               # Accessibility tree perceiver
│   │   └── tools.py                  # Structured function declarations schema
│   ├── artifact/                     # Pydantic v2 Schema & Artifact Recorder
│   │   ├── recorder.py               # Compiles transcript to CapabilityArtifact
│   │   └── schema.py                 # Core Pydantic models (CapabilityArtifact, Step, etc.)
│   ├── escalation/                   # Human Takeover & Live Session Transfer
│   │   ├── handoff.py                # Pause/Resume coordinator on same CDP session
│   │   └── operator_cli.py           # Interactive operator console
│   ├── evidence/                     # Structured JSONL logging & asset capture
│   │   ├── capture.py                # Screenshot and a11y JSON dump helpers
│   │   └── logger.py                 # PII/Secret-redacting logger
│   ├── guardrails/                   # Security, Policy & Redaction
│   │   ├── allowlist.py              # Domain & action whitelisting enforcement
│   │   ├── redactor.py               # Password & API key redaction (****)
│   │   └── risk.py                   # Action risk tiering (safe / reversible / irreversible)
│   ├── replay/                       # Deterministic Execution Engine (Strictly ZERO LLM)
│   │   ├── executor.py               # Deterministic execution runner & assertions
│   │   ├── locators.py               # Multi-strategy locator resolver with fallbacks
│   │   └── outcomes.py               # Error taxonomy & business outcome matcher
│   ├── web/                          # FastAPI Backend & Glassmorphic Web Dashboard
│   │   ├── app.py                    # REST APIs & Embedded LegacyBank Demo
│   │   └── static/index.html         # Single-page interactive UI (Port 3000)
│   └── cli.py                        # Unified command-line interface entry point
├── tests/                            # Comprehensive Pytest test suite
│   ├── test_allowlist.py
│   ├── test_api.py
│   ├── test_redactor.py
│   ├── test_replay.py
│   ├── test_risk.py
│   └── test_schema.py
├── .env                              # Local environment configuration (gitignored)
├── .env.example                      # Configuration template
├── .gitignore                        # Git exclusion rules
├── AGENTS.md                         # Rules of engagement and engineering constraints
├── README.md                         # Public repository overview
├── REPORT.md                         # 7-heading architecture design write-up
└── requirements.txt                  # Python dependencies
```

### 2.2 Core Architectural Invariants
1. **Model Discovers, Replay Executes:** `src/replay/` NEVER imports Gemini or uses an LLM. Replay is 100% deterministic rule-based execution.
2. **Universal Allowlist:** Every single browser interaction (both in discovery and replay) is verified against `guardrails/allowlist.yaml` prior to execution.
3. **Secret Redaction:** Any parameter marked `secret=True` or matching sensitive keys is redacted as `****` across all logs and transcripts.
4. **Live Session Takeover:** Escalation operates on the **same live Playwright browser page**, preserving session tokens, form state, and cookies.

---

## 3. Fix Issues / Troubleshooting

### 3.1 Gemini API Rate Limits (`429 RESOURCE_EXHAUSTED`)
- **Symptom:** Discovery hits Google AI Studio Free Tier rate limit (5 requests per minute).
- **Resolution:** The system includes built-in exponential backoff in `src/agent/model_client.py`. When a 429 response is encountered, it automatically pauses for 12–15 seconds and retries across both `gemini-2.5-flash` and `gemini-3-flash-preview`.
- **Alternative:** If running offline, you do not need Gemini at all: deterministic replay (`python -m src.cli replay ...`) and tests (`pytest tests/`) execute without any API calls.

### 3.2 Windows Console Encoding (`UnicodeEncodeError: 'charmap' codec`)
- **Symptom:** Unicode characters (e.g. `✓`) fail on Windows PowerShell when stdout is set to `cp1252`.
- **Resolution:** All CLI print statements use standard ASCII tags (`[SUCCESS]`, `[ERROR]`, `>>`) rather than bare Unicode symbols, ensuring clean cross-platform compatibility across Windows, Linux, and macOS.

### 3.3 Port 3000 Already in Use
- **Symptom:** `error: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 3000)`.
- **Resolution:** Either specify a different port:
  ```bash
  python -m src.cli serve --port 3001
  ```
  Or stop the existing background process using `manage_task` or Windows PowerShell:
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess | Stop-Process
  ```

### 3.4 Missing Playwright Browser Binaries
- **Symptom:** `playwright._impl._errors.Error: Executable doesn't exist at ...`
- **Resolution:** Run:
  ```bash
  python -m playwright install chromium
  ```

### 3.5 Element Locator Not Found During Replay
- **Symptom:** Step fails with `LOCATOR_NOT_FOUND`.
- **Resolution:**
  1. Check if the failure is actually an upstream business condition (e.g. `USER_LOCKED_OUT`), which the engine classifies automatically under `known_outcomes`.
  2. Inspect the locator fallback chain in `artifacts/checkout_backpack_v1.json`: ensure `strategy: "role"` has a fallback to `strategy: "text"` or `strategy: "css"`.

---

## 4. Environment Variables & `.env` Verification

The following variables are supported in `.env`:

| Variable | Required? | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | **Required for Discovery only** | None | Google AI Studio API key (from https://aistudio.google.com/). *Not required for replay or tests.* |
| `PORT` | Optional | `3000` | Port for the Web Dashboard & API server. |
| `HEADLESS` | Optional | `true` | Set `false` to open a visible browser window for debugging. |
| `ALLOWLIST_FILE` | Optional | `guardrails/allowlist.yaml` | Path to the security allowlist YAML configuration. |
| `LOG_LEVEL` | Optional | `INFO` | Application log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `GEMINI_PRIMARY_MODEL` | Optional | `gemini-2.5-flash` | Primary discovery LLM model ID. |
| `GEMINI_SECONDARY_MODEL` | Optional | `gemini-3-flash-preview` | Fallback discovery LLM model ID. |

### Security Check
- `.env` is listed in `.gitignore` and is **never committed** to git.
- All secrets are redacted as `****` in transcripts, logs, and evidence files.
