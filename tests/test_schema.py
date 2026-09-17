"""Tests for Artifact schema and serialization."""

from datetime import datetime, timezone
import json
import pytest
from src.artifact.schema import (
    CapabilityArtifact,
    InputParam,
    KnownOutcome,
    Locator,
    OutputField,
    ReplayResult,
    Step,
)


def test_artifact_schema_round_trip():
    artifact = CapabilityArtifact(
        id="test_capability_v1",
        version=1,
        name="Test Capability",
        description="A test capability artifact",
        target_app="saucedemo",
        entry_url="https://www.saucedemo.com",
        input_params=[
            InputParam(name="username", type="string", required=True, secret=False),
            InputParam(name="password", type="string", required=True, secret=True),
        ],
        steps=[
            Step(
                id="s1",
                action="navigate",
                risk="safe",
                checkpoint="url_contains:saucedemo.com",
            ),
            Step(
                id="s2",
                action="click",
                locator=Locator(
                    strategy="role",
                    role="button",
                    name="Login",
                    fallback=Locator(strategy="css", css="#login-button"),
                ),
                risk="reversible",
                checkpoint="url_contains:/inventory.html",
            ),
        ],
        outputs=[
            OutputField(
                name="item_total",
                type="string",
                extract_from=Locator(strategy="css", css=".summary_subtotal_label"),
            )
        ],
        success_checkpoint="url_contains:/inventory.html",
        known_outcomes=[
            KnownOutcome(
                match="text_contains:Sorry, this user has been locked out.",
                classification="business_outcome",
                outcome_code="USER_LOCKED_OUT",
                message="User is locked out",
            )
        ],
        created_from_run_id="run_12345",
        status="approved",
    )

    # Validate JSON serialization and deserialization
    json_str = artifact.model_dump_json()
    reloaded = CapabilityArtifact.model_validate_json(json_str)

    assert reloaded.id == "test_capability_v1"
    assert reloaded.version == 1
    assert len(reloaded.steps) == 2
    assert reloaded.steps[1].locator is not None
    assert reloaded.steps[1].locator.fallback is not None
    assert reloaded.steps[1].locator.fallback.strategy == "css"
    assert len(reloaded.known_outcomes) == 1
    assert reloaded.known_outcomes[0].outcome_code == "USER_LOCKED_OUT"


def test_replay_result_schema():
    result = ReplayResult(
        status="business_outcome",
        outputs={},
        outcome_code="USER_LOCKED_OUT",
        step_index=4,
        expected="Successful login navigation",
        observed="Epic sadface: Sorry, this user has been locked out.",
        evidence_path="evidence/run_1",
        message="User account locked out",
    )
    dumped = result.model_dump()
    assert dumped["status"] == "business_outcome"
    assert dumped["outcome_code"] == "USER_LOCKED_OUT"
