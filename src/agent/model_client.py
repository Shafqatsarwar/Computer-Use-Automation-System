"""Gemini Model Client with primary / secondary model fallback.

Wraps google-genai SDK to provide robust tool calling for the discovery loop:
- Default model: gemini-2.5-flash (fast, high quota, optimized for agentic tool use)
- Fallback model: gemini-3-flash-preview (higher reasoning capability for complex/ambiguous states)
- Records exact model_used for every step
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv

load_dotenv()

# Model IDs
PRIMARY_MODEL = os.getenv("GEMINI_PRIMARY_MODEL", "gemini-2.5-flash")
SECONDARY_MODEL = os.getenv("GEMINI_SECONDARY_MODEL", "gemini-3-flash-preview")


@dataclass
class AgentDecision:
    tool_name: str
    tool_args: dict[str, Any]
    model_used: str
    thought: str = ""


class GeminiDiscoveryClient:
    """Manages LLM communication with fallback logic for discovery."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._client = None
        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"[GeminiClient] Warning initializing google.genai: {e}")

    def decide(self, prompt: str, system_instruction: str | None = None) -> AgentDecision:
        """Invokes Gemini with function calling, applying primary -> fallback logic."""
        from src.agent.tools import DISCOVERY_TOOLS
        from google.genai import types

        if not self._client:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured in the environment or .env file. "
                "Please add GEMINI_API_KEY to .env to run real discovery."
            )

        config = types.GenerateContentConfig(
            tools=DISCOVERY_TOOLS,
            temperature=0.1,
            system_instruction=system_instruction or (
                "You are an expert browser automation agent operating a legacy enterprise/e-commerce UI. "
                "Your objective is to accomplish the user's goal by taking ONE discrete action at a time. "
                "Inspect the provided accessibility tree and current page state carefully. "
                "Use 'click' with role and accessible name, 'type' with role, name and text, or 'navigate'. "
                "Call 'finish' immediately when the target page or goal is achieved."
            ),
        )

        import time

        for attempt in range(4):
            # Attempt with Primary Model
            try:
                response = self._client.models.generate_content(
                    model=PRIMARY_MODEL,
                    contents=prompt,
                    config=config,
                )
                decision = self._extract_decision(response, PRIMARY_MODEL)
                if decision:
                    return decision
                print(f"[GeminiClient] Primary model ({PRIMARY_MODEL}) returned no tool call. Retrying with fallback ({SECONDARY_MODEL})...")
            except Exception as e:
                err_str = str(e)
                print(f"[GeminiClient] Primary model ({PRIMARY_MODEL}) error: {e}.")
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"[GeminiClient] Quota hit on primary. Waiting 12s before fallback/retry (attempt {attempt+1}/4)...")
                    time.sleep(12)

            # Attempt with Secondary Model
            try:
                response = self._client.models.generate_content(
                    model=SECONDARY_MODEL,
                    contents=prompt,
                    config=config,
                )
                decision = self._extract_decision(response, SECONDARY_MODEL)
                if decision:
                    return decision
            except Exception as e:
                err_str = str(e)
                print(f"[GeminiClient] Secondary model ({SECONDARY_MODEL}) error: {e}.")
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"[GeminiClient] Quota hit on secondary. Waiting 15s before next attempt (attempt {attempt+1}/4)...")
                    time.sleep(15)

        raise RuntimeError("LLM response did not contain a valid function call after rate-limit retries.")

    def _extract_decision(self, response: Any, model_name: str) -> AgentDecision | None:
        """Extracts tool call and optional text reasoning from model response."""
        if not response:
            return None

        # Extract function call first to avoid Google GenAI SDK warning on response.text
        if hasattr(response, "function_calls") and response.function_calls:
            fc = response.function_calls[0]
            name = getattr(fc, "name", "")
            args = getattr(fc, "args", {})
            args_dict = dict(args) if args else {}
            return AgentDecision(
                tool_name=name,
                tool_args=args_dict,
                model_used=model_name,
                thought="",
            )

        # Check candidates structure
        if hasattr(response, "candidates") and response.candidates:
            for cand in response.candidates:
                content = getattr(cand, "content", None)
                if content and hasattr(content, "parts"):
                    for part in content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            fc = part.function_call
                            args_dict = dict(fc.args) if getattr(fc, "args", None) else {}
                            return AgentDecision(
                                tool_name=fc.name,
                                tool_args=args_dict,
                                model_used=model_name,
                                thought="",
                            )
        return None
