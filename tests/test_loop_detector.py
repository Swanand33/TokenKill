from __future__ import annotations

import pytest

from tokenkill.loop_detector import LoopDetector
from tokenkill.models import LoopAlertLevel


def test_no_alert_on_first_call():
    det = LoopDetector()
    alert = det.check("abc123")
    assert alert is None


def test_warning_at_threshold():
    det = LoopDetector()
    for _ in range(3):
        det.check("repeathash")
    alert = det.check("repeathash")  # 4th identical
    assert alert is not None
    assert alert.level == LoopAlertLevel.WARNING


def test_pause_at_threshold():
    det = LoopDetector()
    for _ in range(5):
        det.check("repeathash")
    alert = det.check("repeathash")  # 6th identical
    assert alert is not None
    assert alert.level == LoopAlertLevel.PAUSE


def test_kill_at_threshold():
    det = LoopDetector()
    for _ in range(8):
        det.check("repeathash")
    alert = det.check("repeathash")  # 9th identical
    assert alert is not None
    assert alert.level == LoopAlertLevel.KILL


def test_no_alert_for_varied_hashes():
    det = LoopDetector()
    for i in range(20):
        alert = det.check(f"hash_{i}")
        assert alert is None


def test_hash_request_stable():
    det = LoopDetector()
    req = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [{"name": "read_file"}],
    }
    h1 = det.hash_request(req)
    h2 = det.hash_request(req)
    assert h1 == h2


def test_hash_request_differs_on_content():
    det = LoopDetector()
    req1 = {"model": "m", "messages": [{"role": "user", "content": "hello"}]}
    req2 = {"model": "m", "messages": [{"role": "user", "content": "world"}]}
    assert det.hash_request(req1) != det.hash_request(req2)


def test_reset_clears_window():
    det = LoopDetector()
    for _ in range(9):
        det.check("repeathash")
    det.reset()
    alert = det.check("repeathash")
    assert alert is None


def test_file_read_alert():
    det = LoopDetector()
    alert = det.check_file_read("/app/config.py", recent_count=5)
    assert alert is not None
    assert alert.trigger_type == "repeated_file_read"
    assert alert.file_path == "/app/config.py"


def test_file_read_no_alert_below_threshold():
    det = LoopDetector()
    alert = det.check_file_read("/app/config.py", recent_count=3)
    assert alert is None
