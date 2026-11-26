# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test isolation for haslam's process-wide state. Every test runs haslam.excite.quantity in strict mode: a value its
type forbids raises where it is made, instead of being marked invalid as in production. A test of the production mode
removes HASLAM_QUANTITY_STRICT itself."""
import pytest


@pytest.fixture(autouse=True)
def _fresh_budget_clock():
    """Each test ends with haslam.budget's process clock dropped. A test that runs a CLI in-process (haslam.cli place
    --time 45) leaves that run's hard deadline (budget.start_run: HARD_FACTOR x its budget from its start) on the
    shared clock; a pcbnew call minutes later in another test then got a timeout of 0.01 s."""
    yield
    from haslam import budget
    budget._clock = None


@pytest.fixture(autouse=True)
def _quantity_strict(monkeypatch):
    monkeypatch.setenv("HASLAM_QUANTITY_STRICT", "1")
