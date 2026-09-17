"""Integration tests for deterministic replay engine."""

import json
from pathlib import Path
import pytest
from src.artifact.schema import CapabilityArtifact
from src.replay.executor import ReplayEngine


@pytest.mark.asyncio
async def test_replay_locked_out_user_outcome():
    """Validates that locked_out_user returns BUSINESS_OUTCOME rather than crashing."""
    artifact_path = Path("artifacts/checkout_backpack_v1.json")
    assert artifact_path.exists()

    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    artifact = CapabilityArtifact.model_validate(data)

    engine = ReplayEngine()
    result = await engine.execute(
        artifact=artifact,
        params={"username": "locked_out_user", "password": "secret_sauce"},
        headless=True,
    )

    assert result.status == "business_outcome"
    assert result.outcome_code == "USER_LOCKED_OUT"
    assert "locked out" in (result.observed or "").lower()


@pytest.mark.asyncio
async def test_replay_input_validation():
    """Validates that missing required input fails before browser launch."""
    artifact_path = Path("artifacts/checkout_backpack_v1.json")
    with open(artifact_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    artifact = CapabilityArtifact.model_validate(data)

    # Empty dictionary without required parameters and without defaults
    artifact.input_params[0].default = None
    engine = ReplayEngine()
    result = await engine.execute(
        artifact=artifact,
        params={},
        headless=True,
    )
    assert result.status == "hard_failure"
    assert result.outcome_code == "INVALID_INPUT"
