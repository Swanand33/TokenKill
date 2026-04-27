from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from tokenkill.budget import BudgetEnforcer
from tokenkill.config import Config
from tokenkill.db import Database
from tokenkill.loop_detector import LoopDetector
from tokenkill.models import LoopAlertLevel, TokenUsage
from tokenkill.providers.anthropic import AnthropicProvider
from tokenkill.providers.base import BaseProvider
from tokenkill.providers.google import GoogleProvider
from tokenkill.providers.ollama import OllamaProvider
from tokenkill.providers.openai import OpenAIProvider
from tokenkill.tracker import CostTracker

logger = structlog.get_logger()

_SAFE_REQUEST_HEADERS = {
    "content-type",
    "accept",
    "user-agent",
    "x-stainless-lang",
    "x-stainless-package-version",
    "x-stainless-runtime",
    "x-stainless-runtime-version",
    "anthropic-version",
    "anthropic-beta",
}


def _strip_sensitive_headers(headers: dict[str, str]) -> dict[str, str]:
    """Pass through only safe headers — never log or inspect Authorization."""
    blocked = {"authorization", "x-api-key", "api-key"}
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


def _route_provider(path: str, config: Config) -> tuple[Optional[BaseProvider], str]:
    """Return (provider, upstream_base_url) based on request path."""
    if path.startswith("/v1/messages") or path.startswith("/v1/complete"):
        return AnthropicProvider(), config.providers.anthropic
    if path.startswith("/v1/chat/completions") or path.startswith("/v1/completions") or path.startswith("/v1/models"):
        return OpenAIProvider(), config.providers.openai
    if "/generateContent" in path or "/streamGenerateContent" in path or path.startswith("/v1beta"):
        return GoogleProvider(), config.providers.google
    if path.startswith("/api/"):
        return OllamaProvider(), config.providers.ollama
    return None, ""


def create_proxy_app(
    config: Config,
    db: Database,
    tracker: CostTracker,
    loop_detector: LoopDetector,
    budget: BudgetEnforcer,
    ws_broadcast: Any = None,
) -> FastAPI:
    app = FastAPI(title="TokenKill Proxy", docs_url=None, redoc_url=None)

    http_client = httpx.AsyncClient(timeout=300.0, follow_redirects=True)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await http_client.aclose()

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    async def proxy(request: Request, path: str) -> Response:
        full_path = "/" + path
        if request.url.query:
            full_path += "?" + request.url.query

        # --- Dashboard passthrough (handled by dashboard router, not here) ---
        if path.startswith("dashboard") or path.startswith("api/sessions"):
            return Response(status_code=404)

        provider, upstream_base = _route_provider("/" + path, config)

        if not provider:
            logger.warning("unknown_route", path=full_path)
            return JSONResponse(
                {"error": {"type": "tokenkill_unknown_route", "message": f"No provider for path: /{path}"}},
                status_code=502,
            )

        # --- Read request body ---
        body_bytes = await request.body()
        request_body: dict[str, Any] = {}
        try:
            if body_bytes:
                request_body = json.loads(body_bytes)
        except json.JSONDecodeError:
            pass

        # --- Budget pre-check (before forwarding, save tokens) ---
        project_spent = await db.get_project_cost(config.proxy.project)
        budget_status = budget.check(
            session_spent=tracker.session_cost,
            project_spent=project_spent,
            burn_rate_per_minute=tracker.burn_rate_per_minute(),
        )

        if budget_status.cap_exceeded:
            return JSONResponse(budget.cap_response_body(budget_status), status_code=429)

        # --- Loop detection ---
        request_hash = loop_detector.hash_request(request_body)
        loop_alert = loop_detector.check(request_hash)

        if loop_alert and loop_alert.level == LoopAlertLevel.KILL:
            return JSONResponse(
                {"error": {"type": "tokenkill_loop_kill", "message": loop_alert.message}},
                status_code=503,
            )
        if loop_alert and loop_alert.level == LoopAlertLevel.PAUSE:
            return JSONResponse(
                {"error": {"type": "tokenkill_loop_pause", "message": loop_alert.message}},
                status_code=429,
            )

        # --- Check file read repetition ---
        file_path = provider.extract_file_path(request_body)
        if file_path and tracker.session_id:
            read_count = await db.get_file_read_count(tracker.session_id, file_path)
            file_alert = loop_detector.check_file_read(file_path, read_count)
            if file_alert and file_alert.level == LoopAlertLevel.KILL:
                return JSONResponse(
                    {"error": {"type": "tokenkill_file_loop", "message": file_alert.message}},
                    status_code=503,
                )

        # --- Forward request upstream ---
        upstream_url = upstream_base.rstrip("/") + "/" + path
        if request.url.query:
            upstream_url += "?" + request.url.query

        forward_headers = dict(request.headers)
        # Re-attach Authorization transparently (never log it)
        safe_log_headers = _strip_sensitive_headers(dict(request.headers))
        logger.debug("forwarding_request", provider=provider.name, path=full_path, headers=safe_log_headers)

        is_streaming = request_body.get("stream", False)

        if is_streaming:
            return await _handle_streaming(
                http_client, upstream_url, forward_headers, body_bytes,
                provider, request_body, request_hash, file_path,
                tracker, budget, budget_status, loop_alert,
            )

        # --- Non-streaming ---
        try:
            upstream_resp = await http_client.request(
                method=request.method,
                url=upstream_url,
                headers=forward_headers,
                content=body_bytes,
            )
        except httpx.ConnectError as e:
            logger.error("upstream_connect_error", provider=provider.name, error=str(e))
            return JSONResponse(
                {"error": {"type": "tokenkill_upstream_error", "message": str(e)}},
                status_code=502,
            )

        response_body: dict[str, Any] = {}
        try:
            response_body = upstream_resp.json()
        except Exception:
            pass

        # --- Extract tokens and record cost ---
        if upstream_resp.status_code == 200 and response_body:
            usage = provider.extract_tokens(response_body)
            model = provider.extract_model(response_body)
            tool_name = provider.extract_tool_name(request_body)

            event = await tracker.record(
                provider=provider,
                usage=usage,
                model=model,
                request_hash=request_hash,
                tool_name=tool_name,
                file_path=file_path,
            )

            # Broadcast to dashboard
            if ws_broadcast:
                project_spent_updated = await db.get_project_cost(config.proxy.project)
                updated_status = budget.check(
                    session_spent=tracker.session_cost,
                    project_spent=project_spent_updated,
                    burn_rate_per_minute=tracker.burn_rate_per_minute(),
                )
                await ws_broadcast(event, updated_status, loop_alert)

        # --- Build response with optional warning headers ---
        response_headers = dict(upstream_resp.headers)
        response_headers.pop("content-encoding", None)  # httpx already decoded
        response_headers.pop("transfer-encoding", None)

        warning = budget.warning_header_value(budget_status)
        if warning:
            response_headers["x-tokenkill-warning"] = warning
        if loop_alert:
            response_headers["x-tokenkill-loop"] = loop_alert.level.value

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=response_headers,
            media_type=upstream_resp.headers.get("content-type", "application/json"),
        )

    return app


async def _handle_streaming(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: bytes,
    provider: BaseProvider,
    request_body: dict[str, Any],
    request_hash: str,
    file_path: Optional[str],
    tracker: CostTracker,
    budget: BudgetEnforcer,
    budget_status: Any,
    loop_alert: Any,
) -> StreamingResponse:
    """Forward SSE stream and extract token counts from terminal event."""
    accumulated_usage = TokenUsage()
    model = request_body.get("model", "unknown")
    anthropic_provider = isinstance(provider, AnthropicProvider)

    async def stream_generator():
        nonlocal accumulated_usage, model

        async with client.stream("POST", url, headers=headers, content=body) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    yield "\n"
                    continue

                yield line + "\n"

                if not anthropic_provider:
                    continue

                # Parse Anthropic SSE chunks to accumulate token counts
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        partial = provider.extract_tokens_from_stream_chunk(chunk)  # type: ignore[attr-defined]
                        if partial:
                            accumulated_usage.input_tokens += partial.input_tokens
                            accumulated_usage.output_tokens += partial.output_tokens
                            accumulated_usage.cache_creation_tokens += partial.cache_creation_tokens
                            accumulated_usage.cache_read_tokens += partial.cache_read_tokens
                        model_val = chunk.get("message", {}).get("model") or chunk.get("model")
                        if model_val:
                            model = model_val
                    except (json.JSONDecodeError, KeyError):
                        pass

        # Record after stream ends
        if accumulated_usage.total_tokens > 0:
            tool_name = provider.extract_tool_name(request_body)
            await tracker.record(
                provider=provider,
                usage=accumulated_usage,
                model=model,
                request_hash=request_hash,
                tool_name=tool_name,
                file_path=file_path,
            )

    response_headers: dict[str, str] = {}
    warning = budget.warning_header_value(budget_status)
    if warning:
        response_headers["x-tokenkill-warning"] = warning

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers=response_headers,
    )
