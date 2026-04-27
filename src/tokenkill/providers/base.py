from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from tokenkill.models import ProviderPricing, TokenUsage


class BaseProvider(ABC):
    name: str
    base_url: str

    # Pricing per million tokens — subclasses override per model
    DEFAULT_PRICING: ProviderPricing = ProviderPricing(
        input_per_mtok=0.0,
        output_per_mtok=0.0,
    )

    @abstractmethod
    def extract_tokens(self, response_body: dict[str, Any]) -> TokenUsage:
        """Parse provider response JSON and return token counts."""
        ...

    @abstractmethod
    def get_pricing(self, model: str) -> ProviderPricing:
        """Return per-million-token pricing for the given model."""
        ...

    @abstractmethod
    def extract_model(self, response_body: dict[str, Any]) -> str:
        """Extract model name from response body."""
        ...

    def extract_tool_name(self, request_body: dict[str, Any]) -> str | None:
        """Optionally extract active tool name from request body."""
        return None

    def extract_file_path(self, request_body: dict[str, Any]) -> str | None:
        """Optionally extract file path from tool_use blocks in request body."""
        messages = request_body.get("messages", [])
        for msg in reversed(messages):
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        inp = block.get("input", {})
                        for key in ("path", "file_path", "filename"):
                            if key in inp:
                                return str(inp[key])
        return None
