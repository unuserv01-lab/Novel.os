"""Shared error types for rooms and their callers.

StateError used to live in the manhwa pipeline, but the explainer room
needs the same error (CLI/API catch it by identity) and rooms must not
import each other — so it lives here in core now.
"""

from __future__ import annotations


class StateError(RuntimeError):
    """Raised when an operation is invalid for the episode's current state
    (unknown episode, wrong room for an edit, export before approval)."""
