"""Tests for allowlist guardrail enforcement."""

import pytest
from src.guardrails.allowlist import AllowlistGuardrail, PolicyViolationError


def test_allowlist_permitted_urls():
    guard = AllowlistGuardrail()
    # Allowed domains
    guard.check_url("https://www.saucedemo.com/inventory.html")
    guard.check_url("https://saucedemo.com")
    guard.check_url("http://localhost:3000/demo/bank/login")
    guard.check_url("http://127.0.0.1:8000")


def test_allowlist_blocked_urls():
    guard = AllowlistGuardrail()
    with pytest.raises(PolicyViolationError) as exc_info:
        guard.check_url("https://malicious-site.com/steal-data")
    assert "POLICY_VIOLATION" in str(exc_info.value)


def test_allowlist_permitted_actions():
    guard = AllowlistGuardrail()
    guard.check_action("navigate", "https://www.saucedemo.com")
    guard.check_action("click")
    guard.check_action("type")
    guard.check_action("read")


def test_allowlist_prohibited_actions():
    guard = AllowlistGuardrail()
    with pytest.raises(PolicyViolationError):
        guard.check_action("upload_file")

    with pytest.raises(PolicyViolationError):
        guard.check_action("eval")

    with pytest.raises(PolicyViolationError):
        guard.check_action("arbitrary_bash_command")
