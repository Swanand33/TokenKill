from __future__ import annotations

from typing import Any

from tokenkill.models import ProviderPricing, TokenUsage
from tokenkill.providers.base import BaseProvider

_PRICING: dict[str, ProviderPricing] = {
    "gemini-2.0-flash":       ProviderPricing(input_per_mtok=0.10,  output_per_mtok=0.40),
    "gemini-2.0-flash-lite":  ProviderPricing(input_per_mtok=0.075, output_per_mtok=0.30),
    "gemini-2.0-pro":         ProviderPricing(input_per_mtok=1.25,  output_per_mtok=5.00),
    "gemini-1.5-pro":         ProviderPricing(input_per_mtok=1.25,  output_per_mtok=5.00),
    "gemini-1.5-flash":       ProviderPricing(input_per_mtok=0.075, output_per_mtok=0.30),
}

_DEFAULT_PRICING = ProviderPricing(input_per_mtok=0.10, output_per_mtok=0.40)


class GoogleProvider(BaseProvider):
    name = "google"
    base_url = "https://generativelanguage.googleapis.com"

    def extract_tokens(self, response_body: dict[str, Any]) -> TokenUsage:
        meta = response_body.get("usageMetadata", {})
        return TokenUsage(
            input_tokens=meta.get("promptTokenCount", 0),
            output_tokens=meta.get("candidatesTokenCount", 0),
        )

    def get_pricing(self, model: str) -> ProviderPricing:
        for key, pricing in _PRICING.items():
            if key in model:
                return pricing
        return _DEFAULT_PRICING

    def extract_model(self, response_body: dict[str, Any]) -> str:
        return response_body.get("modelVersion", "unknown")
