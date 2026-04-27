# ⚡ TokenKill

**Stop your AI coding agent before it empties your wallet.**

TokenKill is a local reverse proxy that sits between your AI coding agent and LLM provider APIs. It enforces budget caps, kills runaway loops, and shows you exactly where every token went — in real time.

[![CI](https://github.com/Swanand33/TokenKill/actions/workflows/ci.yml/badge.svg)](https://github.com/Swanand33/TokenKill/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/tokenkill)](https://pypi.org/project/tokenkill/)

---

## The Problem

> *"I woke up to a $1,600 Claude Code bill. The agent re-read the same 8 files 47 times overnight."*

Runaway agents are real. Compaction loops, SSH retry storms, infinite tool-call cycles — they burn your budget silently and you only find out when the invoice arrives.

**Frontier labs will never fix this.** They make money when you burn tokens.

---

## 60-Second Quickstart

```bash
pip install tokenkill
tokenkill start --budget 50
```

Then point your agent at the proxy. In Claude Code:

```bash
export ANTHROPIC_BASE_URL=http://localhost:9119
claude
```

Open **http://localhost:9119/dashboard/** to watch costs in real time.

---

## What It Does

### Hard Budget Caps
Set a session or project cap. TokenKill pauses the agent before you hit it.

```bash
tokenkill start --budget 50                    # $50 session cap
tokenkill start --budget 50 --project-budget 200   # + $200 project cap
```

At 80% consumed: warning header injected into every response.
At 100%: agent gets HTTP 429 with a human-readable message.

### Loop Circuit Breaker
TokenKill hashes every request. If the agent repeats the same call:

| Repeats | Action |
|---------|--------|
| > 3 | Warning header — loop forming |
| > 5 | HTTP 429 — agent paused |
| > 8 | HTTP 503 — agent killed |

Same file read > 5 times in 10 minutes → also triggers.

### Cost Attribution Tree
See exactly where tokens went:

```
Session total: $1.24
├── by provider
│   ├── anthropic    $1.18
│   └── openai       $0.06
├── by tool
│   ├── read_file    $0.84  (67%)
│   └── bash         $0.34
└── by file
    ├── schema.prisma   $0.41  (re-read 12x)
    └── package.json    $0.23
```

### Predictive Burn-Rate Alert
> "At current rate, you'll hit your $50 cap in **14 minutes**."

Rolling cost-per-minute estimate surfaced in the dashboard and injected as response headers.

### Cross-Provider — One View
Anthropic, OpenAI, Google, and local Ollama models — all in a single dashboard. No switching between billing consoles.

### Live Dashboard
Real-time cost visualization at `http://localhost:9119/dashboard/`

- Cost-over-time chart
- Provider breakdown donut
- Top tools and files by cost
- Budget progress bar with ETA
- Loop alert banner
- Recent events table

### Zero Cloud
Everything runs locally. SQLite storage. No account, no SaaS, no data leaves your machine.

---

## Installation

```bash
pip install tokenkill
```

Requires Python 3.11+.

---

## Usage

### Start the proxy

```bash
# Basic — no cap, just visibility
tokenkill start

# With session budget cap
tokenkill start --budget 50

# With project cap and custom port
tokenkill start --budget 50 --project-budget 200 --port 9119 --project myapp
```

### Point your agent at the proxy

**Claude Code:**
```bash
export ANTHROPIC_BASE_URL=http://localhost:9119
claude
```

**Cursor / Cline / Aider:**
Set the proxy in your tool's API base URL setting to `http://localhost:9119`.

**OpenAI-compatible tools:**
```bash
export OPENAI_BASE_URL=http://localhost:9119/v1
```

### Check status

```bash
tokenkill status          # current session cost
tokenkill report          # full session breakdown
tokenkill report --session <id>   # specific session
```

---

## Configuration

All options available as env vars or CLI flags:

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `TOKENKILL_BUDGET_SESSION` | `--budget` | None | Session cap in USD |
| `TOKENKILL_BUDGET_PROJECT` | `--project-budget` | None | Project cap in USD |
| `TOKENKILL_PORT` | `--port` | `9119` | Proxy port |
| `TOKENKILL_PROJECT` | `--project` | `default` | Project name |
| `TOKENKILL_WARNING_THRESHOLD` | — | `0.80` | Warn at % of cap |
| `TOKENKILL_DB_PATH` | — | `~/.tokenkill/tokenkill.db` | SQLite path |
| `TOKENKILL_LOG_LEVEL` | `--log-level` | `INFO` | DEBUG / INFO / WARNING |

---

## How It Works

```
Your Agent (Claude Code / Cursor / Cline)
         │
         ▼  HTTP to localhost:9119
   ┌─────────────────┐
   │  TokenKill Proxy │  ← budget check → 429 if cap exceeded
   │                 │  ← loop detect  → 429/503 if repeating
   └────────┬────────┘
            │  forward (unmodified)
            ▼
   Provider API (Anthropic / OpenAI / Google / Ollama)
            │
            │  response
            ▼
   ┌─────────────────┐
   │  Token Extractor │  ← parse usage from response body
   │  Cost Tracker    │  ← accumulate per session/tool/file
   │  SQLite DB       │  ← persist
   │  Dashboard WS    │  ← broadcast to browser
   └─────────────────┘
            │
            ▼  original response (unmodified body)
         Agent
```

**Key design decisions:**

- **httpx async proxy** — no TLS cert installation required
- **Pass-through only** — request body is never modified or stored
- **Authorization headers** — forwarded transparently, never logged or stored
- **SQLite** — zero infrastructure, single file at `~/.tokenkill/tokenkill.db`

---

## Supported Providers

| Provider | Token Counting | Pricing | Streaming |
|----------|---------------|---------|-----------|
| Anthropic (Claude) | ✅ | ✅ | ✅ SSE |
| OpenAI (GPT / o-series) | ✅ | ✅ | ✅ SSE |
| Google (Gemini) | ✅ | ✅ | 🔜 |
| Ollama (local models) | ✅ | $0.00 | 🔜 |

---

## Contributing

```bash
git clone https://github.com/Swanand33/TokenKill.git
cd TokenKill
pip install -e ".[dev]"
pytest tests/ -x -v
```

PRs welcome. Please run `ruff check . --fix && black . && mypy src/` before submitting.

---

## Security

TokenKill is a local proxy handling your API keys in transit. Security guarantees:

- **Authorization headers are never logged or stored** — forwarded transparently only
- **Request bodies are never stored** — token counts and hashes only
- **All data stays local** — SQLite on your machine, no telemetry
- **Open source** — audit the code yourself

Found a security issue? Email `workwithswanand@gmail.com`.

---

## License

MIT — see [LICENSE](LICENSE).

---

*Built because $1,600 bills shouldn't happen to anyone.*
