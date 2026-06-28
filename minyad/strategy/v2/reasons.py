"""Reason string helpers for strategy v2 decisions."""

from __future__ import annotations

from datetime import datetime


def adjustment_reason_suffix(*reasons: str | None) -> str:
    adjustment_reasons = "; ".join(reason for reason in reasons if reason)
    if adjustment_reasons:
        return f"; {adjustment_reasons}"
    return "; guard/override adjusted setpoint"


def adjusted_decision_log_due(
    *,
    adjusted: bool,
    setpoint_changed: bool,
    now: datetime,
    last_adjustment_log_at: datetime | None,
    interval_seconds: int,
) -> bool:
    if not adjusted or setpoint_changed:
        return False
    if last_adjustment_log_at is None:
        return True
    return (now - last_adjustment_log_at).total_seconds() >= interval_seconds
