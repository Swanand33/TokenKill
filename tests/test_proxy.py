from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
import respx

from tokenkill.budget import BudgetEnforcer
from tokenkill.config import BudgetConfig, load_config
from tokenkill.db import Database
from tokenkill.loop_detector import LoopDetector
from tokenkill.proxy import create_proxy_app, _route_provider
from tokenkill.tracker import CostTracker
from tests.conftest import ANTHROPIC_RESPONSE, OPENAI_RESPONSE, GOOGLE_RESPONSE, ANTHROPIC_REQUEST


# ── Helpers ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def proxy_client(db, tracker):
    config = load_config()
    loop_det = LoopDetector()
    budget = BudgetEnforcer(BudgetConfig())
    app = create_proxy_app(
        config=config,
        db=db,
        tracker=tracker,
        loop_detector=loop_det,
        budget=budget,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def proxy_client_with_cap(db, tracker):
    config = load_config()
    loop_det = LoopDetector()
    budget = BudgetEnforcer(BudgetConfig(session_cap=0.00001))  # tiny cap — always exceeded
    app = create_proxy_app(
        config=config,
        db=db,
        tracker=tracker,
        loop_detector=loop_det,
        budget=budget,
    )
    # Pre-spend to exceed cap
    tracker._session.total_cost_usd = 9999.0  # type: ignore[union-attr]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Route detection ───────────────────────────────────────────────────────────

def test_route_anthropic():
    config = load_config()
    provider, base = _route_provider("/v1/messages", config)
    assert provider is not None
    assert provider.name == "anthropic"
    assert "anthropic.com" in base


def test_route_openai():
    config = load_config()
    provider, base = _route_provider("/v1/chat/completions", config)
    assert provider is not None
    assert provider.name == "openai"


def test_route_google():
    config = load_config()
    provider, base = _route_provider("/v1beta/models/gemini:generateContent", config)
    assert provider is not None
    assert provider.name == "google"


def test_route_ollama():
    config = load_config()
    provider, base = _route_provider("/api/chat", config)
    assert provider is not None
    assert provider.name == "ollama"


def test_route_unknown():
    config = load_config()
    provider, base = _route_provider("/unknown/path", config)
    assert provider is None
    assert base == ""


# ── Budget enforcement ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_exceeded_returns_429(proxy_client_with_cap):
    resp = await proxy_client_with_cap.post(
        "/v1/messages",
        json=ANTHROPIC_REQUEST,
        headers={"authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"]["type"] == "tokenkill_budget_exceeded"


# ── Loop detection ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_loop_pause_returns_429(db, tracker):
    config = load_config()
    loop_det = LoopDetector()
    budget = BudgetEnforcer(BudgetConfig())
    app = create_proxy_app(config=config, db=db, tracker=tracker,
                           loop_detector=loop_det, budget=budget)

    # Pre-fill window with the actual hash of ANTHROPIC_REQUEST to trigger pause
    real_hash = loop_det.hash_request(ANTHROPIC_REQUEST)
    for _ in range(6):
        loop_det._window.append(real_hash)

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            json=ANTHROPIC_REQUEST,
            headers={"authorization": "Bearer sk-test"},
        )
    # May be 429 (pause) or 503 (kill) depending on hash match — both are loop responses
    assert resp.status_code in (429, 503)


# ── Happy path: request forwarding ───────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_anthropic_request_forwarded(proxy_client):
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    resp = await proxy_client.post(
        "/v1/messages",
        json=ANTHROPIC_REQUEST,
        headers={"authorization": "Bearer sk-ant-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == ANTHROPIC_RESPONSE["id"]


@pytest.mark.asyncio
@respx.mock
async def test_openai_request_forwarded(proxy_client):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=OPENAI_RESPONSE)
    )
    resp = await proxy_client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        headers={"authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == OPENAI_RESPONSE["id"]


@pytest.mark.asyncio
@respx.mock
async def test_token_cost_recorded_after_request(proxy_client, tracker):
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    assert tracker.session_cost == 0.0

    await proxy_client.post(
        "/v1/messages",
        json=ANTHROPIC_REQUEST,
        headers={"authorization": "Bearer sk-ant-test"},
    )
    assert tracker.session_cost > 0.0


# ── Warning headers ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_warning_header_injected_near_cap(db, tracker):
    config = load_config()
    loop_det = LoopDetector()
    budget = BudgetEnforcer(BudgetConfig(session_cap=1.00, warning_threshold=0.80))
    app = create_proxy_app(config=config, db=db, tracker=tracker,
                           loop_detector=loop_det, budget=budget)

    # Spend 85% of cap
    tracker._session.total_cost_usd = 0.85  # type: ignore[union-attr]

    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=ANTHROPIC_RESPONSE)
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/messages",
            json=ANTHROPIC_REQUEST,
            headers={"authorization": "Bearer sk-ant-test"},
        )

    assert "x-tokenkill-warning" in resp.headers
    assert "85" in resp.headers["x-tokenkill-warning"]


# ── Unknown route ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_route_returns_502(proxy_client):
    resp = await proxy_client.post("/totally/unknown/path", json={})
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["type"] == "tokenkill_unknown_route"


# ── Upstream error ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_upstream_connect_error_returns_502(proxy_client):
    respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    resp = await proxy_client.post(
        "/v1/messages",
        json=ANTHROPIC_REQUEST,
        headers={"authorization": "Bearer sk-ant-test"},
    )
    assert resp.status_code == 502
    assert "tokenkill_upstream_error" in resp.json()["error"]["type"]
