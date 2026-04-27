from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Optional

import structlog

from tokenkill.models import LoopAlert, LoopAlertLevel

logger = structlog.get_logger()

# Thresholds for identical-hash detection
_WARN_THRESHOLD = 3
_PAUSE_THRESHOLD = 5
_KILL_THRESHOLD = 8

# File re-read threshold (within last 10 minutes, checked via DB)
_FILE_READ_THRESHOLD = 5

_WINDOW_SIZE = 50


class LoopDetector:
    def __init__(self) -> None:
        self._window: deque[str] = deque(maxlen=_WINDOW_SIZE)

    def hash_request(self, request_body: dict[str, Any]) -> str:
        """Stable content hash of (model, tool_names, last_message_content)."""
        messages = request_body.get("messages", [])
        last_content = ""
        if messages:
            last = messages[-1]
            content = last.get("content", "")
            if isinstance(content, list):
                # Extract text from content blocks
                parts = [
                    b.get("text", "") or b.get("name", "")
                    for b in content
                    if isinstance(b, dict)
                ]
                last_content = " ".join(parts)
            else:
                last_content = str(content)

        tools = request_body.get("tools", [])
        tool_names = sorted(t.get("name", "") for t in tools if isinstance(t, dict))

        payload = {
            "model": request_body.get("model", ""),
            "tools": tool_names,
            "last_message": last_content[:500],  # cap to avoid huge hashes
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def check(self, request_hash: str) -> Optional[LoopAlert]:
        """Add hash to window and return an alert if thresholds are exceeded."""
        self._window.append(request_hash)

        count = sum(1 for h in self._window if h == request_hash)

        if count > _KILL_THRESHOLD:
            alert = LoopAlert(
                level=LoopAlertLevel.KILL,
                hash_count=count,
                window_size=len(self._window),
                trigger_type="identical_calls",
                repeated_hash=request_hash,
                message=(
                    f"TokenKill: Agent killed — identical request repeated {count}x "
                    f"in last {len(self._window)} calls. Possible infinite loop."
                ),
            )
            logger.warning("loop_kill", hash=request_hash, count=count)
            return alert

        if count > _PAUSE_THRESHOLD:
            alert = LoopAlert(
                level=LoopAlertLevel.PAUSE,
                hash_count=count,
                window_size=len(self._window),
                trigger_type="identical_calls",
                repeated_hash=request_hash,
                message=(
                    f"TokenKill: Agent paused — identical request repeated {count}x "
                    f"in last {len(self._window)} calls. Review and resume manually."
                ),
            )
            logger.warning("loop_pause", hash=request_hash, count=count)
            return alert

        if count > _WARN_THRESHOLD:
            alert = LoopAlert(
                level=LoopAlertLevel.WARNING,
                hash_count=count,
                window_size=len(self._window),
                trigger_type="identical_calls",
                repeated_hash=request_hash,
                message=(
                    f"TokenKill: Warning — identical request repeated {count}x "
                    f"in last {len(self._window)} calls. Possible loop forming."
                ),
            )
            logger.info("loop_warning", hash=request_hash, count=count)
            return alert

        return None

    def check_file_read(self, file_path: str, recent_count: int) -> Optional[LoopAlert]:
        """Return alert if the same file has been read too many times recently."""
        if recent_count >= _FILE_READ_THRESHOLD:
            level = LoopAlertLevel.KILL if recent_count >= _FILE_READ_THRESHOLD * 2 else LoopAlertLevel.WARNING
            return LoopAlert(
                level=level,
                hash_count=recent_count,
                window_size=_FILE_READ_THRESHOLD,
                trigger_type="repeated_file_read",
                file_path=file_path,
                message=(
                    f"TokenKill: File '{file_path}' read {recent_count}x in the last 10 minutes."
                ),
            )
        return None

    def reset(self) -> None:
        self._window.clear()
