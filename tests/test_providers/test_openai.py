from __future__ import annotations

import pytest

from tokenkill.providers.openai import OpenAIProvider
from tests.conftest import OPENAI_RESPONSE


@pytest.fixture
def provider():
    return OpenAIProvider()


def test_extract_tokens(provider):
    usage = provider.extract_tokens(OPENAI_RESPONSE)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.total_tokens == 150


def test_extract_tokens_empty(provider):
    usage = provider.extract_tokens({})
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_extract_model(provider):
    assert provider.extract_model(OPENAI_RESPONSE) == "gpt-4o"


def test_get_pricing_gpt4o(provider):
    p = provider.get_pricing("gpt-4o")
    assert p.input_per_mtok == 2.50
    assert p.output_per_mtok == 10.00


def test_get_pricing_mini(provider):
    p = provider.get_pricing("gpt-4o-mini")
    assert p.input_per_mtok == 0.15


def test_get_pricing_unknown(provider):
    p = provider.get_pricing("gpt-unknown")
    assert p.input_per_mtok > 0
