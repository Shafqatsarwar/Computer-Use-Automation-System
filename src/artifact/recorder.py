"""Artifact recorder: converts discovery transcripts into structured capability artifacts.

Decouples the raw model transcript into a typed, parameterized, versioned,
and reviewable CapabilityArtifact suitable for deterministic replay.
"""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.agent.loop import DiscoveryTranscript
from src.artifact.schema import (
    CapabilityArtifact,
    InputParam,
    KnownOutcome,
    Locator,
    OutputField,
    Step,
)
from src.guardrails.risk import classify_risk


STANDARD_SAUCEDEMO_OUTCOMES = [
    KnownOutcome(
        match='text_contains:Epic sadface: Sorry, this user has been locked out.',
        classification="business_outcome",
        outcome_code="USER_LOCKED_OUT",
        message="User account is locked out in the target system.",
    ),
    KnownOutcome(
        match='text_contains:Epic sadface: Username is required',
        classification="business_outcome",
        outcome_code="VALIDATION_ERROR_USERNAME",
        message="Username field was left empty or missing.",
    ),
    KnownOutcome(
        match='text_contains:Epic sadface: Password is required',
        classification="business_outcome",
        outcome_code="VALIDATION_ERROR_PASSWORD",
        message="Password field was left empty or missing.",
    ),
    KnownOutcome(
        match='text_contains:Epic sadface: Username and password do not match any user in this service',
        classification="business_outcome",
        outcome_code="INVALID_CREDENTIALS",
        message="The username or password supplied was invalid.",
    ),
]


class ArtifactRecorder:
    """Compiles a DiscoveryTranscript into a CapabilityArtifact."""

    @staticmethod
    def compile_saucedemo_checkout(
        transcript: DiscoveryTranscript,
        artifact_id: str = "checkout_backpack_v1",
        version: int = 1,
    ) -> CapabilityArtifact:
        """Transforms a successful SauceDemo checkout transcript into a CapabilityArtifact."""
        steps: list[Step] = []
        input_params: list[InputParam] = [
            InputParam(
                name="username",
                type="string",
                required=True,
                secret=False,
                description="Sauce Demo login username",
                default="standard_user",
            ),
            InputParam(
                name="password",
                type="string",
                required=True,
                secret=True,
                description="Sauce Demo login password",
            ),
            InputParam(
                name="first_name",
                type="string",
                required=False,
                secret=False,
                description="Checkout shipping first name",
                default="Alex",
            ),
            InputParam(
                name="last_name",
                type="string",
                required=False,
                secret=False,
                description="Checkout shipping last name",
                default="Morgan",
            ),
            InputParam(
                name="postal_code",
                type="string",
                required=False,
                secret=False,
                description="Checkout shipping postal code",
                default="94016",
            ),
        ]

        step_counter = 1
        for s in transcript.steps:
            if s.action == "finish":
                continue

            # Build multi-strategy locator
            locator: Locator | None = None
            if s.locator_role and s.locator_name:
                locator = Locator(
                    strategy="role",
                    role=s.locator_role,
                    name=s.locator_name,
                    fallback=Locator(
                        strategy="text",
                        name=s.locator_name,
                        fallback=Locator(
                            strategy="css",
                            css=f"[data-test='{s.locator_name.lower().replace(' ', '-')}']",
                        ) if s.locator_name else None,
                    ),
                )

            # Map literal values to parameters
            value_param: str | None = None
            if s.action == "type":
                val = (s.value or "").strip()
                name_lower = (s.locator_name or "").lower()
                if "user" in name_lower or val == "standard_user":
                    value_param = "username"
                elif "pass" in name_lower or val == "secret_sauce":
                    value_param = "password"
                elif "first" in name_lower or val.lower() == "alex":
                    value_param = "first_name"
                elif "last" in name_lower or val.lower() == "morgan":
                    value_param = "last_name"
                elif "zip" in name_lower or "postal" in name_lower or val == "94016":
                    value_param = "postal_code"

            # Determine checkpoint
            checkpoint: str | None = None
            if "login" in (s.locator_name or "").lower() or s.action == "click" and s.locator_name == "Login":
                checkpoint = "url_contains:/inventory.html"
            elif "backpack" in (s.locator_name or "").lower() or "cart" in (s.locator_name or "").lower():
                checkpoint = "text_visible:Remove" if "add" in (s.locator_name or "").lower() else "url_contains:/cart.html"
            elif "checkout" in (s.locator_name or "").lower():
                checkpoint = "url_contains:/checkout-step-one.html"
            elif "continue" in (s.locator_name or "").lower():
                checkpoint = "url_contains:/checkout-step-two.html"

            risk = classify_risk(s.action, s.locator_name, s.locator_role)

            step = Step(
                id=f"step_{step_counter}",
                action=s.action,  # type: ignore
                locator=locator,
                value_param=value_param,
                risk=risk,
                checkpoint=checkpoint,
            )
            steps.append(step)
            step_counter += 1

        outputs = [
            OutputField(
                name="item_total",
                type="string",
                extract_from=Locator(strategy="css", css=".summary_subtotal_label"),
            ),
            OutputField(
                name="tax",
                type="string",
                extract_from=Locator(strategy="css", css=".summary_tax_label"),
            ),
            OutputField(
                name="total",
                type="string",
                extract_from=Locator(strategy="css", css=".summary_total_label"),
            ),
        ]

        artifact = CapabilityArtifact(
            id=artifact_id,
            version=version,
            name="Sauce Demo Backpack Checkout",
            description="Logs into Sauce Demo, adds Sauce Labs Backpack to cart, completes checkout step one, and verifies order review screen with total calculation.",
            target_app="saucedemo",
            entry_url=transcript.entry_url,
            input_params=input_params,
            steps=steps,
            outputs=outputs,
            success_checkpoint="url_contains:/checkout-step-two.html",
            known_outcomes=list(STANDARD_SAUCEDEMO_OUTCOMES),
            created_from_run_id=transcript.run_id,
            created_at=datetime.now(timezone.utc),
            status="approved",
        )
        return artifact

    @staticmethod
    def save_artifact(artifact: CapabilityArtifact, artifacts_dir: str = "artifacts") -> Path:
        """Serializes and saves a CapabilityArtifact to JSON."""
        dir_path = Path(artifacts_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{artifact.id}.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(artifact.model_dump_json(indent=2))
            
        print(f"[ArtifactRecorder] Saved capability artifact to {file_path}")
        return file_path
