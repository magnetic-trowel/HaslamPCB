# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.drc: the unconnected count past kicad-cli's report cap of 499."""
import json

from kae.route import drc


def test_summary_counts_past_the_cap(monkeypatch, tmp_path):
    items = [dict(items=[dict(description=f"Pad 1 [N{i}] of U1")]) for i in range(499)]

    def fake_run(cmd, **kw):
        out = cmd[cmd.index("-o") + 1]
        json.dump(dict(violations=[], unconnected_items=items), open(out, "w"))
        return type("R", (), dict(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(drc, "kicad_cli", lambda: ("kicad-cli",))
    monkeypatch.setattr(drc.subprocess, "run", fake_run)
    monkeypatch.setattr(drc, "uncapped_unconnected", lambda board, timeout=900: 1306)
    b = tmp_path / "board.kicad_pcb"
    b.write_text("(kicad_pcb)\n")
    rep = drc.run(b, tmp_path / "drc.json")
    assert drc.summary(rep)["unconnected"] == 1306
    del items[0]                                    # 498: below the cap DRC's own list is the count
    rep = drc.run(b, tmp_path / "drc2.json")
    assert drc.summary(rep)["unconnected"] == 498 and "unconnected_count" not in rep


def test_summary_counts_with_pcbnew_when_the_project_ignores_unconnected(monkeypatch, tmp_path):
    # the project sets unconnected_items to "ignore": DRC lists none, so 0 from DRC means nothing
    def fake_run(cmd, **kw):
        json.dump(dict(violations=[], unconnected_items=[]), open(cmd[cmd.index("-o") + 1], "w"))
        return type("R", (), dict(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(drc, "kicad_cli", lambda: ("kicad-cli",))
    monkeypatch.setattr(drc.subprocess, "run", fake_run)
    monkeypatch.setattr(drc, "uncapped_unconnected", lambda board, timeout=900: 7)
    b = tmp_path / "board.kicad_pcb"
    b.write_text("(kicad_pcb)\n")
    assert drc.summary(drc.run(b, tmp_path / "a.json"))["unconnected"] == 0     # no project: DRC's list
    pro = dict(board=dict(design_settings=dict(rule_severities=dict(unconnected_items="ignore"))))
    (tmp_path / "board.kicad_pro").write_text(json.dumps(pro))
    assert drc.summary(drc.run(b, tmp_path / "b.json"))["unconnected"] == 7


def test_promote_severities_on_a_staged_copy(tmp_path):
    """kae place's strict profile: the staged project reports the checks it keeps as errors."""
    b = tmp_path / "board.kicad_pcb"
    b.write_text("")
    pro = dict(board=dict(design_settings=dict(rule_severities=dict(courtyards_overlap="ignore", clearance="warning",
                                                                     silk_overlap="warning"))))
    b.with_suffix(".kicad_pro").write_text(json.dumps(pro))
    changed = drc.promote_severities(b, ("courtyards_overlap", "clearance", "shorting_items"))
    assert sorted(changed) == ["clearance", "courtyards_overlap"]
    rs = json.loads(b.with_suffix(".kicad_pro").read_text())["board"]["design_settings"]["rule_severities"]
    assert rs == dict(courtyards_overlap="error", clearance="error", silk_overlap="warning")
    assert drc.promote_severities(tmp_path / "none.kicad_pcb", ("clearance",)) == []


_BOARD = """(kicad_pcb
\t(net 1 "A")
\t(segment
\t\t(start 1 1)
\t\t(end 2 1)
\t\t(width 0.2)
\t\t(layer "F.Cu")
\t\t(net 1)
\t\t(uuid "{u1}")
\t)
\t(via
\t\t(at 2 1)
\t\t(size 0.6)
\t\t(drill 0.3)
\t\t(layers "F.Cu" "B.Cu")
\t\t(net 1)
\t\t(uuid "{u2}")
\t)
\t(segment
\t\t(start 0 0)
\t\t(end 1 1)
\t\t(width 0.2)
\t\t(layer "F.Cu")
\t\t(net 1)
\t\t(uuid "{u3}")
\t)
)
"""
U1, U2, U3 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"


def _shuffled(u1, u2, u3):
    """The same copper as _BOARD in another file order with other UUIDs (as a re-import writes it)."""
    lines = _BOARD.format(u1=u1, u2=u2, u3=u3).split("\n")
    seg1, via, seg3 = lines[2:10], lines[10:18], lines[18:26]
    return "\n".join(lines[:2] + seg3 + via + seg1 + lines[26:])


def test_canonical_copy_is_the_same_whatever_the_file_order_and_uuids(tmp_path):
    a, b = tmp_path / "a.kicad_pcb", tmp_path / "b.kicad_pcb"
    a.write_text(_BOARD.format(u1=U1, u2=U2, u3=U3))
    b.write_text(_shuffled("aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002",
                           "cccccccc-0000-4000-8000-000000000003"))
    back_a, back_b = drc.canonical_copper_order(a, uuids=True), drc.canonical_copper_order(b, uuids=True)
    assert a.read_text() == b.read_text()
    assert sorted(back_a.values()) == sorted([U1, U2, U3])
    assert {back_a[k]: back_b[k] for k in back_a} == {U1: "aaaaaaaa-0000-4000-8000-000000000001",
                                                      U2: "bbbbbbbb-0000-4000-8000-000000000002",
                                                      U3: "cccccccc-0000-4000-8000-000000000003"}


def test_work_mode_report_names_the_boards_items_and_is_written_as_returned(monkeypatch, tmp_path):
    """Work mode judges a canonical copy: the report (returned and on disk) names the board's own UUIDs, is in
    content order and carries the uncapped count, whatever the board file's copper order and UUIDs."""
    from kae import budget
    budget.set_mode("work")
    try:
        def fake_run(cmd, **kw):
            judged = open(cmd[-1]).read()           # KiCad reports the judged copy's UUIDs, in its own order
            import re
            us = re.findall(r'\(uuid "([^"]+)"\)', judged)
            items = [dict(type="unconnected_items", items=[dict(description=f"Track [A] {k}", uuid=u)])
                     for k, u in enumerate(us)]
            items += [dict(type="unconnected_items", items=[dict(description=f"Pad {i} [N] of U1")]) for i in range(496)]
            json.dump(dict(violations=[], unconnected_items=items[::-1]), open(cmd[cmd.index("-o") + 1], "w"))
            return type("R", (), dict(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(drc, "kicad_cli", lambda: ("kicad-cli",))
        monkeypatch.setattr(drc.subprocess, "run", fake_run)
        monkeypatch.setattr(drc, "uncapped_unconnected", lambda board, timeout=900: 777)
        monkeypatch.setattr(drc, "_copper_items", lambda board, timeout: None)     # no KiCad Python here
        reps = []
        for name, text in (("a", _BOARD.format(u1=U1, u2=U2, u3=U3)), ("b", _shuffled(U1, U2, U3))):
            d = tmp_path / name
            d.mkdir()
            (d / "board.kicad_pcb").write_text(text)
            rep = drc.run(d / "board.kicad_pcb", d / "drc.json", cache=False)
            assert json.loads((d / "drc.json").read_text()) == rep
            assert rep["unconnected_count"] == 777
            named = {it["uuid"] for v in rep["unconnected_items"] for it in v["items"] if it.get("uuid")}
            assert named == {U1, U2, U3}
            assert not list(d.glob("drc-canon-*"))
            reps.append(rep)
        # the same copper, in another order: the same report, item for item
        assert reps[0] == reps[1]
    finally:
        budget.set_mode("time")


def test_work_mode_takes_the_uncapped_count_from_the_copper_items_refill(monkeypatch, tmp_path):
    from kae import budget
    budget.set_mode("work")
    try:
        def fake_run(cmd, **kw):
            items = [dict(items=[dict(description=f"Pad 1 [N{i}] of U1")]) for i in range(499)]
            json.dump(dict(violations=[], unconnected_items=items), open(cmd[cmd.index("-o") + 1], "w"))
            return type("R", (), dict(returncode=0, stdout="", stderr=""))
        monkeypatch.setattr(drc, "kicad_cli", lambda: ("kicad-cli",))
        monkeypatch.setattr(drc.subprocess, "run", fake_run)
        monkeypatch.setattr(drc, "_copper_items", lambda board, timeout: dict(items=[], unconnected=1234))

        def no(*a, **k):
            raise AssertionError("a second refill")
        monkeypatch.setattr(drc, "uncapped_unconnected", no)
        b = tmp_path / "board.kicad_pcb"
        b.write_text("(kicad_pcb)\n")
        assert drc.summary(drc.run(b, tmp_path / "drc.json", cache=False))["unconnected"] == 1234
    finally:
        budget.set_mode("time")
