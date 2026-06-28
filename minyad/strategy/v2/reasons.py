"""Reason string helpers for strategy v2 decisions."""

from __future__ import annotations


def adjustment_reason_suffix(*reasons: str | None) -> str:
    adjustment_reasons = "; ".join(reason for reason in reasons if reason)
    if adjustment_reasons:
        return f"; {adjustment_reasons}"
    return "; guard/override adjusted setpoint"
