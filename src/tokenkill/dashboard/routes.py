from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from tokenkill.budget import BudgetEnforcer
from tokenkill.db import Database
from tokenkill.tracker import CostTracker

router = APIRouter(prefix="/api")


def create_router(db: Database, tracker: CostTracker, budget: BudgetEnforcer) -> APIRouter:
    @router.get("/sessions")
    async def get_sessions():
        sessions = await db.get_recent_sessions(limit=20)
        return [s.model_dump() for s in sessions]

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.model_dump()

    @router.get("/sessions/{session_id}/events")
    async def get_session_events(session_id: str):
        events = await db.get_events_for_session(session_id)
        return [e.model_dump() for e in events]

    @router.get("/current")
    async def get_current():
        tree = tracker.cost_tree()
        if not tree:
            return {"active": False}
        session = await db.get_session(tracker.session_id or "")
        return {
            "active": True,
            "session": session.model_dump() if session else None,
            "cost_tree": tree.model_dump(),
            "burn_rate_per_minute": tracker.burn_rate_per_minute(),
        }

    @router.get("/cost-tree")
    async def get_cost_tree():
        tree = tracker.cost_tree()
        if not tree:
            return {}
        return tree.model_dump()

    @router.get("/budget")
    async def get_budget():
        project_spent = 0.0
        if tracker.session_id:
            session = await db.get_session(tracker.session_id)
            project = session.project if session else "default"
            project_spent = await db.get_project_cost(project)
        status = budget.check(
            session_spent=tracker.session_cost,
            project_spent=project_spent,
            burn_rate_per_minute=tracker.burn_rate_per_minute(),
        )
        return status.model_dump()

    return router
