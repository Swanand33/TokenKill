# TokenKill Architecture

## Overview

TokenKill is a local async reverse proxy. It intercepts HTTP requests from AI coding agents to LLM provider APIs, extracts token usage from responses, enforces budget caps, detects loops, and streams cost data to a local dashboard — all without modifying the request or response payload.

---

## Full Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Coding Agent                          │
│          (Claude Code / Cursor / Cline / Aider / Codex)         │
└──────────────────────────┬──────────────────────────────────────┘
                           │  HTTP POST to localhost:9119
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      proxy.py  (FastAPI)                        │
│                                                                 │
│  1. Identify provider from path prefix                          │
│  2. budget.py  → check caps → return 429 if exceeded           │
│  3. loop_detector.py → hash request → return 429/503 if loop   │
│  4. Forward request to upstream (body unmodified)               │
│  5. Receive response                                            │
│  6. providers/*.py → extract TokenUsage from response body     │
│  7. tracker.py → accumulate cost, update session               │
│  8. db.py → persist CostEvent to SQLite                        │
│  9. dashboard WebSocket → broadcast update to browser          │
│  10. Return original response to agent (body unmodified)        │
└──────────┬─────────────────────────────────┬────────────────────┘
           │  forward                         │  original response
           ▼                                  │
┌──────────────────────┐                      │
│   Provider API       │ ─────────────────────┘
│  Anthropic / OpenAI  │
│  Google / Ollama     │
└──────────────────────┘
```

---

## Component Map

```
src/tokenkill/
│
├── proxy.py            ← Entry point for all agent traffic
│                         Routes by path, coordinates all modules
│
├── providers/
│   ├── base.py         ← Abstract: extract_tokens(), get_pricing(), extract_model()
│   ├── anthropic.py    ← Parses usage{} block, handles SSE streaming chunks
│   ├── openai.py       ← Parses usage{} block
│   ├── google.py       ← Parses usageMetadata{} block
│   └── ollama.py       ← Parses prompt_eval_count / eval_count
│
├── loop_detector.py    ← sha256 hash window, warn/pause/kill thresholds
├── budget.py           ← Cap enforcement, warning headers, 429/503 responses
├── tracker.py          ← Cost accumulation per session/tool/file/provider
├── db.py               ← SQLite schema + async CRUD (aiosqlite)
├── models.py           ← All Pydantic models
├── config.py           ← Env vars + CLI arg loading
├── cli.py              ← tokenkill start / status / report
│
└── dashboard/
    ├── app.py          ← FastAPI app, WebSocket connection manager
    ├── routes.py       ← REST API endpoints
    └── static/
        └── index.html  ← Single-file dashboard (Tailwind + Chart.js)
```

---

## Module Responsibilities (strict boundaries)

| Module | Owns | Does NOT touch |
|--------|------|----------------|
| `proxy.py` | Request routing, response forwarding, coordination | Pricing, DB writes, UI |
| `providers/*.py` | Response parsing, pricing tables | HTTP calls, DB, state |
| `loop_detector.py` | Hash window, threshold checks | Cost, DB, budget |
| `budget.py` | Cap math, warning/kill responses | Loops, DB, tracking |
| `tracker.py` | In-memory cost accumulation, burn rate | Enforcement, DB reads |
| `db.py` | SQLite reads/writes | Business logic of any kind |
| `dashboard/` | UI serving, WebSocket broadcast | Cost calculation |

---

## Path Routing

```
/v1/messages              → AnthropicProvider  → api.anthropic.com
/v1/complete              → AnthropicProvider  → api.anthropic.com
/v1/chat/completions      → OpenAIProvider     → api.openai.com
/v1/completions           → OpenAIProvider     → api.openai.com
/v1beta/models/*          → GoogleProvider     → generativelanguage.googleapis.com
/generateContent          → GoogleProvider     → generativelanguage.googleapis.com
/api/*                    → OllamaProvider     → localhost:11434
/dashboard/*              → Dashboard FastAPI  → local (not forwarded)
```

---

## Loop Detection Algorithm

```
Per request:
  hash = sha256(model + sorted_tool_names + last_message_content[:500])
  append hash to deque(maxlen=50)
  count = occurrences of hash in deque

  count > 3  → WARNING  (inject X-TokenKill-Warning header)
  count > 5  → PAUSE    (return HTTP 429, do not forward)
  count > 8  → KILL     (return HTTP 503, do not forward)

Per file read (checked against DB):
  file_path in tool_use input within last 10 minutes > 5 times → WARNING/KILL
```

---

## Budget Enforcement

```
On every incoming request (before forwarding):

  session_pct  = session_spent  / session_cap
  project_pct  = project_spent  / project_cap

  if any pct >= 1.0:
    return HTTP 429 { error: tokenkill_budget_exceeded }

  if any pct >= warning_threshold (default 0.80):
    inject X-TokenKill-Warning header into response

  burn_rate = rolling_avg_cost_per_minute (last 5 min)
  estimated_remaining = (cap - spent) / burn_rate
```

---

## Streaming (SSE)

Anthropic and OpenAI return token counts in SSE streams. TokenKill handles this without blocking the stream:

```
Anthropic SSE:
  event: message_start   → input_tokens, cache tokens
  event: message_delta   → output_tokens (cumulative)
  event: message_stop    → stream ends

Each chunk is forwarded immediately to the agent.
Token counts are accumulated from chunk metadata.
Cost is recorded AFTER the stream ends.
```

---

## SQLite Schema

```sql
sessions (
  id TEXT PRIMARY KEY,
  project TEXT,
  started_at TEXT,
  last_activity TEXT,
  total_cost_usd REAL,
  total_input_tokens INTEGER,
  total_output_tokens INTEGER,
  event_count INTEGER,
  is_active INTEGER
)

cost_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  timestamp TEXT,
  provider TEXT,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cache_creation_tokens INTEGER,
  cache_read_tokens INTEGER,
  cost_usd REAL,
  tool_name TEXT,       -- nullable
  file_path TEXT,       -- nullable
  request_hash TEXT     -- sha256[:16] for loop detection
)
```

---

## Security Constraints

1. `Authorization` / `x-api-key` headers are forwarded to upstream but **never logged, stored, or inspected**
2. Request body is **forwarded unmodified** — content is never stored
3. SQLite stores only: token counts, cost floats, hashes, file paths, timestamps
4. No outbound connections except to the configured provider URLs
5. No telemetry, no analytics, no cloud sync

---

## Dashboard WebSocket Protocol

```
Server → Client (on every cost event):
{
  "type": "cost_event",
  "event": { CostEvent },
  "budget": { BudgetStatus },
  "loop_alert": { LoopAlert } | null
}

Client → Server:
  "ping"   (keepalive every 20s)
```
