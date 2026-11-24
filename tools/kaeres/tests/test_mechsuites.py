# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""mechsuites.py and coverage.py: tag expressions, a mechanism suite's choice of boards, coverage holes
and the additions to the tier suites (stdlib only)."""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import coverage as C  # noqa: E402
import mechsuites as M  # noqa: E402
import suites as S  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------------ tag expressions
def tags(**sets):
    return lambda name: set(sets[name])


def test_expression_or_and_not_and_parentheses():
    t = tags(a="12", b="23", c="3", **{"x.1-2": "9", "y+": "1"})
    assert M.members("a | b", t) == set("123")
    assert M.members("a & b", t) == {"2"}
    assert M.members("a - b", t) == {"1"}
    assert M.members("a | b & c", t) == set("123")          # & binds tighter than |
    assert M.members("( a | b ) & c", t) == {"3"}
    assert M.members("( a | b ) - c - a", t) == set()
    assert M.members("x.1-2 | y+", t) == {"9", "1"}          # - and + inside a name are part of the name
    assert M.atoms("( a | x.1-2 ) & sub:mcu - b") == ["a", "x.1-2", "sub:mcu", "b"]


@pytest.mark.parametrize("bad", ["a |", "| a", "( a", "a b", "a )", ""])
def test_expression_errors(bad):
    with pytest.raises(ValueError):
        M.members(bad, tags(a="1", b="2"))


def test_tags_read_suite_files_feature_fields_and_derived_rules(tmp_path):
    (tmp_path / "suites").mkdir()
    (tmp_path / "functional").mkdir()
    (tmp_path / "suites" / "bga.txt").write_text("b1\nb2\n")
    rows = [dict(id="b1", subtypes={"mcu": 1}, hits={"led_addressable": 16}, kinds={"connector": 4, "resistor": 3, "graphic": 9}),
            dict(id="b2", subtypes={}, hits={"led_addressable": 15}, kinds={"connector": 3, "resistor": 1}),
            dict(id="b3", nhits={"usb3_ss": 2}, kinds={"connector": 4, "ic": 5})]
    (tmp_path / "functional" / "features.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
    t = M.Tags(tmp_path)
    assert t.tag("bga") == {"b1", "b2"}
    assert t.tag("sub:mcu") == {"b1"} and t.tag("net:usb3_ss") == {"b3"} and t.tag("kind:ic") == {"b3"}
    assert t.tag("x_connector_dominated") == {"b1"}          # 4 of 7 parts; b2 has 3 connectors, b3 4 of 9
    assert t.tag("x_addressable_leds_16") == {"b1"}
    assert M.members("bga - sub:mcu", t.tag) == {"b2"}


def test_every_mechanism_has_a_valid_expression_and_a_file_safe_name():
    names = [m[0] for m in M.MECHANISMS]
    assert len(names) == len(set(names))
    for name, group, expr, about, *cells in M.MECHANISMS:
        assert name == name.lower() and "/" not in name and " " not in name
        for e in [expr, M.PLACEABLE] + (list(cells[0]) if cells else []):
            assert M.members(e, lambda _: set()) == set()     # parses
            assert all(a in M.DERIVED or a.split(":")[0] in M.FIELDS or ":" not in a for a in M.atoms(e))


# ------------------------------------------------------------------ one suite
class Inp:
    """Inputs filled by hand: n boards i0.., each its own owner, 40 footprints, usable, not human-clean."""

    def __init__(self, n):
        ids = [f"i{k}" for k in range(n)]
        self.ids = ids
        self.hist, self.sweep = {}, {b: 0.05 for b in ids}
        self.routable, self.placeable, self.placed = set(ids), set(ids), set(ids)
        self.human_clean, self.stored = set(), set()
        self.footprints = {b: 40 for b in ids}
        self.layers = {b: 2 for b in ids}
        self.owner = {b: f"host/{b}" for b in ids}
        self.fixed, self.sets = {}, {}

    def members(self, expr):
        return M.members(expr, lambda name: self.sets.get(name, set()))


def pick(inp, boards=None, **kw):
    return M.pick(inp, set(inp.ids if boards is None else boards), random.Random(1), **kw)


def test_usable_needs_a_route_task_a_closed_outline_and_five_footprints():
    inp = Inp(4)
    inp.routable.discard("i0")
    inp.placeable.discard("i1")
    inp.footprints["i2"] = 4
    assert M.usable(inp, set(inp.ids) | {"unknown"}) == {"i3"}


def test_costs_do_not_trust_route_only_history():
    inp = Inp(3)
    inp.hist = dict(i0=0.4, i1=0.01, i2=0.3)
    inp.placed = {"i0", "i2"}                       # i1 only ran under a router
    cost = M.costs(inp)
    assert cost("i0") == 0.4 and cost("i2") == 0.3
    assert cost("i1") == pytest.approx((0.4 + 0.01 + 0.3) / 3)   # at least the mean of its footprint band


def test_pick_human_clean_first_then_stored_control_then_cheapest_one_per_owner():
    inp = Inp(40)
    inp.hist = {b: 0.1 for b in inp.ids}
    inp.hist.update(i0=0.3, i1=0.05, i2=0.2, i3=0.6, i4=0.05)
    inp.human_clean = {"i0", "i3"}
    inp.stored = {"i2"}
    inp.owner["i5"] = inp.owner["i1"]
    ids, tier = pick(inp, n=35)
    assert tier == "sprint" and len(ids) == 35 and len({inp.owner[b] for b in ids}) == 35
    assert ids[:3] == ["i0", "i2", "i1"]            # clean, then stored control, then the cheapest
    assert "i3" not in ids and "i5" not in ids      # over the sprint cap; second board of i1's owner
    assert "i4" in ids


def test_pick_draws_evenly_over_the_footprint_bands_and_over_given_cells():
    inp = Inp(80)
    for k, b in enumerate(inp.ids):
        inp.footprints[b] = (20, 45, 80, 120)[k % 4] if k < 40 else 20
    ids, _ = pick(inp, n=40)
    assert [sum(lo <= inp.footprints[b] <= hi for b in ids) for lo, hi in M.BANDS] == [10, 10, 10, 10]
    odd = {b for b in inp.ids if int(b[1:]) % 2}
    ids, _ = pick(inp, n=40, cells=[odd, set(inp.ids) - odd])
    assert sum(b in odd for b in ids) == 20


def test_pick_drops_the_costliest_while_over_the_arm_budget():
    inp = Inp(60)
    inp.hist = {b: 0.45 for b in inp.ids}
    inp.hist.update({f"i{k}": 0.5 for k in range(5)})
    ids, tier = pick(inp)
    assert tier == "sprint" and len(ids) == int(M.ARM_CPU_H / 0.45) and not set(ids) & {f"i{k}" for k in range(5)}
    inp.hist = {b: 0.5 for b in inp.ids}
    assert len(pick(inp)[0]) == int(M.ARM_CPU_H / 0.5)


def test_pick_fills_past_the_sprint_cap_and_says_ladder():
    inp = Inp(40)
    inp.hist = {b: 2.0 + k for k, b in enumerate(inp.ids)}     # all over the cap
    inp.hist.update(i30=0.1, i31=0.2)
    inp.footprints["i32"] = 900                                 # over the frontier's size: not a sprint board
    inp.hist["i32"] = 0.1
    ids, tier = pick(inp)
    assert tier == "ladder" and len(ids) == M.MIN_SIZE
    assert ids[:2] == ["i30", "i31"] and ids[2] == "i32" and ids[3:5] == ["i0", "i1"]   # then the cheapest past the cap
    few, tier = pick(inp, boards=["i30", "i31"])
    assert few == ["i30", "i31"] and tier == "sprint"           # a kind with two cheap boards: all of them


def test_build_is_deterministic_and_reports_the_pool():
    inp = Inp(50)
    inp.sets = dict(bga=set(inp.ids[:45]), big=set(inp.ids[:20]), small=set(inp.ids[20:45]), other={"x"})
    inp.human_clean = set(inp.ids[:9])
    inp.routable.discard("i44")
    mech = [("bga", "packages", "bga", "a ball grid", ("big", "small")), ("none", "g", "other - other", "nothing")]
    a, b = M.build(inp, 7, mech), M.build(inp, 7, mech)
    assert a == b and a["bga"]["ids"] != M.build(inp, 8, mech)["bga"]["ids"]
    assert a["bga"]["pool"] == dict(boards=45, usable=44, owners=44, human_clean=9)
    assert set(a["bga"]["ids"][:9]) <= inp.human_clean | set(inp.ids) and len(a["bga"]["ids"]) == 44
    assert sum(x in inp.sets["big"] for x in a["bga"]["ids"]) == 20
    assert a["none"]["ids"] == [] and a["none"]["tier"] == "sprint"
    man = M.manifest(inp, a, 7)
    s = man["suites"]["bga"]
    assert (s["boards"], s["human_clean"], s["tier"], s["expr"]) == (44, 9, "sprint", "bga")
    assert "| `bga` | a ball grid | 44 | 9 (20 %)" in M.table(man)


# ------------------------------------------------------------------ coverage
def test_kinds_flag_holes_and_additions_serve_the_most_kinds_cheapest_first(monkeypatch):
    inp = Inp(60)
    inp.human_clean = set(inp.ids[:40])
    inp.sets = dict(common=set(inp.ids), rare=set(inp.ids[:12]), thin=set(inp.ids[50:55]))
    inp.hist = {b: 0.1 for b in inp.ids}
    inp.hist.update(i5=0.01, i6=0.02)
    inp.fixed = {"sprint-frontier": ["i0"], "sprint-quality": ["i1", "i20", "i21", "i22", "i23"], "ladder": ["i2", "i3"], "canary": []}
    monkeypatch.setattr(M, "MECHANISMS", [("common", "g", "common", "c"), ("rare", "g", "rare", "r"), ("thin", "g", "thin", "t")])
    monkeypatch.setattr(C, "ADD", {"sprint-quality": 3, "ladder": 4})
    ks = C.kinds(inp, {"rare": dict(ids=["i4"], tier="sprint")})
    assert ks["common"]["holes"] == [] and ks["rare"]["holes"] == ["12 owners"]
    assert ks["thin"]["holes"] == ["5 owners", "0 human-clean"]
    assert ks["rare"]["suite"] == {"i4"} and ks["rare"]["tier"] == "sprint" and ks["thin"]["tier"] == "-"
    added = C.build_additions(inp, ks)
    # sprint-quality holds 1 rare board (i1): two more, the cheapest rare ones of unused owners; common is served already
    assert added["sprint-quality"] == ["i5", "i6"]
    # the ladder holds 2 boards, both rare and common: 2 more that serve both; thin has no human-clean board
    assert added["ladder"] == ["i10", "i11"]
    text = C.report(inp, ks, added)
    assert "| g | `rare` | 12 | 12 | 12 | 1 | 1+2 | 2+2 | 0 | 1 (sprint) | 12 owners |" in text
    assert "| `thin` | 0 | 0 | 0 | 0 | 5 human-clean boards in all" not in text and "| `thin` | 0 | 0 | 0 | 0 | 0 human-clean boards in all" in text
    assert "| `common` | small | 60 / 40 / 60 · 1-7-4-0-0 |  |  |" in text


def test_additions_keep_the_suites_rules_and_owners(monkeypatch):
    inp = Inp(12)
    inp.human_clean = set(inp.ids)
    inp.sets = dict(k=set(inp.ids))
    inp.footprints.update(i0=10, i1=200, i2=500)     # under the quality range; over it; over the ladder's
    inp.layers["i3"] = 6
    inp.hist["i4"] = 0.9
    inp.owner["i5"] = "host/taken"
    inp.owner["i11"] = "host/taken"
    inp.fixed = {"sprint-frontier": ["i11"], "sprint-quality": [], "ladder": [], "canary": []}
    monkeypatch.setattr(M, "MECHANISMS", [("k", "g", "k", "k")])
    monkeypatch.setattr(C, "ADD", {"sprint-quality": 4, "ladder": 9})
    added = C.build_additions(inp, C.kinds(inp, {}))
    assert added["sprint-quality"] == ["i10", "i6", "i7", "i8"]
    assert added["ladder"] == ["i0", "i1", "i3", "i4", "i9"]      # what is left: no board twice, no owner twice


# ------------------------------------------------------------------ the committed lists
def committed():
    man = REPO / "bench" / "suites" / "mech" / "suites.json"
    return json.loads(man.read_text()) if man.exists() else None


def test_committed_suites_match_their_manifest_and_the_registry():
    man = committed()
    if man is None:
        pytest.skip("no bench/suites/mech/suites.json")
    assert list(man["suites"]) == [m[0] for m in M.MECHANISMS]
    for name, group, expr, *_ in M.MECHANISMS:
        s = man["suites"][name]
        ids = S.read_ids(REPO / "bench" / "suites" / "mech" / f"{name}.txt")
        assert len(ids) == len(set(ids)) == s["boards"] == s["owners"] <= M.SIZE, name
        assert (s["expr"], s["group"]) == (expr, group) and s["tier"] in ("sprint", "ladder"), name
        if s["tier"] == "sprint":
            assert s["cpu_h_per_arm"] <= M.ARM_CPU_H or s["boards"] <= M.MIN_SIZE, name


def test_committed_additions_add_and_never_repeat():
    d = REPO / "bench" / "suites"
    if not (d / "ladder-additions.txt").exists():
        pytest.skip("no additions")
    base = {n: S.read_ids(d / f"{n}.txt") for n in ("sprint-frontier", "sprint-quality", "ladder")}
    seen = {b for ids in base.values() for b in ids}
    for n in ("sprint-quality", "ladder"):
        ids = S.read_ids(d / f"{n}-additions.txt")
        assert len(ids) == len(set(ids)) and not set(ids) & seen, n
        seen |= set(ids)
