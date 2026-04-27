from __future__ import annotations

from typing import Any

from tokenkill.models import ProviderPricing, TokenUsage
from tokenkill.providers.base import BaseProvider

# Pricing as of April 2026 — update when Anthropic changes rates
_PRICING: dict[str, ProviderPricing] = {
    "claude-opus-4-7":       ProviderPricing(input_per_mtok=15.00, output_per_mtok=75.00, cache_write_per_mtok=18.75, cache_read_per_mtok=1.50),
    "claude-sonnet-4-6":     ProviderPricing(input_per_mtok=3.00,  output_per_mtok=15.00, cache_write_per_mtok=3.75,  cache_read_per_mtok=0.30),
    "claude-haiku-4-5":      ProviderPricing(input_per_mtok=0.80,  output_per_mtok=4.00,  cache_write_per_mtok=1.00,  cache_read_per_mtok=0.08),
    "claude-3-5-sonnet-20241022": ProviderPricing(input_per_mtok=3.00, output_per_mtok=15.00, cache_write_per_mtok=3.75, cache_read_per_mtok=0.30),
    "claude-3-5-haiku-20241022":  ProviderPricing(input_per_mtok=0.80, output_per_mtok=4.00,  cache_write_per_mtok=1.00, cache_read_per_mtok=0.08),
}

_DEFAULT_PRICING = ProviderPricing(input_per_mtok=3.00, output_per_mtok=15.00)


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    base_url = "https://api.anthropic.com"

    def extract_tokens(self, response_body: dict[str, Any]) -> TokenUsage:
        usage = response_body.get("usage", {})
        return TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        )

    def extract_tokens_from_stream_chunk(self, chunk: dict[str, Any]) -> TokenUsage | None:
        """Extract token counts from a streaming message_delta or message_stop chunk."""
        if chunk.get("type") == "message_delta":
            usage = chunk.get("usage", {})
            if usage:
                return TokenUsage(output_tokens=usage.get("output_tokens", 0))
        if chunk.get("type") == "message_start":
            msg = chunk.get("message", {})
            usage = msg.get("usage", {})
            if usage:
                return TokenUsage(
                    input_tokens=usage.get("input_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                )
        return None

    def get_pricing(self, model: str) -> ProviderPricing:
        # Match on prefix so "claude-sonnet-4-6-20260101" still resolves
        for key, pricing in _PRICING.items():
            if model.startswith(key) or key.startswith(model):
                return pricing
        return _DEFAULT_PRICING

    def extract_model(self, response_body: dict[str, Any]) -> str:
        return response_body.get("model", "unknown")

    def extract_tool_name(self, request_body: dict[str, Any]) -> str | None:
        messages = request_body.get("messages", [])
        for msg in reversed(messages):
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        return str(block.get("name", ""))
        return None
