# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""accept_guard: on an equal rank, the joint loop refuses a window that breaks a met relation or pushes a coupling
victim over (or further over) budget (obd-solar FRICTION #55, policy-2 iteration 39)."""
import pytest

from haslam.joint import loop as L
from haslam.joint.scorecard import Scorecard, accept, guard_refusal


def _card(physics, victims=None, relations=None, unconnected=0, errors=3):
    # one module carries the routed physics total (physics_total sums min(u, 5)): 16.57 -> 16.09 as logged
    mods = {f"m{k}": 5.0 for k in range(int(physics // 5))}
    mods["rest"] = round(physics - 5.0 * len(mods), 6)
    return Scorecard(unconnected=unconnected, errors=errors, modules=mods, method="board_physics",
                     victims=victims, relations=relations)


# policy-2 iteration 39 as logged: a DRC window, equal KiCad rank, routed physics 16.57 -> 16.09, C311 2.2 -> 15 mm off
# U301.4, the placer's FB pickup 23 -> 773 mV (limit 12 mV), the hot-loop relation near-C311-U301.4 unmet
OLD = _card(16.57, victims={"victim:feedback:U301:8": 23 / 12, "victim:feedback:FB9": 0.48},
            relations={"near-C311-U301.4": True, "near-C306-U301.17": False})
NEW = _card(16.09, victims={"victim:feedback:U301:8": 773 / 12, "victim:feedback:FB9": 0.30},
            relations={"near-C311-U301.4": False, "near-C306-U301.17": False})


def test_iteration_39_was_kept_without_the_guard():
    keep, why = accept(OLD, NEW)
    assert keep and why.startswith("physics better")


@pytest.mark.parametrize("guard, word", [("victims", "victim:feedback:U301:8"), ("relations", "near-C311-U301.4"),
                                         ("both", "near-C311-U301.4")])
def test_iteration_39_is_reverted_with_the_guard(guard, word):
    keep, why = accept(OLD, NEW, guard=guard)
    assert not keep and why.startswith("guard:") and word in why


def test_guard_rules():
    assert guard_refusal(OLD, NEW, "off") is None
    # pushed over budget
    assert guard_refusal(_card(16, victims={"v": 0.9}), _card(15, victims={"v": 1.01}), "victims")
    # already over budget, worse within the tolerance: kept; beyond it: refused
    assert guard_refusal(_card(16, victims={"v": 2.0}), _card(15, victims={"v": 2.1}), "victims") is None
    assert guard_refusal(_card(16, victims={"v": 2.0}), _card(15, victims={"v": 2.5}), "victims")
    # a victim that gets better, or stays under budget, never refuses
    assert guard_refusal(_card(16, victims={"v": 3.0}), _card(15, victims={"v": 1.5}), "victims") is None
    assert guard_refusal(_card(16, victims={"v": 0.2}), _card(15, victims={"v": 0.9}), "victims") is None
    # a relation that was unmet before is not "broken"; nothing measured: nothing to refuse
    assert guard_refusal(_card(16, relations={"r": False}), _card(15, relations={"r": False}), "relations") is None
    assert guard_refusal(_card(16), _card(15), "both") is None
    with pytest.raises(ValueError):
        guard_refusal(OLD, NEW, "always")


def test_rank_still_decides_first():
    better = _card(18.0, victims=NEW.victims, relations=NEW.relations, unconnected=0, errors=1)
    keep, why = accept(OLD, better, guard="both")
    assert keep and why.startswith("rank better")


def test_loop_default_is_off():
    assert L.DEFAULTS["accept_guard"] == "off"
    from haslam.joint.cli import _known_key
    assert _known_key("accept_guard")
