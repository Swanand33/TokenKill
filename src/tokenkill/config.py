from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class BudgetConfig(BaseModel):
    session_cap: Optional[float] = None       # TOKENKILL_BUDGET_SESSION
    project_cap: Optional[float] = None       # TOKENKILL_BUDGET_PROJECT
    warning_threshold: float = 0.80           # warn at 80% consumed


class ProxyConfig(BaseModel):
    port: int = 9119
    host: str = "127.0.0.1"
    db_path: Path = Path.home() / ".tokenkill" / "tokenkill.db"
    project: str = "default"
    log_level: str = "INFO"


class ProviderURLs(BaseModel):
    anthropic: str = "https://api.anthropic.com"
    openai: str = "https://api.openai.com"
    google: str = "https://generativelanguage.googleapis.com"
    ollama: str = "http://localhost:11434"


class Config(BaseModel):
    proxy: ProxyConfig
    budget: BudgetConfig
    providers: ProviderURLs


def load_config(
    port: Optional[int] = None,
    budget_session: Optional[float] = None,
    budget_project: Optional[float] = None,
    project: Optional[str] = None,
) -> Config:
    def _float(key: str) -> Optional[float]:
        val = os.getenv(key)
        return float(val) if val else None

    session_cap = budget_session or _float("TOKENKILL_BUDGET_SESSION")
    project_cap = budget_project or _float("TOKENKILL_BUDGET_PROJECT")
    warning_threshold = float(os.getenv("TOKENKILL_WARNING_THRESHOLD", "0.80"))

    proxy_port = port or int(os.getenv("TOKENKILL_PORT", "9119"))
    proxy_project = project or os.getenv("TOKENKILL_PROJECT", "default")
    log_level = os.getenv("TOKENKILL_LOG_LEVEL", "INFO")

    db_path_str = os.getenv("TOKENKILL_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else Path.home() / ".tokenkill" / "tokenkill.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Config(
        proxy=ProxyConfig(
            port=proxy_port,
            project=proxy_project,
            db_path=db_path,
            log_level=log_level,
        ),
        budget=BudgetConfig(
            session_cap=session_cap,
            project_cap=project_cap,
            warning_threshold=warning_threshold,
        ),
        providers=ProviderURLs(
            anthropic=os.getenv("TOKENKILL_ANTHROPIC_URL", "https://api.anthropic.com"),
            openai=os.getenv("TOKENKILL_OPENAI_URL", "https://api.openai.com"),
            google=os.getenv("TOKENKILL_GOOGLE_URL", "https://generativelanguage.googleapis.com"),
            ollama=os.getenv("TOKENKILL_OLLAMA_URL", "http://localhost:11434"),
        ),
    )
