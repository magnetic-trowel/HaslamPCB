# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose oracle for the pose-transplant diagnostic: the human poses of each pose tier's parts, read
from a joint-fixed task's human placement outside the method's sandbox, and checked with the
harness's own placement check before any run uses them.

    pose_oracle.py build --boards FILE --tiers big,mid --out DIR [--exclusions FILE] [--harness SHA]

For each board: prepare (or take from the kaeres task cache) the place-fixed task with the
harness at SHA (the baseline tag by default); for each tier, write the task input with the
tier's parts moved to their human poses (kae's S-expression writer; the other free parts stay
staged off the board, as in the input) and score that board the way score_joint_task judges a
placement: the transplant-placement rebuild with zones, KiCad DRC, the placement error types
(kaebench.score.PLACEMENT_ERROR_TYPES), and pads outside the outline beyond the human layout's.
A tier is legal when it adds no placement error over the task input's own DRC (errors of the
locked parts, which every method inherits) and no part outside; otherwise it carries the
reason. DIR/<board_key>.json is what `kae.joint.cli run --set pose_tier=T --set pose_source=DIR`
reads (kae.place.pose_tiers.held_poses); --exclusions writes {board: reason} for the boards with
an illegal tier or no task, the input of `kaeres sprint --exclude`.

Runs KiCad: queue it (kaeq). Needs kae (loader, writer) and kaebench and kaeres importable:
PYTHONPATH=bench/src:kae/src:tools/kaeres with a kae venv's python.
"""
import argparse
import json
import os
import sys
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kae.place.pose_tiers import BIG_PADS, ORACLE_SCHEMA, board_key, tier_uuids

INPUTS = ["place-fixed", "route"]       # what a joint-fixed kaeres job prepares (so its task cache serves)


def excess_errors(errors, base, types):
    """Placement errors of `errors` above the task input's count `base`, per type."""
    return {k: v - base.get(k, 0) for k, v in sorted(errors.items()) if k in types and v > base.get(k, 0)}


def tier_verdict(excess, outside, held_refs):
    """(legal, reason) of one tier's held poses."""
    why = []
    if excess:
        why.append("the held human poses add placement errors over the task input's own: "
                   + ", ".join(f"{k} {v}" for k, v in excess.items()))
    if outside:
        why.append(f"{outside} held parts have more pads outside the outline than in the human layout")
    if not held_refs:
        why.append("the tier holds no part beyond the task's fixed ones")
    return (not why), "; ".join(why) or None


def _measure(score, task, board, wd):
    """score_joint_task's placement measurement of `board` (a full board of the task's footprints)."""
    from kaebench.prepare import board_path
    staged, tr = score._rebuild("transplant-placement", board, board_path(task / "place-fixed" / "input"),
                                task / "reference", wd, board_path(task / "reference"), flags=("--zones",))
    if not tr.get("loadable"):
        raise RuntimeError(f"rebuild failed: {tr.get('error')}")
    st, drc = score._measure(staged, wd)
    return st, drc, tr


def board_oracle(bid, task, tiers, big_pads, wd):
    """The oracle record of one board from its prepared task directory."""
    from kae.board.kicad_file import load
    from kae.place.writer import write
    from kaebench import score
    from kaebench.prepare import board_path
    rec = json.loads((task / "task.json").read_text())
    inp, hum = board_path(task / "place-fixed" / "input"), board_path(task / "place-fixed" / "human-placement")
    a, h = load(inp), load(hum)
    if {f.uuid for f in a.footprints} != {f.uuid for f in h.footprints}:
        raise RuntimeError("the task input and its human placement have different footprints")
    hp = {f.uuid: (f.x, f.y, f.rot, f.side) for f in h.footprints}
    types = score.PLACEMENT_ERROR_TYPES
    _, base, _ = _measure(score, task, inp, wd / "input")
    base_err = {k: v for k, v in base["errors_by_type"].items() if k in types}
    allowed = rec["reference"].get("pads_outside", {})
    out = dict(schema=ORACLE_SCHEMA, board=bid, key=board_key(a), big_pads=big_pads, task_spec=rec.get("task_spec"),
               input_placement_hash=rec["tasks"]["place-fixed"]["input_stats"]["placement_hash"],
               input_placement_errors=base_err, tiers={})
    for t in tiers:
        uu = tier_uuids(a, t, big_pads)
        fixed = {f.uuid for f in a.footprints if f.locked}
        refs = sorted(f.ref for f in a.footprints if f.uuid in uu - fixed)
        check = wd / t / "check" / "board.kicad_pcb"
        write(str(inp), str(check), {u: hp[u] for u in uu}, mode="sexpr")
        st, drc, _ = _measure(score, task, check, wd / t / "score")
        errs = {k: v for k, v in drc["errors_by_type"].items() if k in types}
        exc = excess_errors(errs, base_err, types)
        outside = score.outside_count([r for r in st["placement"] if r["uuid"] in uu], allowed)
        legal, reason = tier_verdict(exc, outside, refs)
        out["tiers"][t] = dict(held={u: list(hp[u]) for u in sorted(uu)}, refs=refs, legal=legal, reason=reason,
                               placement_errors=errs, excess=exc, outside=outside)
    return out


def _task(bid, harness, ws):
    """A prepared joint-fixed task of board bid by harness (kaeres's own prepare and task cache)."""
    import kaeres as K
    row = K.corpus_rows()[bid]
    src = ws / "src" / bid
    src.mkdir(parents=True, exist_ok=True)
    for p in (K.CORPUS / row["path"]).iterdir():
        if (p.name.startswith("board.") or p.name == "row.json") and not (src / p.name).exists():
            os.symlink(p, src / p.name)
    env = dict(os.environ)
    env.update({k: v for k, v in K.env_sh().items() if k not in env})
    binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
    env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(K.CORPUS.resolve())]))
    task, rc, to = K._prepare(bid, harness, INPUTS, ws, env, ws / f"prepare-{bid[:40]}.log", {})
    if task is None or not (task / "place-fixed" / "human-placement").is_dir():
        raise RuntimeError(f"no place-fixed task (prepare rc {rc}{', timed out' if to else ''})")
    return task


def cmd_build(a):
    import kaeres as K
    boards = [w for ln in Path(a.boards).read_text().splitlines() for w in ln.split("#", 1)[0].split()[:1]]
    tiers = [t for t in a.tiers.split(",") if t]
    harness = K.git(K.main_repo(), "rev-parse", f"{a.harness}^{{commit}}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(os.environ.get("KAEQ_SCRATCH") or tempfile.mkdtemp(prefix="pose-oracle-", dir="/var/tmp"))
    excl, summary = {}, {}

    def one(bid):
        ws = root / bid
        try:
            os.environ.setdefault("KAE_WRITER", "sexpr")
            o = board_oracle(bid, _task(bid, harness, ws), tiers, a.big_pads, ws / "oracle")
        except Exception as e:  # a board without an oracle is excluded with its reason
            traceback.print_exc()
            return bid, None, f"no pose oracle: {type(e).__name__}: {e}"
        (out / f"{o['key']}.json").write_text(json.dumps(o, indent=1) + "\n")
        bad = {t: v["reason"] for t, v in o["tiers"].items() if not v["legal"]}
        return bid, o, "; ".join(f"tier {t}: {r}" for t, r in bad.items()) or None

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        for bid, o, why in ex.map(one, boards):
            summary[bid] = dict(key=o and o["key"], excluded=why,
                                tiers={t: dict(legal=v["legal"], held=len(v["refs"]), excess=v["excess"])
                                       for t, v in ((o or {}).get("tiers") or {}).items()})
            if why:
                excl[bid] = why
            print(f"{bid}: {'excluded: ' + why if why else 'ok'}", flush=True)
    (out / "summary.json").write_text(json.dumps(dict(harness=harness, tiers=tiers, big_pads=a.big_pads,
                                                      boards=summary), indent=1) + "\n")
    if a.exclusions:
        Path(a.exclusions).write_text(json.dumps(excl, indent=1) + "\n")
    print(f"{len(boards) - len(excl)} of {len(boards)} boards usable; {len(excl)} excluded", flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pose_oracle", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--boards", required=True, help="board ids, one per line (a suite file)")
    b.add_argument("--tiers", default="big,mid")
    b.add_argument("--out", required=True, help="the oracle directory (pose_source)")
    b.add_argument("--exclusions", help="write {board: reason} of the boards to leave out")
    b.add_argument("--harness", default="baseline/2026-w47", help="the harness that prepares the tasks")
    b.add_argument("--big-pads", type=int, default=BIG_PADS)
    b.add_argument("-j", "--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    return cmd_build(a)


if __name__ == "__main__":
    sys.exit(main())
