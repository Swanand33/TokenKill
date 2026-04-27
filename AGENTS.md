# AGENTS.md — TokenKill

This file is read by all AI agents working on this repo (Claude Code, Cursor, Cline, Windsurf, GitHub Copilot). Follow every rule here regardless of which tool you are.

## What TokenKill Does

TokenKill is a local Python reverse proxy that sits between AI coding agents and LLM provider APIs. It intercepts HTTP calls, counts tokens in real time, enforces hard budget caps, detects degenerate agent loops via content-hashing, and attributes cost per sub-agent/tool/file. Everything runs locally — SQLite storage, no cloud, no accounts.

**Install:** `pip install tokenkill`
**Run:** `tokenkill start --budget 50` → proxy starts on `localhost:9119`
**Dashboard:** `http://localhost:9119/dashboard/`

## Stack

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Language |
| httpx | latest | Async HTTP client + proxy forwarding |
| FastAPI | latest | Dashboard API + WebSocket |
| uvicorn | latest | ASGI server |
| aiosqlite | latest | Async SQLite |
| Pydantic v2 | latest | Data models |
| tiktoken | latest | Token counting (OpenAI) |
| Click | latest | CLI (`tokenkill start`, `status`, `report`) |
| pytest + pytest-asyncio | latest | Tests |
| ruff + black + mypy | latest | Lint / format / types |

## Module Map

| Module | Single Responsibility |
|--------|-----------------------|
| `proxy.py` | Accept requests, route to provider, forward, extract usage — nothing else |
| `providers/base.py` | Abstract `extract_tokens(response) -> TokenUsage` |
| `providers/anthropic.py` | Anthropic response parsing + pricing |
| `providers/openai.py` | OpenAI response parsing + pricing |
| `providers/google.py` | Google response parsing + pricing |
| `providers/ollama.py` | Ollama response parsing |
| `tracker.py` | Accumulate cost per session/project/tool/file |
| `loop_detector.py` | Hash calls, maintain window, emit alerts |
| `budget.py` | Read config caps, enforce them, return 429/503 |
| `db.py` | SQLite schema + async CRUD — no business logic |
| `models.py` | All Pydantic models shared across modules |
| `dashboard/app.py` | FastAPI app, WebSocket for real-time updates |
| `dashboard/routes.py` | REST endpoints: `/api/sessions`, `/api/current`, `/api/cost-tree` |
| `cli.py` | Click CLI entrypoint |
| `config.py` | Env var loading, defaults, validation |

## Data Flow (per request)

```
1. Agent sends HTTP POST to localhost:9119/v1/messages
2. proxy.py identifies provider from path prefix
3. proxy.py forwards request to real provider API via httpx (body unchanged)
4. Provider returns response
5. providers/anthropic.py extracts TokenUsage from response body
6. loop_detector.py hashes (model + tool_names + last_message) → checks window
7. tracker.py adds CostEvent to session accumulator
8. budget.py checks if session/project cap exceeded → sets flag for next request
9. db.py persists CostEvent asynchronously
10. dashboard WebSocket pushes update to browser
11. proxy.py returns original unmodified provider response to agent
```

Budget enforcement happens on the **incoming** request (step 2), not the outgoing response. If cap exceeded, return 429 before forwarding.

## Code Conventions

### Async

Every function that touches DB, network, or filesystem must be `async def`. No sync calls in the proxy hot path.

```python
# Correct
async def extract_tokens(response: httpx.Response) -> TokenUsage: ...

# Wrong
def extract_tokens(response: httpx.Response) -> TokenUsage: ...
```

### Types

Every function signature has type annotations. Use Pydantic models at all module boundaries. No raw `dict` passed between modules.

```python
# Correct
async def record_event(event: CostEvent) -> None: ...

# Wrong
async def record_event(event: dict) -> None: ...
```

### Imports

Absolute imports only. No relative imports in `src/`.

```python
# Correct
from tokenkill.providers.anthropic import AnthropicProvider

# Wrong
from .anthropic import AnthropicProvider
```

### Error Handling

Catch specific exceptions. Log with structlog key=value. Never swallow silently.

```python
# Correct
except httpx.ConnectError as e:
    logger.error("provider_unreachable", provider=name, error=str(e))
    raise ProxyConnectionError(name) from e

# Wrong
except Exception:
    pass
```

### Logging

Use `structlog`. Key=value pairs, not f-strings. **Never log Authorization headers, API keys, or message content.**

```python
# Correct
logger.info("request_forwarded", provider="anthropic", input_tokens=100)

# Wrong
logger.info(f"Forwarded to anthropic, auth={auth_header}")
```

## Security Rules (non-negotiable)

1. Strip `Authorization` headers before any logging or storage.
2. Request body passes through unmodified — never inspect or store message content.
3. SQLite stores: token counts, content hashes, timestamps, file paths, cost floats. Nothing else.
4. No `eval()`, `exec()`, or `subprocess` with user-controlled data.
5. Never read `.env`, `~/.ssh/*`, `~/.aws/*` — those are the files we protect agents FROM reading.

## Testing Expectations

- All tests use `pytest` + `pytest-asyncio`
- Mark async tests: `@pytest.mark.asyncio`
- No real API calls — mock all HTTP with `httpx.MockTransport`
- Test DB: `":memory:"` SQLite, never a file path
- Test file structure mirrors `src/tokenkill/` exactly under `tests/`
- Run before every commit: `pytest tests/ -x -v`

### Mock response fixtures (in conftest.py)

```python
ANTHROPIC_RESPONSE = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello"}],
    "usage": {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0
    }
}

OPENAI_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
}

GOOGLE_RESPONSE = {
    "candidates": [{"content": {"parts": [{"text": "Hello"}]}}],
    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50, "totalTokenCount": 150}
}
```

## Pricing Reference (April 2026)

| Model | Input $/MTok | Output $/MTok | Cache Read $/MTok |
|-------|-------------|--------------|-------------------|
| claude-sonnet-4-6 | $3.00 | $15.00 | $0.30 |
| claude-opus-4-7 | $15.00 | $75.00 | $1.50 |
| claude-haiku-4-5 | $0.80 | $4.00 | $0.08 |
| gpt-4o | $2.50 | $10.00 | — |
| gpt-4o-mini | $0.15 | $0.60 | — |
| gemini-2.0-flash | $0.10 | $0.40 | — |
| gemini-2.0-pro | $1.25 | $5.00 | — |

## v1 Scope Boundaries

Build only this. Do not add features outside this list.

**In scope:**
- HTTP proxy for Anthropic, OpenAI, Google, Ollama
- Budget caps via env vars
- Loop detection via content-hashing
- Cost attribution per session/tool/file
- Local web dashboard on localhost:9119/dashboard/
- SQLite persistence
- `pip install tokenkill` CLI

**Out of scope for v1:**
- Cloud sync or remote dashboards
- User accounts or authentication
- React/Next.js frontend (single-file HTML only)
- Modifying or inspecting request payload content
- Providers beyond the four listed above
- Team/multi-user features
