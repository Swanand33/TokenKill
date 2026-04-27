from __future__ import annotations

from typing import Any

from tokenkill.models import ProviderPricing, TokenUsage
from tokenkill.providers.base import BaseProvider

# Ollama runs locally — cost is compute time, not $/token
# We track tokens for usage visibility but cost is always $0.00
_ZERO_PRICING = ProviderPricing(input_per_mtok=0.0, output_per_mtok=0.0)


class OllamaProvider(BaseProvider):
    name = "ollama"
    base_url = "http://localhost:11434"

    def extract_tokens(self, response_body: dict[str, Any]) -> TokenUsage:
        return TokenUsage(
            input_tokens=response_body.get("prompt_eval_count", 0),
            output_tokens=response_body.get("eval_count", 0),
        )

    def get_pricing(self, model: str) -> ProviderPricing:
        return _ZERO_PRICING

    def extract_model(self, response_body: dict[str, Any]) -> str:
        return response_body.get("model", "unknown")
