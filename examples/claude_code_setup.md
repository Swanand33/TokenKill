# Using TokenKill with Claude Code

## Setup (30 seconds)

**1. Start TokenKill**
```bash
tokenkill start --budget 50
```

**2. Point Claude Code at the proxy**
```bash
export ANTHROPIC_BASE_URL=http://localhost:9119
claude
```

Or add it permanently to your shell profile:
```bash
# ~/.bashrc or ~/.zshrc
export ANTHROPIC_BASE_URL=http://localhost:9119
```

**3. Open the dashboard**

Navigate to `http://localhost:9119/dashboard/` — costs appear live as you work.

---

## Per-Project Budget

Run different caps per project:

```bash
# In your project directory
ANTHROPIC_BASE_URL=http://localhost:9119 tokenkill start \
  --budget 25 \
  --project myapp \
  --port 9119
```

---

## Verify It's Working

Run any Claude Code command. You should see:
- Terminal: `INFO session_started session_id=... project=default`
- Dashboard: first cost event appears within seconds
- Response headers include `x-tokenkill-warning` once you hit 80% of your cap

To confirm token interception:
```bash
claude -p "say hello"
tokenkill report
```

The report should show tokens and cost for that single request.

---

## What Gets Intercepted

| Claude Code Feature | Intercepted |
|--------------------|-------------|
| Normal chat | ✅ |
| Agentic sessions (`claude --dangerously-skip-permissions`) | ✅ |
| Tool calls (read_file, bash, etc.) | ✅ cost attributed per tool |
| Streaming responses | ✅ SSE handled |
| Prompt caching | ✅ cache tokens tracked separately |

---

## Loop Detection in Practice

If Claude Code enters a compaction loop or re-reads the same files repeatedly, TokenKill will:

1. **Warning** (3+ repeats): inject `X-TokenKill-Warning` header — visible in dashboard
2. **Pause** (5+ repeats): return HTTP 429 — Claude Code stops and reports an error
3. **Kill** (8+ repeats): return HTTP 503 — hard stop

To resume after a pause, simply restart the Claude Code session.

---

## Stop Tracking

```bash
# Kill the proxy
Ctrl+C

# Unset the env var
unset ANTHROPIC_BASE_URL
```

---

## Troubleshooting

**Claude Code can't connect to the API**
- Check TokenKill is running: `tokenkill status`
- Verify the port: `curl http://localhost:9119/dashboard/api/current`

**Tokens not showing in dashboard**
- Confirm `ANTHROPIC_BASE_URL` is set: `echo $ANTHROPIC_BASE_URL`
- Check for TLS issues — TokenKill uses plain HTTP on localhost

**Claude Code ignores the env var**
- Some Claude Code versions require restarting the terminal after setting env vars
- Try: `ANTHROPIC_BASE_URL=http://localhost:9119 claude`
