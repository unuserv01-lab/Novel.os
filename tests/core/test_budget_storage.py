"""Tests for core/ (budget guard + storage). Moved from tests/test_units.py, unchanged."""

import pytest

from novelos.core.budget import BudgetExceeded, BudgetGuard
from novelos.core.storage import Storage


def test_budget_guard_reserves_before_spending():
    g = BudgetGuard(1.0)
    g.charge(0.6)
    with pytest.raises(BudgetExceeded):
        g.charge(0.6)
    assert g.spent == 0.6  # the refused call was not charged


def test_storage_blocks_path_traversal(tmp_path):
    st = Storage(tmp_path / "s")
    with pytest.raises(ValueError):
        st.write("../escape.png", b"x")
    assert st.write("a/b.png", b"x") == "a/b.png"
