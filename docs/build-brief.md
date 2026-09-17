# Computer-Use Automation System — Build Brief for Antigravity Agent

**Purpose of this document:** hand this whole file to your coding agent as the project brief for the interface.ai take-home ("Computer-Use Automation System"). Every choice below is a real, working decision — not a placeholder — so the agent can start building immediately instead of asking you to decide things. Section 11 is the literal, ordered task list; give the agent that section and let it work top to bottom, showing you a diff before it runs the real LLM discovery step (Step 7).

---

## 1. Target Application — Decided: Sauce Demo

**URL:** `https://www.saucedemo.com`

**Why this, specifically, and not a guess:**
- It's a public site *built and maintained specifically for test-automation practice* — automating it is expected use, not a ToS violation.
- It has a real non-trivial multi-step flow that matches the brief's example almost verbatim: log in → find an item → add to cart → checkout → reach the review/overview page.
- It ships with **known test accounts that produce real, verifiable error/business-outcome states** — this is the hard part of the assignment (Section 3.3), and Sauce Demo hands it to you for free:

| Username | Password | Result |
|---|---|---|
| `standard_user` | `secret_sauce` | Logs in normally → Products page |
| `locked_out_user` | `secret_sauce` | Login blocked, error text: `Epic sadface: Sorry, this user has been locked out.` |
| `problem_user` | `secret_sauce` | Logs in, but UI has intentional bugs (broken images, cart glitches) — good for testing checkpoint robustness |
| `performance_glitch_user` | `secret_sauce` | Logs in, but with a multi-second artificial delay — good for testing "slow/transient" handling |
| (empty username) | — | Error text: `Epic sadface: Username is required` |

The login error is rendered in an element with class `error-message-container` inside an `<h3>` tag — verified, real, stable. This gives you a genuine "business outcome vs. failure" test case without inventing one.

**Discovery goal to use:** *"Log in as the given user, add the Sauce Labs Backpack to the cart, proceed through checkout with placeholder shipping info, and reach the order review/overview screen; report the item total."*

**Legacy-surface stretch reference (design-only, do not build):** for REPORT.md Section 4 (Heterogeneity), reference `the-internet.herokuapp.com` (iframes, framesets, table layouts, no test IDs) as the credible example of what your abstraction would need to handle for a legacy surface — you don't need to implement against it.

---

## 2. Tech Stack — Decided

- **Python 3.11+**
- **Playwright for Python** — `pip install playwright && playwright install chromium`. Real, current, actively maintained. Locate elements by **accessibility role + name** (`page.get_by_role("button", name="Login")`), not raw CSS — this is deliberately the same signal that would work against a legacy app or a desktop app's accessibility tree, per the brief's "bias toward no-clean-DOM" guidance.
- **Google Gemini API via the `google-genai` SDK** for the discovery loop, using **function calling** so the model's output is a structured action, not free text you have to parse.
  - `pip install google-genai`
  - `GEMINI_API_KEY` from Google AI Studio (free tier — no billing setup needed to run this project).
  - **Primary model: `gemini-2.5-flash`** — stable (not preview), explicitly positioned by Google for "price-performance, high volume, agentic use cases," which is exactly this workload: one structured tool call per turn, many turns.
  - **Secondary/fallback model: `gemini-3-flash-preview`** — newer generation, higher reasoning quality, used automatically if the primary model call fails or the loop gets stuck on an ambiguous page (see retry logic below). It's a preview model, so it's the *fallback*, not the default, to keep the common path on the more stable, higher-quota model.
  - Confirm both exact model ID strings in Google AI Studio at build time — Google's model names shift fairly often and the agent should treat the strings above as the starting point, not gospel.
- **Pydantic v2** for the artifact schema — this is the piece the evaluators weight most heavily, so it gets built first and gets real validation, not just type hints.
- **Plain `logging` with a JSON formatter** for evidence — no external logging service needed.
- **Single process, synchronous, no queue** — deliberate, matches the brief's explicit instruction not to build scaling infrastructure prematurely.

---

## 3. Repo Layout

```
computer-use-automation/
  README.md
  REPORT.md
  requirements.txt
  .env.example
  .gitignore
  src/
    agent/
      loop.py            # observe -> decide -> act loop (LLM-driven, discovery only)
      tools.py            # function-declaration schema passed to Gemini
      model_client.py     # wraps google-genai, handles primary/secondary fallback
      observer.py         # accessibility-tree snapshot builder
    artifact/
      schema.py           # Pydantic Capability artifact models
      recorder.py         # transcript -> CapabilityArtifact converter
    replay/
      executor.py         # deterministic replay engine (no LLM)
      locators.py          # locator resolution + fallback strategy
      outcomes.py          # known-outcome / error-taxonomy matcher
    guardrails/
      allowlist.py
      allowlist.yaml
      risk.py
    escalation/
      handoff.py           # pause / resume / control-transfer model
      operator_cli.py      # minimal real operator console (mocked UI, real mechanism)
    evidence/
      logger.py
      capture.py            # screenshot + accessibility snapshot dump
    cli.py                  # `discover` and `replay` entrypoints
  artifacts/                 # saved capability artifacts, JSON, versioned
  evidence/                  # per-run logs, screenshots, snapshots
  tests/
```

---

## 4. Artifact Schema — the load-bearing piece

Build this **before** the agent loop or the replay engine — both other pieces serialize into and out of this.

```python
from pydantic import BaseModel
from typing import Literal
from datetime import datetime

class Locator(BaseModel):
    strategy: Literal["role", "text", "css"]
    role: str | None = None       # e.g. "button", "textbox"
    name: str | None = None       # accessible name, e.g. "Login"
    css: str | None = None        # last-resort fallback only
    fallback: "Locator | None" = None

class Step(BaseModel):
    id: str
    action: Literal["navigate", "click", "type", "wait_for", "read"]
    locator: Locator | None = None
    value_param: str | None = None   # references an input_param NAME, never a literal secret
    risk: Literal["safe", "reversible", "irreversible"]
    checkpoint: str | None = None     # e.g. "url_contains:/cart.html"

class InputParam(BaseModel):
    name: str
    type: Literal["string", "int", "bool"]
    required: bool
    secret: bool = False              # true for password-like params -> always redacted in logs
    description: str

class OutputField(BaseModel):
    name: str
    type: Literal["string", "int", "bool"]
    extract_from: Locator

class KnownOutcome(BaseModel):
    match: str                        # e.g. "text_contains:Epic sadface: Sorry, this user has been locked out."
    classification: Literal["business_outcome", "recoverable", "hard_failure"]
    outcome_code: str                 # e.g. "USER_LOCKED_OUT"
    message: str

class CapabilityArtifact(BaseModel):
    id: str
    version: int
    name: str
    description: str
    target_app: str
    entry_url: str
    input_params: list[InputParam]
    steps: list[Step]
    outputs: list[OutputField]
    success_checkpoint: str
    known_outcomes: list[KnownOutcome]
    created_from_run_id: str
    created_at: datetime
    status: Literal["draft", "approved"] = "draft"
```

`status` matters: replay of any step marked `risk="irreversible"` should refuse to run unattended unless the artifact is `approved` — that's your safety story for Section 3.4, made concrete instead of hand-waved.

---

## 5. Error Taxonomy — concrete, for this target

Wire this table directly into `known_outcomes` on the checkout artifact:

| Match condition | Classification | Outcome code |
|---|---|---|
| `text_contains: "Epic sadface: Sorry, this user has been locked out."` | `business_outcome` | `USER_LOCKED_OUT` |
| `text_contains: "Epic sadface: Username is required"` | `business_outcome` | `VALIDATION_ERROR_USERNAME` |
| `text_contains: "Epic sadface: Password is required"` | `business_outcome` | `VALIDATION_ERROR_PASSWORD` |
| Playwright locator not found within timeout, fallback also not found | `recoverable` → retry once with 2s backoff, then escalate | `LOCATOR_NOT_FOUND` |
| URL after a step doesn't match any known page for that step | `hard_failure` | `UNEXPECTED_STATE` |

This is exactly the "expected business outcome vs. recoverable vs. hard failure" distinction the brief calls out as the most common design mistake to avoid conflating.

---

## 6. Discovery Loop — concrete mechanics

1. **Observe:** call `page.accessibility.snapshot()`, trim it to interactive/visible nodes (role, name, value), attach current URL + title. This is your "no clean DOM" answer — it would work identically against a legacy app or an OS-level accessibility tree.
2. **Decide:** send the trimmed snapshot + goal + step history to Gemini via `google-genai`'s function-calling interface, with a **fixed set of function declarations**: `click(role, name)`, `type(role, name, text)`, `navigate(url)`, `finish(success: bool, reason: str)`. The model must return exactly one function call per turn.

   Concrete call shape (`agent/model_client.py`):

   ```python
   from google import genai
   from google.genai import types

   client = genai.Client()  # reads GEMINI_API_KEY from env

   PRIMARY_MODEL = "gemini-2.5-flash"
   SECONDARY_MODEL = "gemini-3-flash-preview"

   TOOLS = [
       types.Tool(function_declarations=[
           {
               "name": "click",
               "description": "Click an interactive element identified by its accessibility role and accessible name.",
               "parameters": {
                   "type": "object",
                   "properties": {
                       "role": {"type": "string"},
                       "name": {"type": "string"},
                   },
                   "required": ["role", "name"],
               },
           },
           {
               "name": "type",
               "description": "Type text into a field identified by its accessibility role and accessible name.",
               "parameters": {
                   "type": "object",
                   "properties": {
                       "role": {"type": "string"},
                       "name": {"type": "string"},
                       "text": {"type": "string"},
                   },
                   "required": ["role", "name", "text"],
               },
           },
           {
               "name": "navigate",
               "description": "Navigate the browser to an absolute URL.",
               "parameters": {
                   "type": "object",
                   "properties": {"url": {"type": "string"}},
                   "required": ["url"],
               },
           },
           {
               "name": "finish",
               "description": "Call this when the goal is met or cannot be met.",
               "parameters": {
                   "type": "object",
                   "properties": {
                       "success": {"type": "boolean"},
                       "reason": {"type": "string"},
                   },
                   "required": ["success", "reason"],
               },
           },
       ])
   ]

   def decide(prompt: str, model: str = PRIMARY_MODEL):
       try:
           response = client.models.generate_content(
               model=model,
               contents=prompt,
               config=types.GenerateContentConfig(tools=TOOLS),
           )
       except Exception:
           if model == PRIMARY_MODEL:
               return decide(prompt, model=SECONDARY_MODEL)  # one fallback hop, then let it raise
           raise
       # If the primary model returns no function call (ambiguous page, chose to just respond in text),
       # retry once against the secondary model before giving up on this turn.
       if not response.function_calls and model == PRIMARY_MODEL:
           return decide(prompt, model=SECONDARY_MODEL)
       return response
   ```

   Fallback rule, in plain terms: **`gemini-2.5-flash` runs every turn by default.** It only hands off to `gemini-3-flash-preview` for that single turn when the primary call either errors outright (rate limit, transient API failure) or comes back without a function call at all — i.e., the page state was ambiguous enough that the cheaper model didn't commit to an action. Log which model actually produced each step's decision in the transcript (`model_used` field) — this is also good evidence for your write-up.

3. **Act:** execute the returned function call via Playwright; every action is checked against the allowlist (Section 8) before execution.
4. **Record:** append `{step_index, actor: "agent", action, locator_used, model_used, result, timestamp}` to the transcript.
5. **Stop condition:** `finish` called, `max_steps` (e.g. 15) reached, or wall-clock timeout — whichever first.
6. On successful `finish`: hand the transcript to `recorder.py`, which resolves each action's locator (already captured at action time), promotes any literal string that matches a declared input (username/password) into an `input_param` reference, strips raw screenshots/tokens, and writes a `CapabilityArtifact` to `artifacts/`.

**This step (running discovery once, for real, against the live site) is the one part of this project that cannot be mocked or guessed** — the brief is explicit that this is non-negotiable.

---

## 7. Replay Engine — concrete mechanics

1. Load the artifact by `id` + `version`; validate supplied input params against the Pydantic schema — a mismatch is a `hard_failure: INVALID_INPUT` *before* the browser even opens.
2. For each step: resolve the primary locator; on timeout, try `fallback`; if still not found, classify per Section 5's table (checking `known_outcomes` against current page text *first*, since a missing locator is often really a business outcome — e.g. no "Checkout" button because login itself failed).
3. After every step with a `checkpoint`, assert it. Failure triggers the same known-outcome check before declaring `hard_failure`.
4. Return a single structured result:

```python
class ReplayResult(BaseModel):
    status: Literal["success", "business_outcome", "hard_failure"]
    outputs: dict
    outcome_code: str | None
    step_index: int | None
    expected: str | None
    observed: str | None
    evidence_path: str
```

No LLM call anywhere in this file — that's the whole point of the artifact. Gemini is only ever invoked from `agent/`, never from `replay/`.

---

## 8. Safety & Guardrails — concrete

- **`allowlist.yaml`:** permitted domain = `saucedemo.com` only; permitted actions = `navigate, click, type, read`. No `upload_file`, no `download`. Every action — in *both* discovery and replay — is checked against this before it touches the browser. A violation is an immediate `hard_failure: POLICY_VIOLATION`, no retry, no exception.
- **Risk classification (`risk.py`):** `read`/`navigate` → `safe`; `click`/`type` that doesn't submit → `reversible`; anything matching `/place order|submit|confirm|finish/i` on the acted-on element's accessible name → `irreversible`. Irreversible steps in an artifact whose `status` is still `"draft"` always pause for human confirmation in replay, regardless of anything else.
- **Redaction:** any `InputParam` with `secret=True` (password fields) is logged as `"****"` — never the raw value — in every log line and every artifact. Credentials are never hardcoded into an artifact; they're supplied at replay time from environment variables (`.env`, gitignored). This applies equally to your `GEMINI_API_KEY` — never printed, never logged.

---

## 9. Escalation & Handoff — concrete, real mechanism

- Launch the browser with `headless=False` and keep it in the **same Playwright `Page` object** for the whole run — discovery, replay, and any human handoff all operate on that one live session, never a fresh one.
- `handoff.py` triggers escalation on: a replay `hard_failure`, discovery hitting `max_steps` without `finish`, or any `irreversible` step on a `draft` artifact.
- On trigger: automation stops issuing commands and calls `operator_cli.py` — a minimal terminal console (the mocked part, deliberately) that:
  1. prints the escalation reason, current URL, and the trimmed accessibility snapshot;
  2. accepts operator commands: `click <role> <name>`, `type <role> <name> <text>`, or `manual` (since the window is visible with `headless=False`, the human can literally take the mouse/keyboard on the real OS window);
  3. on `resume`, control returns to the loop, which re-observes the page and continues from where it left off.
- Every operator action is logged with `actor: "human"`, distinct from `actor: "agent"` steps — this is what makes the handoff auditable rather than a black box.
- **Prove this with a real run:** deliberately break one locator in the checkout artifact so replay hits `LOCATOR_NOT_FOUND`, escalates, you issue one manual `click` command through the console to fix it, then `resume` — capture the whole thing in `/evidence/`.

---

## 10. Evidence

- `evidence/<run_id>/log.jsonl` — one JSON line per step: `actor`, `action`, `locator`, `model_used` (discovery only), `result`, `timestamp`.
- `evidence/<run_id>/screenshots/step_<n>.png` — on every `business_outcome` or `hard_failure`, plus one final screenshot regardless of outcome.
- `evidence/<run_id>/accessibility_snapshot_<n>.json` — on every failure.

You need at minimum: one discovery run's evidence, one clean replay's evidence, one replay that hits `USER_LOCKED_OUT` (business outcome, not a crash), and one replay that triggers the escalation/handoff flow.

---

## 11. Ordered Build Plan — give this to the agent literally, step by step

1. Scaffold the repo layout from Section 3. Write `requirements.txt` (`playwright`, `google-genai`, `pydantic`, `python-dotenv`). Run `playwright install chromium`.
2. Write `artifact/schema.py` exactly per Section 4 — this is the contract everything else depends on. Get this reviewed/correct before writing anything that uses it.
3. Write `guardrails/allowlist.py`, `guardrails/risk.py`, and `guardrails/allowlist.yaml` per Section 8 — small, self-contained, needed by both the loop and the replay engine.
4. Write `agent/observer.py`: a function taking a Playwright `Page`, returning a trimmed JSON accessibility snapshot (role, name, value per interactive node).
5. Write `agent/tools.py` and `agent/model_client.py`: the function-declaration schema and the primary/secondary `google-genai` client wrapper from Section 6, step 2.
6. Write `agent/loop.py`: the observe → decide → act loop. Every action passes through the allowlist check first. Log every step, including which model produced the decision. Stop on `finish`, `max_steps`, or timeout.
7. **Run discovery for real** against `https://www.saucedemo.com` with the goal from Section 1, using `standard_user` / `secret_sauce`. Command: `python -m src.cli discover --goal "log in, add Sauce Labs Backpack to cart, complete checkout to the overview page, report the total" --url https://www.saucedemo.com`. Confirm the transcript and evidence are sane, and that `model_used` shows `gemini-2.5-flash` for the normal steps. **This is the one step that must be a real LLM call — do not mock or fabricate it.**
8. Write `artifact/recorder.py`: convert the successful transcript into a `CapabilityArtifact`, save to `artifacts/checkout_backpack_v1.json`.
9. Write `replay/locators.py` and `replay/executor.py`: load the artifact, substitute params, execute steps directly via Playwright (no LLM), assert checkpoints per Section 7.
10. Write `replay/outcomes.py`: the known-outcomes matcher from Section 5, wired into the executor so a failed checkpoint checks it before declaring `hard_failure`.
11. Run replay on the happy path: `python -m src.cli replay --artifact checkout_backpack_v1 --params username=standard_user password=secret_sauce`. Confirm deterministic success and correct outputs.
12. Run replay again with `username=locked_out_user` — this produces the required "replay that hits an error/exceptional state" evidence. Confirm it reports `business_outcome / USER_LOCKED_OUT`, not a crash.
13. Write `escalation/handoff.py` and `escalation/operator_cli.py` per Section 9. Deliberately break one locator to force `LOCATOR_NOT_FOUND`, capture the full pause → manual fix → resume cycle as its own evidence run.
14. Write `evidence/logger.py` and `evidence/capture.py` (or fold them in earlier if that's cleaner) — make sure discovery, replay, and escalation all write evidence consistently.
15. Write `README.md`: setup instructions (keys/config needed, e.g. `GEMINI_API_KEY` in `.env`), and the exact demo commands from steps 7 and 11–13.
16. Write `REPORT.md` using the seven required headings (Architecture, Artifact schema, Determinism & error handling, Heterogeneity & multi-tenant, Escalation & handoff, Safety, Cuts). Be explicit about what's cut per Section 12 below and why — including *why Gemini* (free tier, real function-calling support, `gemini-2.5-flash`'s explicit agentic-use positioning) if asked to defend the model choice.
17. Final pass: confirm `.env` is gitignored, confirm nothing in `/evidence/` contains a raw password or your API key (spot-check the JSON logs), push to a **public** GitHub repo, email the link to `assignments@interface.ai`.

---

## 12. What to Cut, Explicitly

- No multi-tenant plumbing, no queue/service split, no real desktop-app support — design story only, in REPORT.md Section 4, as the brief explicitly says not to build this.
- The operator console is a terminal CLI and/or interactive web UI on port 3000; the pause/resume/control-transfer *mechanism* underneath it is real, which is what's actually being evaluated.
- Skip stretch goals (Section 8 of the brief) entirely unless the core (Sections 1–11 above) is fully working with time to spare.
