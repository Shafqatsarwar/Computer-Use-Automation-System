# AGENTS.md

This file tells any AI coding agent (Antigravity, or any other agent operating in this repo) how to work here. Read this in full before writing or running anything. It does not replace the project spec — it governs *how* you execute it.

**Source of truth for what to build:** `docs/build-brief.md` (the file titled "Computer-Use Automation System — Build Brief for Antigravity Agent"). Copy that file into this repo at that path before starting. Everything in this file assumes it's present and has already been read.

---

## 1. Project Snapshot

This repo is a take-home assignment for interface.ai: a system that (1) uses an LLM to complete a goal by driving a real web UI, (2) records the successful run as a typed, reusable "capability" artifact, (3) replays that artifact deterministically with no LLM involved, (4) escalates to a human when it can't safely proceed, and (5) enforces safety guardrails throughout. Target app: Sauce Demo (`https://www.saucedemo.com`). LLM: Google Gemini, via the `google-genai` SDK — `gemini-2.5-flash` as the default model, `gemini-3-flash-preview` as a single-turn fallback. Full details, schema, and the exact ordered build steps are in `docs/build-brief.md` Section 11 — follow that order. Don't reorder it, don't skip ahead, don't start two sections in parallel.

---

## 2. Setup & Environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then fill in GEMINI_API_KEY
```

Required env vars (`.env`, gitignored — never commit this file):
- `GEMINI_API_KEY`

If you need to run anything without live services (no browser, no API), that path is: load an existing artifact from `artifacts/` and call the replay engine's `validate_only` mode if implemented, or just import `artifact/schema.py` and validate a sample JSON. There is no other offline mode — discovery and replay both require a live browser; replay does not require the Gemini API.

---

## 3. Commands You Will Actually Run

```bash
# Discovery (LLM-driven, real browser, real API calls — never mock this)
python -m src.cli discover --goal "<goal text>" --url https://www.saucedemo.com

# Replay (deterministic, no LLM)
python -m src.cli replay --artifact <artifact_id> --params key=value key2=value2

# Tests
pytest tests/
```

---

## 4. Conventions

- Python 3.11+, type hints everywhere, Pydantic v2 for anything that crosses a serialization boundary (artifacts, replay results, transcripts).
- No bare `except:` — catch specific exceptions or `Exception` with a comment explaining why it's broad.
- Every function that touches the browser, the allowlist, or the Gemini API gets a docstring stating its inputs/outputs and what it does on failure. This is not optional — the evaluators read this code.
- Keep `agent/` (LLM-in-the-loop) and `replay/` (no LLM, ever) in separate modules with no import from `replay/` into anything that calls Gemini. If you find yourself importing the model client into `replay/`, stop — that's a design violation of the whole point of the artifact.
- Filenames and JSON field names: `snake_case`. Artifact IDs: `<goal_slug>_v<n>`, e.g. `checkout_backpack_v1`.

---

## 5. Hard Rules — Do Not Violate These

1. **The discovery run must be a real Gemini API call against the real live site.** Never fabricate a transcript, never hardcode a fake LLM response to "save time." If Gemini access isn't working, stop and say so — don't route around it.
2. **Replay never calls Gemini, ever, under any circumstance.** No LLM in the decision loop for replay is the entire premise of the artifact. If you're tempted to add an "LLM fallback" inside `replay/executor.py`, that belongs in a clearly separate, explicitly-flagged assisted-recovery path per the brief's stretch goals — not silently inside the core replay path.
3. **Never act outside the allowlist** (`guardrails/allowlist.yaml` — `saucedemo.com` only, actions limited to `navigate, click, type, read`). This check runs before every single browser action in both discovery and replay, no exceptions for "just testing."
4. **Never write secrets or raw sensitive values into logs, artifacts, or evidence.** Passwords are redacted as `****` at the point of logging, not after the fact. The `GEMINI_API_KEY` is never printed or logged, period.
5. **Never commit `.env`, real credentials, or anything under `/evidence/` that hasn't been checked for leaked secrets.** Run a grep for `secret_sauce` and your API key prefix over `/evidence/` and `/artifacts/` before every commit as a sanity check.
6. **Irreversible steps (`risk: "irreversible"`) never run unattended on a `draft` artifact.** That's a policy check in the replay engine, not a comment — write the test for it.
7. **Don't automate against anything other than `saucedemo.com`** for this project, even "just to try something." The allowlist exists so this is enforced in code, not just in intent.

---

## 6. Order of Work

Follow `docs/build-brief.md` Section 11 exactly, in order, 1 through 17. Do not write the replay engine before the artifact schema is finalized. Do not write the escalation console before replay works on the happy path. Each numbered step in that section is a checkpoint — after finishing one, briefly state what was built and what evidence (if any) it produced, before moving to the next.

**Step 7 of that plan (the live discovery run) is a hard stop-and-confirm point.** Before running it, show the goal string, the target URL, and the model config you're about to use. After running it, show the resulting transcript summary and confirm `model_used` fields are populated before writing the recorder.

---

## 7. Definition of Done, Per Phase

- **Schema (build-brief Section 4):** `artifact/schema.py` imports cleanly, and a hand-written sample `CapabilityArtifact` JSON round-trips through `model_validate_json` / `model_dump_json` without errors.
- **Discovery loop:** produces a transcript with at least one real Gemini API response recorded, ends in `finish(success=True)`, and evidence files exist in `evidence/<run_id>/`.
- **Artifact recorder:** the saved artifact in `artifacts/` validates against the schema and contains no literal secret values in `value_param` fields (only param *names*).
- **Replay engine:** the happy-path replay (`standard_user`) succeeds deterministically on at least two consecutive runs, and the `locked_out_user` replay returns `status: "business_outcome"`, `outcome_code: "USER_LOCKED_OUT"` — not an exception, not a crash.
- **Escalation:** a deliberately broken locator triggers the operator console, a manual operator action is logged with `actor: "human"`, and the run resumes and completes after `resume`.
- **Docs:** `README.md` runs verbatim if someone follows it from a clean checkout; `REPORT.md` has all seven required headings filled in, not stubbed.

---

## 8. When You're Uncertain

If the brief or this file doesn't cover a decision you're facing, make the smallest reasonable decision that doesn't contradict Section 5's hard rules, note it inline as a comment (`# DECISION: ...`), and mention it in the relevant `REPORT.md` section rather than stopping to ask — unless the uncertainty is about one of the Section 5 hard rules themselves, in which case stop and ask before proceeding.

---

## 9. Git Hygiene

- One repo, single `main` branch is fine for this project — no need for a branching strategy.
- Commit at each numbered step in Section 6 above, not as one giant commit at the end. Commit messages reference the step number, e.g. `Step 9: replay executor + locator fallback`.
- `.gitignore` must include `.env`, `.venv/`, `__pycache__/`, and any `*.png`/`*.json` under `/evidence/` that you decide not to keep as committed proof — but the evidence required by the brief (Section 6, deliverable 3) does get committed; don't gitignore that away.
