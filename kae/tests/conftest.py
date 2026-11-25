# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test isolation for kae's process-wide state."""
import pytest


@pytest.fixture(autouse=True)
def _fresh_budget_clock():
    """Each test ends with kae.budget's process clock dropped. A test that runs a CLI in-process (kae.cli place
    --time 45) leaves that run's hard deadline (budget.start_run: HARD_FACTOR x its budget from its start) on the
    shared clock; a pcbnew call minutes later in another test then got a timeout of 0.01 s."""
    yield
    from kae import budget
    budget._clock = None
