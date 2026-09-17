"""Tests for risk policy and approval gating."""

from src.guardrails.risk import classify_risk, requires_approval_for_replay


def test_risk_classification():
    assert classify_risk("read") == "safe"
    assert classify_risk("navigate") == "safe"
    assert classify_risk("click", "Username input") == "reversible"
    assert classify_risk("type", "First Name") == "reversible"
    assert classify_risk("click", "Place Order") == "irreversible"
    assert classify_risk("click", "Submit Payment") == "irreversible"
    assert classify_risk("click", "Finish") == "irreversible"


def test_approval_gating():
    # Irreversible step in draft artifact requires approval
    assert requires_approval_for_replay(risk="irreversible", artifact_status="draft") is True
    # Reversible step in draft does not require approval
    assert requires_approval_for_replay(risk="reversible", artifact_status="draft") is False
    # Irreversible step in approved artifact is permitted
    assert requires_approval_for_replay(risk="irreversible", artifact_status="approved") is False
