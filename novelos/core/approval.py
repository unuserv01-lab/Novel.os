"""Human approval gate: the single place that decides whether an episode
may be approved or exported.

Rooms call these helpers instead of flipping status themselves, so the rule
(only an episode awaiting approval can be approved; export needs approval)
lives here, not in each room. The error is a core error; rooms translate
it to their own StateError so CLI/API behaviour is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone


class ApprovalError(RuntimeError):
    pass


def check_approvable(episode) -> None:
    if episode is None or episode.status != "awaiting_approval":
        raise ApprovalError(
            f"only an episode awaiting approval can be approved "
            f"(status: {episode.status if episode else 'missing'})"
        )


def check_exportable(episode) -> None:
    if episode is None or episode.status not in ("approved", "exported") or episode.approved_at is None:
        raise ApprovalError("export requires human approval first (run approve)")


def mark_approved(episode) -> None:
    episode.status, episode.approved_at = "approved", datetime.now(timezone.utc)
