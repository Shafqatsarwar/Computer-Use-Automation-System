"""Secret and PII redaction utilities for Computer-Use Automation System.

Ensures that passwords, API keys, and sensitive fields are never written
to logs, transcripts, or persisted capability artifacts.
"""

from __future__ import annotations
import os
import re
from typing import Any

SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|secret|api_?key|token|auth|credential|ssn|cvv)",
    re.IGNORECASE,
)

# Common test credentials to redact from raw logs if present
KNOWN_TEST_SECRETS = ["secret_sauce"]


def get_environment_secrets() -> list[str]:
    """Collects actual environment secrets that must be redacted."""
    secrets: list[str] = list(KNOWN_TEST_SECRETS)
    for k, v in os.environ.items():
        if v and len(v) > 4 and SENSITIVE_KEY_PATTERNS.search(k):
            secrets.append(v)
    return secrets


def redact_text(text: str, extra_secrets: list[str] | None = None) -> str:
    """Redacts secret substrings in a text string with '****'."""
    if not text or not isinstance(text, str):
        return text

    secrets = get_environment_secrets()
    if extra_secrets:
        secrets.extend(extra_secrets)

    redacted = text
    for secret in set(secrets):
        if secret and len(secret) >= 3:
            redacted = redacted.replace(secret, "****")
            
    # Also redact generic patterns like api key parameters if matched
    redacted = re.sub(r'(api_key=)[^&\s"\']+', r'\1****', redacted, flags=re.IGNORECASE)
    return redacted


def redact_data(obj: Any, extra_secrets: list[str] | None = None) -> Any:
    """Recursively redacts dictionary keys and values containing sensitive information."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if SENSITIVE_KEY_PATTERNS.search(str(k)):
                result[k] = "****"
            else:
                result[k] = redact_data(v, extra_secrets)
        return result
    elif isinstance(obj, list):
        return [redact_data(item, extra_secrets) for item in obj]
    elif isinstance(obj, str):
        return redact_text(obj, extra_secrets)
    else:
        return obj
