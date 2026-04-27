from __future__ import annotations

from typing import Any

from tokenkill.models import ProviderPricing, TokenUsage
from tokenkill.providers.base import BaseProvider

_PRICING: dict[str, ProviderPricing] = {
    "gpt-4o":            ProviderPricing(input_per_mtok=2.50,  output_per_mtok=10.00),
    "gpt-4o-mini":       ProviderPricing(input_per_mtok=0.15,  output_per_mtok=0.60),
    "gpt-4-turbo":       ProviderPricing(input_per_mtok=10.00, output_per_mtok=30.00),
    "gpt-4":             ProviderPricing(input_per_mtok=30.00, output_per_mtok=60.00),
    "gpt-3.5-turbo":     ProviderPricing(input_per_mtok=0.50,  output_per_mtok=1.50),
    "o1":                ProviderPricing(input_per_mtok=15.00, output_per_mtok=60.00),
    "o1-mini":           ProviderPricing(input_per_mtok=3.00,  output_per_mtok=12.00),
    "o3":                ProviderPricing(input_per_mtok=10.00, output_per_mtok=40.00),
    "o3-mini":           ProviderPricing(input_per_mtok=1.10,  output_per_mtok=4.40),
    "codex-mini-latest": ProviderPricing(input_per_mtok=1.50,  output_per_mtok=6.00),
}

_DEFAULT_PRICING = ProviderPricing(input_per_mtok=2.50, output_per_mtok=10.00)


class OpenAIProvider(BaseProvider):
    name = "openai"
    base_url = "https://api.openai.com"

    def extract_tokens(self, response_body: dict[str, Any]) -> TokenUsage:
        usage = response_body.get("usage", {})
        return TokenUsage(
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def get_pricing(self, model: str) -> ProviderPricing:
        for key, pricing in _PRICING.items():
            if model.startswith(key):
                return pricing
        return _DEFAULT_PRICING

    def extract_model(self, response_body: dict[str, Any]) -> str:
        return response_body.get("model", "unknown")

    def extract_tool_name(self, request_body: dict[str, Any]) -> str | None:
        messages = request_body.get("messages", [])
        for msg in reversed(messages):
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                return str(tool_calls[-1].get("function", {}).get("name", ""))
        return None
