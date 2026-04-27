from __future__ import annotations

import pytest
import pytest_asyncio

from tokenkill.db import Database
from tokenkill.config import BudgetConfig, load_config
from tokenkill.budget import BudgetEnforcer
from tokenkill.loop_detector import LoopDetector
from tokenkill.tracker import CostTracker

# --- Mock API response fixtures ---

ANTHROPIC_RESPONSE = {
    "id": "msg_test123",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello!"}],
    "model": "claude-sonnet-4-6",
    "usage": {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    },
}

ANTHROPIC_RESPONSE_WITH_CACHE = {
    **ANTHROPIC_RESPONSE,
    "usage": {
        "input_tokens": 80,
        "output_tokens": 50,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 20,
    },
}

OPENAI_RESPONSE = {
    "id": "chatcmpl-test123",
    "object": "chat.completion",
    "model": "gpt-4o",
    "choices": [{"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
}

GOOGLE_RESPONSE = {
    "candidates": [{"content": {"parts": [{"text": "Hello!"}]}, "finishReason": "STOP"}],
    "modelVersion": "gemini-2.0-flash",
    "usageMetadata": {
        "promptTokenCount": 100,
        "candidatesTokenCount": 50,
        "totalTokenCount": 150,
    },
}

OLLAMA_RESPONSE = {
    "model": "qwen3:30b",
    "message": {"role": "assistant", "content": "Hello!"},
    "done": True,
    "prompt_eval_count": 100,
    "eval_count": 50,
}

ANTHROPIC_REQUEST = {
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 1024,
}

ANTHROPIC_REQUEST_WITH_TOOL = {
    "model": "claude-sonnet-4-6",
    "messages": [
        {"role": "user", "content": "Read the config file"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "read_file",
                    "input": {"path": "/app/config.py"},
                }
            ],
        },
    ],
    "tools": [{"name": "read_file", "description": "Read a file", "input_schema": {}}],
    "max_tokens": 1024,
}


# --- DB fixture (in-memory) ---

@pytest_asyncio.fixture
async def db():
    from pathlib import Path
    database = Database(Path(":memory:"))
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def tracker(db):
    t = CostTracker(db, project="test")
    await t.start_session()
    return t


@pytest.fixture
def loop_detector():
    return LoopDetector()


@pytest.fixture
def budget_no_cap():
    return BudgetEnforcer(BudgetConfig())


@pytest.fixture
def budget_with_cap():
    return BudgetEnforcer(BudgetConfig(session_cap=1.00, project_cap=5.00))
