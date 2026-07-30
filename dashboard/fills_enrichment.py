"""Backward-compatible alias for ``dashboard.fill_enrichment``."""

from dashboard.fill_enrichment import (
    EXIT_FILL_ACTIONS,
    apply_entry_stop_fallback,
    enrichment_from_decision_payload,
    finite_or_none,
    is_exit_fill_action,
)

__all__ = [
    "EXIT_FILL_ACTIONS",
    "apply_entry_stop_fallback",
    "enrichment_from_decision_payload",
    "finite_or_none",
    "is_exit_fill_action",
]
