from __future__ import annotations

import pytest
import pytest_asyncio
import httpx

from tokenkill.budget import BudgetEnforcer
from tokenkill.config import BudgetConfig
from tokenkill.dashboard.app import create_dashboard_app
from tokenkill.models import TokenUsage
from tokenkill.providers.anthropic import AnthropicProvider


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def dashboard_client(db, tracker):
    budget = BudgetEnforcer(BudgetConfig(session_cap=50.00))
    app = create_dashboard_app(db=db, tracker=tracker, budget=budget)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def dashboard_client_with_data(db, tracker):
    """Dashboard client with one recorded cost event."""
    budget = BudgetEnforcer(BudgetConfig(session_cap=50.00))
    provider = AnthropicProvider()
    usage = TokenUsage(input_tokens=200, output_tokens=100)
    await tracker.record(
        provider=provider,
        usage=usage,
        model="claude-sonnet-4-6",
        tool_name="read_file",
        file_path="/app/config.py",
    )
    app = create_dashboard_app(db=db, tracker=tracker, budget=budget)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tracker


# ── Root / HTML ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_index_returns_html(dashboard_client):
    resp = await dashboard_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "TokenKill" in resp.text


# ── /api/current ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_current_active_session(dashboard_client_with_data):
    client, tracker = dashboard_client_with_data
    resp = await client.get("/api/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["session"] is not None
    assert data["cost_tree"] is not None


@pytest.mark.asyncio
async def test_current_has_cost_tree_fields(dashboard_client_with_data):
    client, _ = dashboard_client_with_data
    resp = await client.get("/api/current")
    tree = resp.json()["cost_tree"]
    assert "by_provider" in tree
    assert "by_tool" in tree
    assert "by_file" in tree
    assert "total_cost_usd" in tree


@pytest.mark.asyncio
async def test_current_cost_tree_populated(dashboard_client_with_data):
    client, _ = dashboard_client_with_data
    resp = await client.get("/api/current")
    tree = resp.json()["cost_tree"]
    assert "anthropic" in tree["by_provider"]
    assert "read_file" in tree["by_tool"]
    assert "/app/config.py" in tree["by_file"]


# ── /api/sessions ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sessions_returns_list(dashboard_client_with_data):
    client, _ = dashboard_client_with_data
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_session_by_id(dashboard_client_with_data):
    client, tracker = dashboard_client_with_data
    sid = tracker.session_id
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == sid


@pytest.mark.asyncio
async def test_session_not_found_returns_404(dashboard_client):
    resp = await dashboard_client.get("/api/sessions/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_events(dashboard_client_with_data):
    client, tracker = dashboard_client_with_data
    sid = tracker.session_id
    resp = await client.get(f"/api/sessions/{sid}/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    assert events[0]["session_id"] == sid


# ── /api/cost-tree ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cost_tree_endpoint(dashboard_client_with_data):
    client, _ = dashboard_client_with_data
    resp = await client.get("/api/cost-tree")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_cost_usd" in data
    assert data["total_cost_usd"] > 0


# ── /api/budget ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_endpoint_returns_status(dashboard_client_with_data):
    client, _ = dashboard_client_with_data
    resp = await client.get("/api/budget")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_cap" in data
    assert "cap_exceeded" in data
    assert "warning_triggered" in data
    assert data["session_cap"] == 50.00


@pytest.mark.asyncio
async def test_budget_not_exceeded_fresh_session(dashboard_client):
    resp = await dashboard_client.get("/api/budget")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cap_exceeded"] is False
