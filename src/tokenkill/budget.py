from __future__ import annotations

from typing import Optional

import structlog

from tokenkill.config import BudgetConfig
from tokenkill.models import BudgetStatus

logger = structlog.get_logger()


class BudgetEnforcer:
    def __init__(self, config: BudgetConfig) -> None:
        self._config = config

    def check(
        self,
        session_spent: float,
        project_spent: float,
        burn_rate_per_minute: Optional[float] = None,
    ) -> BudgetStatus:
        session_pct = None
        if self._config.session_cap and self._config.session_cap > 0:
            session_pct = session_spent / self._config.session_cap

        project_pct = None
        if self._config.project_cap and self._config.project_cap > 0:
            project_pct = project_spent / self._config.project_cap

        cap_exceeded = bool(
            (session_pct is not None and session_pct >= 1.0)
            or (project_pct is not None and project_pct >= 1.0)
        )

        warning_triggered = bool(
            (session_pct is not None and session_pct >= self._config.warning_threshold)
            or (project_pct is not None and project_pct >= self._config.warning_threshold)
        )

        estimated_minutes: Optional[float] = None
        if burn_rate_per_minute and burn_rate_per_minute > 0:
            remaining = float("inf")
            if self._config.session_cap:
                remaining = min(remaining, (self._config.session_cap - session_spent) / burn_rate_per_minute)
            if self._config.project_cap:
                remaining = min(remaining, (self._config.project_cap - project_spent) / burn_rate_per_minute)
            if remaining != float("inf"):
                estimated_minutes = max(0.0, remaining)

        status = BudgetStatus(
            session_cap=self._config.session_cap,
            project_cap=self._config.project_cap,
            session_spent=session_spent,
            project_spent=project_spent,
            session_pct=session_pct,
            project_pct=project_pct,
            warning_triggered=warning_triggered,
            cap_exceeded=cap_exceeded,
            estimated_minutes_remaining=estimated_minutes,
            burn_rate=burn_rate_per_minute,
        )

        if cap_exceeded:
            logger.warning(
                "budget_cap_exceeded",
                session_spent=round(session_spent, 4),
                session_cap=self._config.session_cap,
                project_spent=round(project_spent, 4),
                project_cap=self._config.project_cap,
            )
        elif warning_triggered:
            logger.info(
                "budget_warning",
                session_pct=round(session_pct or 0, 2),
                estimated_minutes=round(estimated_minutes or 0, 1),
            )

        return status

    def cap_response_body(self, status: BudgetStatus) -> dict:
        parts = []
        if status.session_pct and status.session_pct >= 1.0:
            parts.append(
                f"Session budget of ${status.session_cap:.2f} exceeded "
                f"(spent ${status.session_spent:.4f})."
            )
        if status.project_pct and status.project_pct >= 1.0:
            parts.append(
                f"Project budget of ${status.project_cap:.2f} exceeded "
                f"(spent ${status.project_spent:.4f})."
            )
        return {
            "error": {
                "type": "tokenkill_budget_exceeded",
                "message": " ".join(parts) + " Set a higher cap or start a new session.",
                "session_spent": status.session_spent,
                "session_cap": status.session_cap,
                "project_spent": status.project_spent,
                "project_cap": status.project_cap,
            }
        }

    def warning_header_value(self, status: BudgetStatus) -> Optional[str]:
        if not status.warning_triggered:
            return None
        pct = max(
            p for p in [status.session_pct, status.project_pct] if p is not None
        )
        msg = f"{int(pct * 100)}pct of budget consumed"
        if status.estimated_minutes_remaining is not None:
            msg += f"; ~{status.estimated_minutes_remaining:.0f}min remaining"
        return msg
