from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    OLLAMA = "ollama"
    UNKNOWN = "unknown"


class LoopAlertLevel(str, Enum):
    WARNING = "warning"   # >3 identical hashes → inject header
    PAUSE = "pause"       # >5 identical hashes → return 429
    KILL = "kill"         # >8 identical hashes → return 503


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def has_usage(self) -> bool:
        return bool(self.input_tokens or self.output_tokens or self.cache_creation_tokens or self.cache_read_tokens)

    def cost(self, pricing: ProviderPricing) -> float:
        return (
            (self.input_tokens / 1_000_000) * pricing.input_per_mtok
            + (self.output_tokens / 1_000_000) * pricing.output_per_mtok
            + (self.cache_creation_tokens / 1_000_000) * pricing.cache_write_per_mtok
            + (self.cache_read_tokens / 1_000_000) * pricing.cache_read_per_mtok
        )


class ProviderPricing(BaseModel):
    input_per_mtok: float
    output_per_mtok: float
    cache_write_per_mtok: float = 0.0
    cache_read_per_mtok: float = 0.0


class CostEvent(BaseModel):
    id: Optional[int] = None
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider: Provider
    model: str
    usage: TokenUsage
    cost_usd: float
    tool_name: Optional[str] = None
    file_path: Optional[str] = None
    request_hash: Optional[str] = None


class Session(BaseModel):
    id: str
    project: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    event_count: int = 0
    is_active: bool = True


class LoopAlert(BaseModel):
    level: LoopAlertLevel
    hash_count: int
    window_size: int
    trigger_type: str  # "identical_calls" | "repeated_file_read"
    repeated_hash: Optional[str] = None
    file_path: Optional[str] = None
    message: str


class BudgetStatus(BaseModel):
    session_cap: Optional[float]
    project_cap: Optional[float]
    session_spent: float
    project_spent: float
    session_pct: Optional[float]
    project_pct: Optional[float]
    warning_triggered: bool
    cap_exceeded: bool
    estimated_minutes_remaining: Optional[float]
    burn_rate: Optional[float] = None


class CostTree(BaseModel):
    session_id: str
    total_cost_usd: float
    by_provider: dict[str, float]
    by_tool: dict[str, float]
    by_file: dict[str, float]
    by_model: dict[str, float]


class DashboardUpdate(BaseModel):
    session_id: str
    event: CostEvent
    budget_status: BudgetStatus
    loop_alert: Optional[LoopAlert] = None
