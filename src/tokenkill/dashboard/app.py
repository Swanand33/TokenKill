from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Set

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from tokenkill.budget import BudgetEnforcer
from tokenkill.db import Database
from tokenkill.models import BudgetStatus, CostEvent, LoopAlert
from tokenkill.tracker import CostTracker

from tokenkill.dashboard.routes import create_router

logger = structlog.get_logger()

_STATIC_DIR = Path(__file__).parent / "static"


class ConnectionManager:
    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        dead = set()
        for ws in self._active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.add(ws)
        self._active -= dead


def create_dashboard_app(
    db: Database,
    tracker: CostTracker,
    budget: BudgetEnforcer,
) -> FastAPI:
    app = FastAPI(title="TokenKill Dashboard", docs_url=None, redoc_url=None)
    manager = ConnectionManager()

    async def broadcast(
        event: CostEvent,
        status: BudgetStatus,
        loop_alert: Optional[LoopAlert] = None,
    ) -> None:
        payload: dict[str, Any] = {
            "type": "cost_event",
            "event": event.model_dump(mode="json"),
            "budget": status.model_dump(),
        }
        if loop_alert:
            payload["loop_alert"] = loop_alert.model_dump()
        await manager.broadcast(payload)

    app.state.broadcast = broadcast

    # REST routes
    api_router = create_router(db, tracker, budget)
    app.include_router(api_router)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()  # keep alive — client sends pings
        except WebSocketDisconnect:
            manager.disconnect(ws)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_index() -> HTMLResponse:
        index = _STATIC_DIR / "index.html"
        return HTMLResponse(index.read_text())

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
