# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The satisficing price of a physics structure (kae.physics.priors.hinge) and the placer's
place_phys_hinge setting: off by default and then nothing changes; on, a structure below the
threshold costs nothing, the price never falls as utilisation grows, and the macro ranking and
the report's scorecard stay on the raw utilisation."""
import math
import random
from pathlib import Path

import pytest

from kae.physics import priors as PR
from kae.physics.place_terms import Terms
from kae.physics.priors import Knobs
from place_terms_fixtures import buck_board, decap_board

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"
US = [i / 200.0 for i in range(0, 1201)] + [6.5, 9.99, 10.0, 10.01, 30.0, 1e3]


@pytest.mark.parametrize("theta", [0.0, 0.3, 0.7, 1.0])
@pytest.mark.parametrize("beta", [0.0, 4.0])
@pytest.mark.parametrize("u_sat", [3.0, 10.0])
def test_hinge_is_zero_below_theta_one_at_budget_and_never_falls(theta, beta, u_sat):
    f = [PR.hinge(u, theta, beta, u_sat) for u in US]
    assert all(v == 0.0 for u, v in zip(US, f) if u <= theta)
    assert all(v > 0.0 for u, v in zip(US, f) if u > theta)
    assert all(b >= a for a, b in zip(f, f[1:]))                       # monotone in u
    assert all(b > a for (ua, a), (ub, b) in zip(zip(US, f), zip(US[1:], f[1:])) if ua >= theta and ub > ua)
    assert PR.hinge(1.0, theta, beta, u_sat) == pytest.approx(0.0 if theta == 1.0 else 1.0)
    for u0 in (theta, 1.0, u_sat):                                     # continuous at every joint
        if u0 > 0:
            assert PR.hinge(u0 + 1e-9, theta, beta, u_sat) - PR.hinge(u0 - 1e-9, theta, beta, u_sat) < 1e-6
    # above budget: the ramp's slope carried on, plus the quadratic penalty
    s = 1.0 if theta == 1.0 else 1.0 / (1.0 - theta)
    assert PR.hinge(2.0, theta, beta, u_sat) == pytest.approx((2.0 - theta) * s + beta)
    # far over budget the tail is logarithmic: an estimator outlier does not outbid everything
    if beta:
        assert PR.hinge(1e3, theta, beta, u_sat) < 0.05 * beta * 999.0 ** 2


def test_hinge_at_theta_zero_is_phi_and_bad_thresholds_are_refused():
    for u in US:
        assert PR.hinge(u, 0.0, 4.0, 10.0) == pytest.approx(PR.phi(u, 4.0, 10.0), rel=1e-12)
    assert PR.check_hinge("0.7", 4) == (0.7, 4.0)
    for theta, beta in ((-0.1, 4.0), (1.01, 4.0), (0.7, -1.0), (float("nan"), 4.0)):
        with pytest.raises(ValueError):
            PR.check_hinge(theta, beta)


def _terms():
    b, brief = buck_board()
    T = Terms(b, brief, knobs=Knobs(jit="off", barrier=0.0, u_sat=3.0))    # the placer's knobs
    return T, T.bv.pose0()


def _moves(T, poses, n=40, seed=3):
    rng = random.Random(seed)
    uu = sorted(T.parts())
    for _ in range(n):
        u = rng.choice(uu)
        x, y, r, s = poses[u]
        yield u, (x + rng.uniform(-4, 4), y + rng.uniform(-4, 4), rng.choice((0.0, 90.0, 180.0, 270.0)), s)


@pytest.mark.parametrize("theta", [0.7, 1.0])
def test_terms_price_every_structure_by_the_hinge_and_switch_back_exactly(theta):
    T, poses = _terms()
    raw_total = T.total(poses)
    raw_rows = {r["id"]: (r["util"], r["cost"]) for r in T.breakdown(poses)}
    raw_deltas = [T.delta(poses, [u], [q]) for u, q in _moves(T, poses)]
    assert {"commutation", "thermal"} <= {r["kind"] for r in T.breakdown(poses)}

    T.set_hinge(theta, 4.0)
    rows = T.breakdown(poses)
    for r in rows:                              # same raw utilisation, the hinge's price
        assert r["util"] == raw_rows[r["id"]][0]
        assert r["cost"] == pytest.approx(r["confidence"] * PR.hinge(r["util"], theta, 4.0, 3.0), abs=1e-12)
        assert (r["cost"] == 0.0) == bool(r["util"] <= theta)
    assert any(r["util"] <= theta for r in rows) and any(r["util"] > theta for r in rows)
    assert T.total(poses) == pytest.approx(sum(r["cost"] for r in rows), rel=1e-9)
    for u, q in _moves(T, poses):               # the incremental price is the hinge's too (thermal included)
        p2 = dict(poses)
        p2[u] = q
        assert T.delta(poses, [u], [q]) == pytest.approx(T.total(p2) - T.total(poses), rel=1e-6, abs=1e-9)

    T.set_hinge(None)                           # off again: bit for bit what it was
    assert T.total(poses) == raw_total
    assert {r["id"]: (r["util"], r["cost"]) for r in T.breakdown(poses)} == raw_rows
    assert [T.delta(poses, [u], [q]) for u, q in _moves(T, poses)] == raw_deltas


def test_a_structure_inside_its_threshold_moves_for_free_and_margin_is_not_rewarded():
    """Under the linear price a decoupling loop at half its budget still pays to tighten; under
    the hinge every pose below the threshold costs the same, nothing, and a pose over budget
    costs more than under the linear price."""
    b, brief = decap_board()
    T = Terms(b, brief, knobs=Knobs(jit="off", barrier=0.0, u_sat=3.0))
    poses = T.bv.pose0()
    cap = poses["uuid-C1"]
    at = {x: {**poses, "uuid-C1": (x, cap[1], cap[2], cap[3])} for x in (17.0, 19.0, 22.0, 30.0)}
    util = {x: T.breakdown(p)[0]["util"] for x, p in at.items()}
    assert util[19.0] < util[17.0] < 0.7 < util[22.0] < 1.0 < util[30.0] < 3.0
    lin = {x: T.total(p) for x, p in at.items()}
    assert lin[19.0] < lin[17.0] < lin[22.0] < lin[30.0]         # linear: margin below budget is rewarded
    assert T.delta(at[17.0], ["uuid-C1"], [at[19.0]["uuid-C1"]]) < 0
    T.set_hinge(0.7)
    hin = {x: T.total(p) for x, p in at.items()}
    assert hin[19.0] == hin[17.0] == 0.0 < hin[22.0] < hin[30.0]
    assert T.delta(at[17.0], ["uuid-C1"], [at[19.0]["uuid-C1"]]) == 0.0
    assert hin[30.0] > lin[30.0]                                 # over budget is priced harder than before
    T.set_hinge(1.0)
    one = {x: T.total(p) for x, p in at.items()}
    assert one[19.0] == one[17.0] == one[22.0] == 0.0 < one[30.0]


def test_macro_ranking_reads_the_raw_utilisation(monkeypatch):
    """build_macros ranks and refines layouts before the placer switches the terms to the hinge:
    the terms it is handed still price phi."""
    from kae.board import kicad_file
    from kae.place import clusters, pipeline
    seen = []
    real = clusters.build_macros

    def spy(P, structs, **kw):
        seen.append(("macros", kw["terms"].knobs.hinge))
        return real(P, structs, **kw)

    real_ann = pipeline.make_annealer

    def spy_ann(P, st, **kw):
        seen.append(("anneal", kw["terms"].knobs.hinge))
        return real_ann(P, st, **kw)

    monkeypatch.setattr(clusters, "build_macros", spy)
    monkeypatch.setattr(pipeline, "make_annealer", spy_ann)
    res = pipeline.place(kicad_file.load(FIXTURE), seed=0, time_s=10, physics=True, workers=1,
                         opts=dict(place_phys_hinge=0.7, place_severity="strict"))
    assert seen == [("macros", None), ("anneal", 0.7)]
    assert res.terms.knobs.hinge is None        # and the report's scorecard after the annealer is raw again


def test_setting_off_places_identically_and_on_is_reported_and_legal():
    from kae import budget
    from kae.board import kicad_file
    from kae.place.pipeline import phys_hinge, place
    from kae.route.constraints import DEFAULTS
    assert DEFAULTS["place_phys_hinge"] < 0 and DEFAULTS["place_phys_hinge_beta"] == 4.0
    assert phys_hinge() is None and phys_hinge(opts=dict(place_phys_hinge=0.7)) == (0.7, 4.0)
    assert phys_hinge(opts=dict(place_phys_hinge=1, place_phys_hinge_beta=2)) == (1.0, 2.0)
    with pytest.raises(ValueError, match="place_phys_hinge"):
        phys_hinge(opts=dict(place_phys_hinge=1.5))
    from kae.joint.cli import _known_key           # the experiment's arms: kae.joint.cli --set place_phys_hinge=0.7
    assert _known_key("place_phys_hinge") and _known_key("place_phys_hinge_beta")

    def run(opts):
        # counted work: the same seed gives the same placement whatever the host's load
        budget.set_mode("work")
        try:
            return place(kicad_file.load(FIXTURE), seed=0, time_s=20, physics=True, workers=1, opts=opts)
        finally:
            budget.set_mode("time")

    base, off = run(None), run(dict(place_phys_hinge=-1))
    assert base.poses and off.poses == base.poses                       # default = off = today's placement
    assert "phys_hinge" not in base.report and "phys_hinge" not in off.report
    assert off.report["anneal_cost"] == base.report["anneal_cost"]
    for theta in (0.7, 1.0):
        on = run(dict(place_phys_hinge=theta))
        rep = on.report
        assert rep["phys_hinge"] == dict(theta=theta, beta=4.0)
        assert rep["legal_grid"] and rep["exact"] == []
        # the fixture's one structure sits far below budget: free under the hinge, priced before
        assert base.report["anneal_cost"]["annealed_terms"]["phys"] > 0
        assert rep["anneal_cost"]["annealed_terms"]["phys"] == 0.0
        card = rep["scorecard"]                                          # the scorecard stays the raw one
        assert card["structures"] == base.report["scorecard"]["structures"] and card["total_linear"] > 0
        assert math.isfinite(card["total"])
