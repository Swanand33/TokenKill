from __future__ import annotations

import pytest

from tokenkill.budget import BudgetEnforcer
from tokenkill.config import BudgetConfig


def test_no_cap_never_exceeds():
    enf = BudgetEnforcer(BudgetConfig())
    status = enf.check(session_spent=9999.0, project_spent=9999.0)
    assert not status.cap_exceeded
    assert not status.warning_triggered


def test_session_cap_exceeded():
    enf = BudgetEnforcer(BudgetConfig(session_cap=10.00))
    status = enf.check(session_spent=10.01, project_spent=0.0)
    assert status.cap_exceeded


def test_session_cap_warning():
    enf = BudgetEnforcer(BudgetConfig(session_cap=10.00, warning_threshold=0.80))
    status = enf.check(session_spent=8.50, project_spent=0.0)
    assert status.warning_triggered
    assert not status.cap_exceeded


def test_project_cap_exceeded():
    enf = BudgetEnforcer(BudgetConfig(project_cap=50.00))
    status = enf.check(session_spent=0.0, project_spent=51.0)
    assert status.cap_exceeded


def test_pct_calculation():
    enf = BudgetEnforcer(BudgetConfig(session_cap=100.00))
    status = enf.check(session_spent=25.0, project_spent=0.0)
    assert status.session_pct == pytest.approx(0.25)


def test_estimated_minutes_remaining():
    enf = BudgetEnforcer(BudgetConfig(session_cap=10.00))
    status = enf.check(session_spent=5.0, project_spent=0.0, burn_rate_per_minute=0.5)
    assert status.estimated_minutes_remaining == pytest.approx(10.0)


def test_cap_response_body():
    enf = BudgetEnforcer(BudgetConfig(session_cap=5.00))
    status = enf.check(session_spent=6.00, project_spent=0.0)
    body = enf.cap_response_body(status)
    assert "error" in body
    assert "budget" in body["error"]["type"]


def test_warning_header_value():
    enf = BudgetEnforcer(BudgetConfig(session_cap=10.00))
    status = enf.check(session_spent=9.00, project_spent=0.0)
    header = enf.warning_header_value(status)
    assert header is not None
    assert "90" in header


def test_no_warning_header_below_threshold():
    enf = BudgetEnforcer(BudgetConfig(session_cap=10.00))
    status = enf.check(session_spent=5.00, project_spent=0.0)
    assert enf.warning_header_value(status) is None
