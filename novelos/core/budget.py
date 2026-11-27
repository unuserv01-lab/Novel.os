"""Budget guard: production stops (and can resume) instead of silently burning API credit."""

from __future__ import annotations


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, cap: float, spent: float = 0.0):
        self.cap = cap
        self.spent = spent

    def check(self, amount: float, what: str = "call") -> None:
        """Non-mutating pre-check: would `charge(amount)` succeed? Raises
        BudgetExceeded if not, without spending anything. The runner calls
        this before a step runs; the step's own charges remain the exact
        enforcement."""
        if self.spent + amount > self.cap + 1e-9:
            raise BudgetExceeded(f"cost cap ${self.cap:.2f} would be exceeded by {what} (spent ${self.spent:.2f})")

    def charge(self, amount: float, what: str = "call") -> None:
        """Reserve `amount` BEFORE making the call, so the cap is never overshot."""
        self.check(amount, what)
        self.spent += amount
