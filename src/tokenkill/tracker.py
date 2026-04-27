from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

import structlog

from tokenkill.db import Database
from tokenkill.models import CostEvent, CostTree, Provider, Session, TokenUsage
from tokenkill.providers.base import BaseProvider

logger = structlog.get_logger()


class CostTracker:
    def __init__(self, db: Database, project: str) -> None:
        self._db = db
        self._project = project
        self._session: Optional[Session] = None
        self._cost_by_tool: dict[str, float] = defaultdict(float)
        self._cost_by_file: dict[str, float] = defaultdict(float)
        self._cost_by_model: dict[str, float] = defaultdict(float)
        self._cost_by_provider: dict[str, float] = defaultdict(float)
        self._burn_window: list[tuple[datetime, float]] = []  # (timestamp, cost) for rate calc

    async def start_session(self) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        self._session = Session(
            id=session_id,
            project=self._project,
            started_at=now,
            last_activity=now,
        )
        await self._db.upsert_session(self._session)
        logger.info("session_started", session_id=session_id, project=self._project)
        return session_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session.id if self._session else None

    @property
    def session_cost(self) -> float:
        return self._session.total_cost_usd if self._session else 0.0

    async def record(
        self,
        provider: BaseProvider,
        usage: TokenUsage,
        model: str,
        request_hash: Optional[str] = None,
        tool_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> CostEvent:
        if not self._session:
            await self.start_session()

        assert self._session is not None

        pricing = provider.get_pricing(model)
        cost = usage.cost(pricing)

        event = CostEvent(
            session_id=self._session.id,
            provider=Provider(provider.name),
            model=model,
            usage=usage,
            cost_usd=cost,
            tool_name=tool_name,
            file_path=file_path,
            request_hash=request_hash,
        )

        self._session.total_cost_usd += cost
        self._session.total_input_tokens += usage.input_tokens
        self._session.total_output_tokens += usage.output_tokens
        self._session.event_count += 1
        self._session.last_activity = datetime.utcnow()

        if tool_name:
            self._cost_by_tool[tool_name] += cost
        if file_path:
            self._cost_by_file[file_path] += cost
        self._cost_by_model[model] += cost
        self._cost_by_provider[provider.name] += cost

        self._burn_window.append((datetime.utcnow(), cost))
        self._trim_burn_window()

        await self._db.insert_event(event)
        await self._db.upsert_session(self._session)

        logger.info(
            "cost_recorded",
            provider=provider.name,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(cost, 6),
            session_total=round(self._session.total_cost_usd, 4),
        )

        return event

    def burn_rate_per_minute(self) -> Optional[float]:
        """Rolling average cost per minute over the last 5 minutes."""
        if len(self._burn_window) < 2:
            return None
        oldest_time, _ = self._burn_window[0]
        newest_time, _ = self._burn_window[-1]
        elapsed_minutes = (newest_time - oldest_time).total_seconds() / 60
        if elapsed_minutes < 0.1:
            return None
        total = sum(c for _, c in self._burn_window)
        return total / elapsed_minutes

    def cost_tree(self) -> Optional[CostTree]:
        if not self._session:
            return None
        return CostTree(
            session_id=self._session.id,
            total_cost_usd=self._session.total_cost_usd,
            by_provider=dict(self._cost_by_provider),
            by_tool=dict(self._cost_by_tool),
            by_file=dict(self._cost_by_file),
            by_model=dict(self._cost_by_model),
        )

    def _trim_burn_window(self) -> None:
        cutoff = datetime.utcnow()
        from datetime import timedelta
        five_min_ago = cutoff - timedelta(minutes=5)
        self._burn_window = [(t, c) for t, c in self._burn_window if t >= five_min_ago]
