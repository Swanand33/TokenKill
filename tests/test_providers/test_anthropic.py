from __future__ import annotations

import pytest

from tokenkill.providers.anthropic import AnthropicProvider
from tests.conftest import ANTHROPIC_RESPONSE, ANTHROPIC_RESPONSE_WITH_CACHE, ANTHROPIC_REQUEST_WITH_TOOL


@pytest.fixture
def provider():
    return AnthropicProvider()


def test_extract_tokens_basic(provider):
    usage = provider.extract_tokens(ANTHROPIC_RESPONSE)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cache_creation_tokens == 0
    assert usage.cache_read_tokens == 0
    assert usage.total_tokens == 150


def test_extract_tokens_with_cache(provider):
    usage = provider.extract_tokens(ANTHROPIC_RESPONSE_WITH_CACHE)
    assert usage.input_tokens == 80
    assert usage.cache_creation_tokens == 10
    assert usage.cache_read_tokens == 20


def test_extract_tokens_empty_response(provider):
    usage = provider.extract_tokens({})
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_extract_model(provider):
    model = provider.extract_model(ANTHROPIC_RESPONSE)
    assert model == "claude-sonnet-4-6"


def test_extract_model_missing(provider):
    model = provider.extract_model({})
    assert model == "unknown"


def test_get_pricing_sonnet(provider):
    pricing = provider.get_pricing("claude-sonnet-4-6")
    assert pricing.input_per_mtok == 3.00
    assert pricing.output_per_mtok == 15.00


def test_get_pricing_opus(provider):
    pricing = provider.get_pricing("claude-opus-4-7")
    assert pricing.input_per_mtok == 15.00


def test_get_pricing_unknown_model(provider):
    pricing = provider.get_pricing("claude-unknown-9000")
    assert pricing.input_per_mtok > 0  # falls back to default


def test_extract_tool_name(provider):
    tool = provider.extract_tool_name(ANTHROPIC_REQUEST_WITH_TOOL)
    assert tool == "read_file"


def test_extract_tool_name_no_tool(provider):
    tool = provider.extract_tool_name({"messages": [{"role": "user", "content": "hi"}]})
    assert tool is None


def test_extract_file_path(provider):
    path = provider.extract_file_path(ANTHROPIC_REQUEST_WITH_TOOL)
    assert path == "/app/config.py"


def test_cost_calculation(provider):
    usage = provider.extract_tokens(ANTHROPIC_RESPONSE)
    pricing = provider.get_pricing("claude-sonnet-4-6")
    cost = usage.cost(pricing)
    expected = (100 / 1_000_000 * 3.00) + (50 / 1_000_000 * 15.00)
    assert abs(cost - expected) < 1e-10
