from __future__ import annotations

import asyncio
from typing import Optional

import click
import structlog
import uvicorn

from tokenkill import __version__

logger = structlog.get_logger()


@click.group()
@click.version_option(__version__, prog_name="tokenkill")
def main() -> None:
    """TokenKill — cost governor and loop circuit breaker for AI coding agents."""


@main.command()
@click.option("--budget", "-b", type=float, default=None, help="Session budget cap in USD (e.g. 50.0)")
@click.option("--project-budget", type=float, default=None, help="Project budget cap in USD")
@click.option("--port", "-p", type=int, default=9119, show_default=True, help="Proxy port")
@click.option("--project", type=str, default="default", show_default=True, help="Project name")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING"]), default="INFO", show_default=True)
def start(
    budget: Optional[float],
    project_budget: Optional[float],
    port: int,
    project: str,
    log_level: str,
) -> None:
    """Start the TokenKill proxy and dashboard."""
    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(
        {"DEBUG": 10, "INFO": 20, "WARNING": 30}[log_level]
    ))

    from tokenkill.config import load_config
    from tokenkill.db import Database
    from tokenkill.budget import BudgetEnforcer
    from tokenkill.loop_detector import LoopDetector
    from tokenkill.tracker import CostTracker
    from tokenkill.proxy import create_proxy_app
    from tokenkill.dashboard.app import create_dashboard_app

    config = load_config(
        port=port,
        budget_session=budget,
        budget_project=project_budget,
        project=project,
    )

    click.echo(f"\n  TokenKill v{__version__}")
    click.echo(f"  Proxy:     http://{config.proxy.host}:{config.proxy.port}")
    click.echo(f"  Dashboard: http://{config.proxy.host}:{config.proxy.port}/dashboard/")
    click.echo(f"  Project:   {config.proxy.project}")
    if budget:
        click.echo(f"  Budget:    ${budget:.2f} session cap")
    click.echo()

    async def run() -> None:
        db = Database(config.proxy.db_path)
        await db.connect()

        tracker = CostTracker(db, config.proxy.project)
        await tracker.start_session()

        loop_det = LoopDetector()
        budget_enf = BudgetEnforcer(config.budget)

        dashboard_app = create_dashboard_app(db, tracker, budget_enf)
        proxy_app = create_proxy_app(
            config=config,
            db=db,
            tracker=tracker,
            loop_detector=loop_det,
            budget=budget_enf,
            ws_broadcast=dashboard_app.state.broadcast if hasattr(dashboard_app.state, "broadcast") else None,
        )

        # Mount dashboard under proxy app
        proxy_app.mount("/dashboard", dashboard_app)

        server_config = uvicorn.Config(
            proxy_app,
            host=config.proxy.host,
            port=config.proxy.port,
            log_level=log_level.lower(),
            access_log=False,
        )
        server = uvicorn.Server(server_config)
        try:
            await server.serve()
        finally:
            await db.close()

    asyncio.run(run())


@main.command()
def status() -> None:
    """Show current session cost summary."""
    click.echo("No active session found. Is tokenkill running?")


@main.command()
@click.option("--session", type=str, default=None, help="Session ID (default: most recent)")
def report(session: Optional[str]) -> None:
    """Print cost report for a session."""
    asyncio.run(_print_report(session))


async def _print_report(session_id: Optional[str]) -> None:
    from tokenkill.config import load_config
    from tokenkill.db import Database

    config = load_config()
    db = Database(config.proxy.db_path)
    await db.connect()

    try:
        if session_id:
            sess = await db.get_session(session_id)
            sessions = [sess] if sess else []
        else:
            sessions = await db.get_recent_sessions(limit=1)

        if not sessions:
            click.echo("No sessions found.")
            return

        s = sessions[0]
        click.echo(f"\nSession: {s.id}")
        click.echo(f"Project: {s.project}")
        click.echo(f"Started: {s.started_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        click.echo(f"Requests: {s.event_count}")
        click.echo(f"Input tokens:  {s.total_input_tokens:,}")
        click.echo(f"Output tokens: {s.total_output_tokens:,}")
        click.echo(f"Total cost:    ${s.total_cost_usd:.4f}")
    finally:
        await db.close()
