from __future__ import annotations

import pytest

from tokenkill.models import TokenUsage
from tokenkill.providers.anthropic import AnthropicProvider


@pytest.mark.asyncio
async def test_tracker_starts_session(tracker):
    assert tracker.session_id is not None


@pytest.mark.asyncio
async def test_tracker_records_cost(tracker):
    provider = AnthropicProvider()
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    event = await tracker.record(provider=provider, usage=usage, model="claude-sonnet-4-6")
    assert event.cost_usd > 0
    assert tracker.session_cost > 0


@pytest.mark.asyncio
async def test_tracker_accumulates_cost(tracker):
    provider = AnthropicProvider()
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    await tracker.record(provider=provider, usage=usage, model="claude-sonnet-4-6")
    await tracker.record(provider=provider, usage=usage, model="claude-sonnet-4-6")
    assert tracker.session_cost == pytest.approx(
        2 * usage.cost(provider.get_pricing("claude-sonnet-4-6")), rel=1e-6
    )


@pytest.mark.asyncio
async def test_tracker_cost_tree(tracker):
    provider = AnthropicProvider()
    usage = TokenUsage(input_tokens=100, output_tokens=50)
    await tracker.record(
        provider=provider, usage=usage, model="claude-sonnet-4-6",
        tool_name="read_file", file_path="/app/config.py"
    )
    tree = tracker.cost_tree()
    assert tree is not None
    assert "read_file" in tree.by_tool
    assert "/app/config.py" in tree.by_file
    assert "anthropic" in tree.by_provider


@pytest.mark.asyncio
async def test_tracker_burn_rate_none_initially(tracker):
    assert tracker.burn_rate_per_minute() is None
