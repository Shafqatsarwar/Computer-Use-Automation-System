"""Unit test for the forced function-calling fix in GeminiDiscoveryClient.

Does not call the live Gemini API -- verifies the request shape only, so it
runs fast and doesn't burn quota. This is a regression test for the bug where
gemini-2.5-flash silently returned plain text instead of a tool call and the
loop fell back to the secondary model on every single step.
"""

from unittest.mock import MagicMock
import pytest
from google.genai import types
from src.agent.model_client import GeminiDiscoveryClient


def _fake_response_with_function_call():
    fc = types.FunctionCall(name="finish", args={"success": True, "reason": "done"})
    response = MagicMock()
    response.function_calls = [fc]
    return response


def test_decide_forces_function_calling_mode_any():
    client = GeminiDiscoveryClient(api_key="fake-key-for-test")
    mock_generate = MagicMock(return_value=_fake_response_with_function_call())
    client._client = MagicMock()
    client._client.models.generate_content = mock_generate

    decision = client.decide("dummy prompt")

    assert decision.tool_name == "finish"
    assert mock_generate.called
    _, kwargs = mock_generate.call_args
    config = kwargs["config"]
    assert config.tool_config is not None
    assert config.tool_config.function_calling_config.mode == "ANY"


def test_decide_raises_clear_error_without_api_key():
    client = GeminiDiscoveryClient(api_key=None)
    client._client = None
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        client.decide("dummy prompt")
