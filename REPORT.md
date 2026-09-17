# System Design Report — Computer-Use Automation System

> **interface.ai Engineering Take-Home Submission**  
> Candidate System Architecture & Design Specification

---

## 1. Architecture

### 1.1 Architectural Overview & Core Decoupling
The core premise of this system is that **the model discovers, the artifact becomes the reusable capability, and deterministic replay is the production execution path**.

```text
[Goal + Entry URL]
       ↓
LLM Discovery Agent (Google Gemini 2.5 Flash / Gemini 3 Flash Preview fallback)
       ↓  (Perceives via A11y Tree + Role/Name perception, Executes via Playwright)
Discovery Transcript (JSONL + Step History)
       ↓
Artifact Recorder (Parameterization + Error Taxonomy Injection + Risk Tagging)
       ↓
Capability Artifact (.json, Pydantic v2 Contract)
       ↓
Deterministic Replay Engine (Strictly ZERO LLM In Loop, Sub-Second, Rule-Driven)
       ↓
  ├── Success: Checkpoint Verified, Outputs Extracted
  ├── Business Outcome: Handled cleanly (e.g. USER_LOCKED_OUT)
  ├── Recoverable: Fallback retry / Operator assistance
  └── Hard Failure: Safe halt + Rich evidence dump
       ↓
Human Escalation & Live Session Transfer (Same CDP Session Takeover & Resume)
```

### 1.2 Boundary Isolation
To guarantee stability, cost efficiency, and predictability in production banking environments:
- **`src/agent/` (LLM in the loop):** Used strictly during the discovery phase. Uses Gemini function calling (`click`, `type`, `navigate`, `finish`) to map a natural-language goal to concrete UI interactions.
- **`src/replay/` (Zero LLM):** Contains no model imports or LLM dependencies. It executes compiled artifacts deterministically using hierarchical locators and assertions.
- **`src/guardrails/` (Universal safety):** Intercepts every single browser action in both discovery and replay before it touches the browser engine.

### 1.3 Why Google Gemini & Playwright
- **`gemini-2.5-flash`:** Google's dedicated model for high-throughput, low-latency agentic function calling, offering fast turnarounds and precise structured parameter generation.
- **`gemini-3-flash-preview` (Fallback):** Invoked automatically on ambiguous states or transient API errors for higher reasoning depth.
- **Playwright with Accessibility Tree Targeting:** Rather than brittle CSS selectors, automation targets the browser's accessibility tree (`getByRole`, accessible name, value). This mirrors how assistive technologies and human operators perceive UI surfaces, providing direct transferability to desktop accessibility APIs (e.g., Win32 UI Automation / AX).

---

## 2. Artifact Schema

### 2.1 The Capability Contract
The `CapabilityArtifact` (defined in `src/artifact/schema.py`) serves as a versioned, typed contract between the discovery phase and calling AI agents.

```python
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

### 2.2 Design Rationale
1. **Separation of Parameters from Actions:** Literal values discovered during interactive exploration (e.g., `standard_user`, `secret_sauce`, `$29.99`) are replaced by `value_param: "username"` references. This allows the capability to be parameterized for any member or account without altering step logic.
2. **Multi-Strategy Locators with Explicit Fallbacks:** Every target element encapsulates a primary locator and a fallback chain (`role` -> `text` -> `css`).
3. **Explicit Checkpoints per Step:** Steps assert state transitions (e.g., `url_contains:/inventory.html` or `text_visible:Remove`) rather than blindly assuming a click succeeded.
4. **Approval Lifecycle (`status: draft | approved`):** Risky or irreversible steps (`risk="irreversible"`) are gated and refuse to execute unattended on `draft` artifacts without operator approval.

---

## 3. Determinism & Error Handling

### 3.1 Eliminating Non-Determinism
Replay determinism is achieved through:
1. **Explicit Locator Resolution:** The resolver waits for element presence, visibility, and non-zero bounding boxes with configurable timeouts rather than arbitrary sleeps.
2. **Hierarchical Locator Fallbacks:** If UI styling or DOM class names drift, semantic role and accessible text fallbacks ensure uninterrupted targeting.
3. **State Checkpoints:** Every action verifies URL mutations or DOM content assertions before proceeding.

### 3.2 Error Taxonomy: Business Outcomes vs. Failures
Conflating expected domain outcomes with system crashes is a catastrophic architectural flaw in banking automation. The system explicitly separates three runtime states:

| Condition | Match Example | Classification | System Behavior |
|---|---|---|---|
| User account locked out | `Epic sadface: Sorry, this user has been locked out.` | `business_outcome` (`USER_LOCKED_OUT`) | Returns structured outcome with `status: "business_outcome"`. No crash, no retry loop. |
| Missing mandatory field | `Epic sadface: Username is required` | `business_outcome` (`VALIDATION_ERROR_USERNAME`) | Returns structured business validation error to calling agent. |
| Member not found | `Member ID '99999' not found in database` | `business_outcome` (`MEMBER_NOT_FOUND`) | Expected domain response; capability returns cleanly. |
| Transient network delay | Element wait timeout exceeded | `recoverable` (`LOCATOR_NOT_FOUND`) | Evaluates known outcomes first, then applies bounded backoff retry (1 attempt, 2s). |
| Disallowed URL / Action | Navigation outside allowlist | `hard_failure` (`POLICY_VIOLATION`) | Immediate execution termination; audit event logged. |

When an element fails to resolve, the engine inspects the page body against `known_outcomes` *before* declaring a failure, correctly detecting when an absent button is actually caused by an upstream business condition (e.g., login failed).

---

## 4. Heterogeneity & Multi-Tenant

### 4.1 Surface Abstraction (Modern Web, Legacy Web, Desktop)
The system decouples **how we perceive/act on a surface** from **the workflow flow representation**:
- **Unified Perception Model:** Both discovery and replay operate on an abstract accessibility tree (roles, accessible names, values, bounding boxes).
- **Surface Adapter Interface:**
  - `WebModernAdapter`: Playwright Chromium targeting modern SPAs.
  - `WebLegacyAdapter`: Traverses framesets, nested table layouts, and legacy HTML (demonstrated in our synthetic `LegacyBank` portal).
  - `DesktopAdapter` (Design Seam): Bridges to OS-level accessibility APIs (Microsoft UI Automation `UIA` via `pywinauto` / `UIAutomationCore.dll` or macOS Accessibility API) without modifying the `CapabilityArtifact` step model.

### 4.2 Multi-Tenant Reuse & Parameterization
In banking software where hundreds of credit unions use branded instances of the same core vendor product (e.g., Symitar, Fiserv, Jack Henry):
1. **Canonical Parameterized Routes:** Concrete tenant URLs (e.g., `https://tenantA.bank.com/member/12345/account`) normalize to canonical templates (`{{base_url}}/member/{{member_id}}/account`).
2. **Base Artifact + Tenant Delta Overrides:** Base capabilities define universal workflow steps; tenant-specific artifacts only store locator delta overrides (e.g., if Tenant B labels the search button *"Find Customer"* instead of *"Search Member"*):
   ```json
   {
     "base_artifact": "member_lookup_v1",
     "tenant": "credit_union_b",
     "locator_overrides": {
       "step_3": { "strategy": "role", "role": "button", "name": "Find Customer" }
     }
   }
   ```
3. **Drift Detection:** Replay telemetry records locator resolution confidence. When a tenant instance drifts below a confidence threshold (e.g., primary locator fails and resolves via tertiary fallback), an automated re-indexing alert is triggered.

---

## 5. Escalation & Handoff

### 5.1 Stuck Detection & Trigger Conditions
Escalation is triggered automatically when:
1. Replay encounters an unresolvable locator after all fallbacks are exhausted (`LOCATOR_NOT_FOUND`).
2. Discovery hits maximum step limits without reaching a `finish()` checkpoint.
3. An irreversible step (`risk="irreversible"`) is reached on an unapproved (`status="draft"`) artifact.

### 5.2 Same-Session Control Transfer Model
Unlike naive systems that merely snapshot an error and abort, this platform implements **true live session takeover**:
1. **Browser State Preservation:** The automation engine freezes execution on the live Playwright `Page` and context, retaining cookies, session tokens, and active form input values.
2. **Operator Console Interface:** The session state, URL, a11y tree, and failure screenshot are routed to the operator console (available via CLI `python -m src.cli escalate-test` and Web UI at `http://localhost:3000`).
3. **Human Action Injection:** The operator executes manual interactions directly on the live session (`click`, `type`, `navigate`) or physically takes over the visible browser.
4. **Auditable Control Logs:** Every action executed by the operator is tagged with `actor: "human"`, distinguishing operator corrections from autonomous agent steps.
5. **Resume & Continue:** Upon operator command, automation resumes from the current page state, asserts subsequent checkpoints, and completes the workflow.

---

## 6. Safety

### 6.1 Strict Allowlist Enforcement
- **Domain Whitelisting:** Enforced via `guardrails/allowlist.yaml`. Any navigation outside permitted domains (`saucedemo.com`, `localhost`, `127.0.0.1`) triggers an immediate `PolicyViolationError` and halts execution.
- **Action Whitelisting:** Permits only discrete, auditable operations (`navigate`, `click`, `type`, `read`, `wait_for`). Destructive capabilities (`eval`, `script_execution`, `upload_file`, `download`) are blocked at the engine boundary.

### 6.2 Risk Classification & Irreversible Action Gating
Steps are categorized into three risk tiers:
- **`safe`:** Read-only inspections, page navigations.
- **`reversible`:** Form inputs, standard non-submitting button clicks.
- **`irreversible`:** Actions matching `/place order|submit|confirm|finish|pay|transfer/i`.
- **Policy Check:** Irreversible steps on `draft` capabilities are strictly prevented from executing unattended.

### 6.3 Secret & PII Redaction
- Sensitive input parameters marked `secret=True` (passwords, PINs, tokens) are systematically redacted to `****` before log serialization, transcript generation, or artifact storage.
- Environment API keys (`GEMINI_API_KEY`) are masked in all console outputs and excluded from git via `.gitignore`.

---

## 7. Cuts

### 7.1 What Was Deliberately Cut
1. **Premature Distributed Infrastructure:** In accordance with Section 4 & 5 of the evaluation brief, distributed message brokers (Kafka/RabbitMQ), Kubernetes clustering, and multi-tenant SQL database plumbing were excluded in favor of a lean, single-process, highly-testable architecture.
2. **Native OS Desktop Automation Implementation:** The surface abstraction layer and a11y tree perceiver are designed for cross-surface compatibility, but runtime implementation was focused on web surfaces (Sauce Demo and synthetic LegacyBank).
3. **Full WebRTC Video Co-Browsing:** Replaced with a real CDP/Playwright live session transfer mechanism and rich web operator console, fulfilling the handoff requirement without redundant media-streaming infrastructure.

### 7.2 What to Build Next
1. **Automated Cross-Tenant Specialization:** Automated clustering of multi-tenant locator variations from telemetry logs to generate localized artifact deltas.
2. **Single-Step Assisted LLM Recovery:** A bounded, policy-checked LLM fallback invoked strictly on single-step replay locator failures to suggest locator adaptations before human escalation.
3. **Capability OpenAPI Export:** Auto-generating OpenAPI 3.1 specifications and MCP tool definitions from saved `CapabilityArtifact` contracts for direct invocation by external conversational AI agents.
