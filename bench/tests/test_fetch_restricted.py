# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A board whose host's robots.txt disallows automated fetching is never downloaded (FRICTION F70)."""
import json

import pytest

from haslambench import fetch


def test_a_restricted_row_is_not_fetched_but_a_cached_one_is_used(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(fetch, "_download", lambda *a, **k: called.append(a) or False)
    e = dict(id="b1", repo="https://codeberg.org/x/y", commit="abc", pcb_path="b.kicad_pcb",
             tags=["host-robots-restricted"])
    with pytest.raises(fetch.Restricted):
        fetch.fetch(e, tmp_path)
    assert called == []
    d = tmp_path / "b1"
    d.mkdir()
    (d / "fetch.json").write_text(json.dumps({"pcb_sha256": "0" * 64}))
    assert fetch.fetch(e, tmp_path)["pcb_sha256"] == "0" * 64
