# Provider API Formats

Reference for token extraction and pricing. Used by `src/tokenkill/providers/*.py`.

---

## Anthropic

**Endpoint:** `POST https://api.anthropic.com/v1/messages`

### Non-streaming response

```json
{
  "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
  "type": "message",
  "role": "assistant",
  "content": [{ "type": "text", "text": "..." }],
  "model": "claude-sonnet-4-6-20260401",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 800
  }
}
```

**Extraction:**
```python
usage["input_tokens"]                   # prompt tokens
usage["output_tokens"]                  # completion tokens
usage["cache_creation_input_tokens"]    # tokens written to cache (billed at 1.25x)
usage["cache_read_input_tokens"]        # tokens read from cache (billed at 0.1x)
```

### Streaming SSE events (in order)

```
event: message_start
data: {"type":"message_start","message":{"usage":{"input_tokens":1234,"cache_read_input_tokens":800}}}

event: content_block_start
event: content_block_delta   (repeated)
event: content_block_stop

event: message_delta
data: {"type":"message_delta","usage":{"output_tokens":567}}

event: message_stop
```

Extract `input_tokens` from `message_start`, `output_tokens` from `message_delta`.

### Pricing (April 2026, per million tokens)

| Model | Input | Output | Cache Write | Cache Read |
|-------|-------|--------|-------------|------------|
| claude-opus-4-7 | $15.00 | $75.00 | $18.75 | $1.50 |
| claude-sonnet-4-6 | $3.00 | $15.00 | $3.75 | $0.30 |
| claude-haiku-4-5 | $0.80 | $4.00 | $1.00 | $0.08 |

---

## OpenAI

**Endpoint:** `POST https://api.openai.com/v1/chat/completions`

### Non-streaming response

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "model": "gpt-4o-2024-11-20",
  "choices": [
    {
      "message": { "role": "assistant", "content": "..." },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 567,
    "total_tokens": 1801
  }
}
```

**Extraction:**
```python
usage["prompt_tokens"]       # input
usage["completion_tokens"]   # output
```

### Streaming SSE

Final chunk carries `usage` when `stream_options: {"include_usage": true}` is set in request.

```
data: {"id":"...","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":50}}
data: [DONE]
```

### Pricing (April 2026, per million tokens)

| Model | Input | Output |
|-------|-------|--------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| o1 | $15.00 | $60.00 |
| o1-mini | $3.00 | $12.00 |
| o3 | $10.00 | $40.00 |
| o3-mini | $1.10 | $4.40 |
| gpt-4-turbo | $10.00 | $30.00 |
| codex-mini-latest | $1.50 | $6.00 |

---

## Google (Gemini)

**Endpoint:** `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`

### Response

```json
{
  "candidates": [
    {
      "content": { "parts": [{ "text": "..." }], "role": "model" },
      "finishReason": "STOP"
    }
  ],
  "modelVersion": "gemini-2.0-flash",
  "usageMetadata": {
    "promptTokenCount": 1234,
    "candidatesTokenCount": 567,
    "totalTokenCount": 1801
  }
}
```

**Extraction:**
```python
usageMetadata["promptTokenCount"]      # input
usageMetadata["candidatesTokenCount"]  # output
```

**Model name:** `response["modelVersion"]`

### Pricing (April 2026, per million tokens)

| Model | Input | Output |
|-------|-------|--------|
| gemini-2.0-flash | $0.10 | $0.40 |
| gemini-2.0-flash-lite | $0.075 | $0.30 |
| gemini-2.0-pro | $1.25 | $5.00 |
| gemini-1.5-pro | $1.25 | $5.00 |
| gemini-1.5-flash | $0.075 | $0.30 |

---

## Ollama (local models)

**Endpoint:** `POST http://localhost:11434/api/chat`

### Response

```json
{
  "model": "qwen3:30b",
  "message": { "role": "assistant", "content": "..." },
  "done": true,
  "done_reason": "stop",
  "prompt_eval_count": 1234,
  "eval_count": 567,
  "eval_duration": 12345678900
}
```

**Extraction:**
```python
response["prompt_eval_count"]   # input tokens
response["eval_count"]          # output tokens
```

**Pricing:** Always $0.00 — local compute, no API cost.

**Note:** `eval_duration` is in nanoseconds. Not used by TokenKill but useful for latency tracking if added later.

---

## Adding a New Provider

1. Create `src/tokenkill/providers/yourprovider.py`
2. Subclass `BaseProvider`
3. Implement `extract_tokens()`, `get_pricing()`, `extract_model()`
4. Add path prefix → provider mapping in `proxy.py::_route_provider()`
5. Add to `providers/__init__.py`
6. Add mock response fixture to `tests/conftest.py`
7. Add `tests/test_providers/test_yourprovider.py`
