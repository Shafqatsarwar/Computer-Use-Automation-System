"""Tests for sensitive data and secret redaction."""

from src.guardrails.redactor import redact_data, redact_text


def test_redact_text():
    text = "User logged in with password secret_sauce and key AIzaSy12345678"
    redacted = redact_text(text, extra_secrets=["secret_sauce", "AIzaSy12345678"])
    assert "secret_sauce" not in redacted
    assert "AIzaSy12345678" not in redacted
    assert "****" in redacted


def test_redact_dictionary_data():
    payload = {
        "event": "login",
        "username": "standard_user",
        "password": "secret_sauce",
        "api_key": "sensitive_key_123",
        "nested": {
            "token": "bearer_abc",
            "normal_field": "visible_value",
        },
    }
    redacted = redact_data(payload, extra_secrets=["secret_sauce"])
    assert redacted["username"] == "standard_user"
    assert redacted["password"] == "****"
    assert redacted["api_key"] == "****"
    assert redacted["nested"]["token"] == "****"
    assert redacted["nested"]["normal_field"] == "visible_value"
