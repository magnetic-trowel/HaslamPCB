# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every test runs kae.excite.quantity in strict mode: a value its type forbids raises where it is made, instead of
being marked invalid as in production. A test of the production mode removes KAE_QUANTITY_STRICT itself."""
import pytest


@pytest.fixture(autouse=True)
def _quantity_strict(monkeypatch):
    monkeypatch.setenv("KAE_QUANTITY_STRICT", "1")
