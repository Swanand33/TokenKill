from __future__ import annotations

import pytest

from tokenkill.providers.google import GoogleProvider
from tests.conftest import GOOGLE_RESPONSE


@pytest.fixture
def provider():
    return GoogleProvider()


def test_extract_tokens(provider):
    usage = provider.extract_tokens(GOOGLE_RESPONSE)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50


def test_extract_tokens_empty(provider):
    usage = provider.extract_tokens({})
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_extract_model(provider):
    assert provider.extract_model(GOOGLE_RESPONSE) == "gemini-2.0-flash"


def test_get_pricing_flash(provider):
    p = provider.get_pricing("gemini-2.0-flash")
    assert p.input_per_mtok == 0.10
