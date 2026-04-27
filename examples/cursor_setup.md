# Using TokenKill with Cursor

## Setup (60 seconds)

**1. Start TokenKill**
```bash
tokenkill start --budget 50
```

**2. Configure Cursor to use the proxy**

Open Cursor → Settings (`Ctrl+,`) → search **"OpenAI Base URL"** or **"API Base URL"**

Set:
```
http://localhost:9119/v1
```

For Anthropic models in Cursor, set the Anthropic base URL if available:
```
http://localhost:9119
```

**3. Open the dashboard**

Navigate to `http://localhost:9119/dashboard/`

---

## Via Environment Variable (recommended)

Cursor inherits env vars from the terminal it's launched from.

```bash
# Launch Cursor from terminal with proxy set
ANTHROPIC_BASE_URL=http://localhost:9119 \
OPENAI_BASE_URL=http://localhost:9119/v1 \
cursor .
```

Add to your shell profile so it applies every time:
```bash
# ~/.bashrc or ~/.zshrc
export ANTHROPIC_BASE_URL=http://localhost:9119
export OPENAI_BASE_URL=http://localhost:9119/v1
```

---

## Track Costs Per Project

```bash
cd my-project
tokenkill start --budget 30 --project my-project
cursor .
```

All Cursor activity in this session is attributed to `my-project` in the dashboard.

---

## What Gets Intercepted

| Cursor Feature | Intercepted |
|---------------|-------------|
| Tab autocomplete | ✅ |
| Chat (Cmd+L) | ✅ |
| Composer / Agent mode | ✅ |
| `@codebase` context reads | ✅ file paths tracked |
| Background indexing calls | ✅ |

---

## Loop Detection

Cursor's Agent mode can enter loops when it gets stuck. TokenKill catches:

- Same file re-read > 5 times in 10 minutes → warning
- Identical agent request repeated > 5 times → pause (Cursor shows API error)
- Repeated > 8 times → kill

When Cursor is paused by TokenKill, you'll see an API error in the Cursor chat panel. Start a new chat to resume.

---

## Cline Setup

Cline (VS Code extension) uses the same approach:

1. Open Cline settings in VS Code
2. Set **API Base URL** to `http://localhost:9119`
3. Keep your real API key in Cline's key field — TokenKill forwards it transparently

---

## Aider Setup

```bash
OPENAI_BASE_URL=http://localhost:9119/v1 \
ANTHROPIC_BASE_URL=http://localhost:9119 \
aider --model claude-sonnet-4-6
```

---

## Troubleshooting

**Cursor shows "API connection failed"**
- Check TokenKill is running: `curl http://localhost:9119/dashboard/api/current`
- Restart Cursor from a terminal where the env var is set

**Costs not appearing in dashboard**
- Verify Cursor is actually routing through the proxy by checking TokenKill terminal logs
- Some Cursor versions cache the API base URL — restart Cursor after changing it

**Getting 429 errors unexpectedly**
- Check the dashboard for loop alerts — Cursor's agent may be repeating calls
- Check your budget: `tokenkill report`
- Temporarily raise the cap: restart TokenKill with `--budget 100`
