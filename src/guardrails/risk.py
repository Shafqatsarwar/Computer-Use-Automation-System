"""Risk classification and policy enforcement for Computer-Use Automation System.

Classifies action risk:
- 'safe': read, navigate
- 'reversible': standard clicks, field entry
- 'irreversible': final confirmations, submissions, order placement, payments

Enforces safety policy: irreversible actions on 'draft' artifacts require explicit operator approval.
"""

from __future__ import annotations
import re
from typing import Literal

RiskLevel = Literal["safe", "reversible", "irreversible"]

IRREVERSIBLE_PATTERNS = [
    r"place\s*order",
    r"submit",
    r"confirm",
    r"finish",
    r"pay\b",
    r"complete\s*order",
    r"transfer\b",
    r"delete\b",
]

_IRREVERSIBLE_REGEX = re.compile("|".join(IRREVERSIBLE_PATTERNS), re.IGNORECASE)


def classify_risk(action: str, target_name: str | None = None, role: str | None = None) -> RiskLevel:
    """Classifies an action's risk level based on action type and target element semantics."""
    action_norm = (action or "").strip().lower()
    
    if action_norm in ("read", "navigate", "wait_for"):
        return "safe"
    
    # Check if the target label/name denotes an irreversible action
    target_text = f"{target_name or ''} {role or ''}".strip()
    if _IRREVERSIBLE_REGEX.search(target_text):
        return "irreversible"
        
    return "reversible"


def requires_approval_for_replay(risk: RiskLevel, artifact_status: str) -> bool:
    """Returns True if the step requires explicit human approval before execution.
    
    Rule: Irreversible actions on 'draft' artifacts cannot run unattended.
    """
    if risk == "irreversible" and artifact_status != "approved":
        return True
    return False
