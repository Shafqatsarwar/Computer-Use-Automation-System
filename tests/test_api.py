"""Tests for FastAPI backend and synthetic LegacyBank demo portal."""

import pytest
from httpx import AsyncClient, ASGITransport
from src.web.app import app


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"
        assert "artifacts_count" in data


@pytest.mark.asyncio
async def test_artifacts_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == "checkout_backpack_v1"


@pytest.mark.asyncio
async def test_legacy_bank_portal():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Sign in page
        resp = await ac.get("/demo/bank/login")
        assert resp.status_code == 200
        assert "LegacyBank Core Servicing Portal" in resp.text

        # Search member 12345 (Found)
        resp_found = await ac.get("/demo/bank/search?member_id=12345")
        assert resp_found.status_code == 200
        assert "$12,450.00" in resp_found.text
        assert "Alex Morgan" in resp_found.text

        # Search member 99999 (Not found)
        resp_not_found = await ac.get("/demo/bank/search?member_id=99999")
        assert resp_not_found.status_code == 200
        assert "Member ID '99999' not found" in resp_not_found.text
