"""Allowlist guardrail enforcement for Computer-Use Automation System.

Checks every single browser action in both discovery and replay against the allowlist.
Violations result in immediate rejection with PolicyViolationError.
"""

from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
import yaml


class PolicyViolationError(Exception):
    """Raised when an action or navigation violates safety guardrails."""
    pass


class AllowlistGuardrail:
    """Enforces domain and action allowlists."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            # Default search path
            potential_paths = [
                Path(__file__).parent / "allowlist.yaml",
                Path("guardrails/allowlist.yaml"),
                Path(__file__).parent.parent.parent / "guardrails" / "allowlist.yaml",
            ]
            for p in potential_paths:
                if p.exists():
                    config_path = p
                    break

        self.permitted_domains: set[str] = {"saucedemo.com", "www.saucedemo.com", "localhost", "127.0.0.1"}
        self.permitted_actions: set[str] = {"navigate", "click", "type", "read", "wait_for"}
        self.prohibited_actions: set[str] = {"upload_file", "download", "eval", "script_execution", "raw_websocket"}

        if config_path and Path(config_path).exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        if "permitted_domains" in data:
                            self.permitted_domains = set(data["permitted_domains"])
                        if "permitted_actions" in data:
                            self.permitted_actions = set(data["permitted_actions"])
                        if "prohibited_actions" in data:
                            self.prohibited_actions = set(data["prohibited_actions"])
            except Exception as e:
                # Fallback to safe defaults if file reading fails
                pass

    def check_url(self, url: str) -> None:
        """Validates that a URL is in the permitted domain list.
        
        Raises PolicyViolationError if domain is not allowed.
        """
        if not url:
            return
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        
        # Check against permitted domains (exact or subdomain match)
        is_allowed = False
        for allowed in self.permitted_domains:
            if hostname == allowed or hostname.endswith("." + allowed):
                is_allowed = True
                break
        
        if not is_allowed:
            raise PolicyViolationError(
                f"POLICY_VIOLATION: Navigation to '{url}' (host '{hostname}') is outside the allowlist: {sorted(self.permitted_domains)}"
            )

    def check_action(self, action: str, target_url: str | None = None) -> None:
        """Validates that an action type and target are permitted.
        
        Raises PolicyViolationError if action is prohibited or not in allowlist.
        """
        action_normalized = (action or "").strip().lower()
        
        if action_normalized in self.prohibited_actions:
            raise PolicyViolationError(
                f"POLICY_VIOLATION: Action '{action}' is explicitly prohibited."
            )

        if action_normalized not in self.permitted_actions:
            raise PolicyViolationError(
                f"POLICY_VIOLATION: Action '{action}' is not in permitted actions: {sorted(self.permitted_actions)}"
            )

        if target_url:
            self.check_url(target_url)


# Global default instance
default_allowlist = AllowlistGuardrail()
