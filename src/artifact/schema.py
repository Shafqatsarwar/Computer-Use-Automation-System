"""Artifact schema definitions for Computer-Use Automation System.

This is the central contract crossing serialization boundaries:
- CapabilityArtifact: versioned, reusable, reviewable capability
- Step, Locator, InputParam, OutputField, KnownOutcome
- ReplayResult: structured output contract from deterministic replay
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


class Locator(BaseModel):
    """Multi-strategy element locator with explicit fallback chain."""
    strategy: Literal["role", "text", "css"]
    role: str | None = None  # e.g. "button", "textbox"
    name: str | None = None  # accessible name e.g. "Login"
    css: str | None = None   # last-resort CSS fallback
    fallback: Locator | None = None


class Step(BaseModel):
    """An individual discrete action in a capability workflow."""
    id: str
    action: Literal["navigate", "click", "type", "wait_for", "read"]
    locator: Locator | None = None
    value_param: str | None = None  # references an input_param NAME, NEVER a literal secret
    risk: Literal["safe", "reversible", "irreversible"] = "safe"
    checkpoint: str | None = None    # e.g. "url_contains:/cart.html" or "text_visible:Products"


class InputParam(BaseModel):
    """Typed input parameter required by a capability."""
    name: str
    type: Literal["string", "int", "bool"] = "string"
    required: bool = True
    secret: bool = False  # true for password/sensitive fields -> redacted in logs
    description: str = ""
    default: str | None = None


class OutputField(BaseModel):
    """Typed output extracted upon successful checkpoint verification."""
    name: str
    type: Literal["string", "int", "bool"] = "string"
    extract_from: Locator


class KnownOutcome(BaseModel):
    """Rule matching known runtime business conditions or failures."""
    match: str  # e.g. "text_contains:Epic sadface: Sorry, this user has been locked out."
    classification: Literal["business_outcome", "recoverable", "hard_failure"]
    outcome_code: str  # e.g. "USER_LOCKED_OUT"
    message: str


class CapabilityArtifact(BaseModel):
    """The agent-invocable, versioned, replayable capability artifact."""
    id: str
    version: int = 1
    name: str
    description: str
    target_app: str
    entry_url: str
    input_params: list[InputParam] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    outputs: list[OutputField] = Field(default_factory=list)
    success_checkpoint: str
    known_outcomes: list[KnownOutcome] = Field(default_factory=list)
    created_from_run_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["draft", "approved"] = "draft"


class ReplayResult(BaseModel):
    """Deterministic replay execution result contract."""
    status: Literal["success", "business_outcome", "hard_failure"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    outcome_code: str | None = None
    step_index: int | None = None
    expected: str | None = None
    observed: str | None = None
    evidence_path: str = ""
    message: str = ""
