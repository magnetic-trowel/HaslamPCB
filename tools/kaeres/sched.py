# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Return-driven restart scheduler for tools/kaeres/restart.py (`--sched return`).

restart.py's fixed schedule runs attempts in batches of --parallel; attempt k gets
first_s * growth**(k // parallel) and, with --resume S, a share S of each later batch continues
from the best board. Every share is a constant. On s2-merit213 (route-only methods) the extra seeds
of batch 0 made no more boards clean, 28-38 % of CPU went to attempts launched after the best one,
resumed attempts removed about 4x more opens per CPU-hour than fresh ones, and boards with more than
20 opens took 22-37 % of CPU without one becoming clean. This module chooses, before each batch,
how many lanes resume and how many start fresh, and whether to stop restarting, from what the
attempts so far returned.

Policy `return` v1 (every threshold is a field of OPTIONS, overridable with --sched-opts):

1. Probe: batch 0 runs `probe_n` fresh attempts at first_s (default: --parallel; 2 with
   `fixed_placement`, a method whose seeds only permute the routing order: the best of two is the
   resume base).
2. Return per action type (fresh, resume): rate = (a0 + opens_closed) / (b0 + cpu_s). In each batch
   the best attempt of a type is credited the drop of the incumbent's unconnected count it made
   against the incumbent before that batch (never negative; batch 0 has no incumbent, so nothing);
   cpu_s is all CPU spent by attempts of the type. Priors (a0, b0) per type and incumbent-opens
   bucket come from `priors` (default: sched_priors.json beside this file, placeholder values).
3. Lanes: budgets stay first_s * growth**batch. A later batch runs `lanes_resume` resume and
   `lanes_fresh` fresh lanes (default 1 + 1: the replay of stored logs found lane width the lever
   that pays). With `adapt`, the --parallel lanes split between resume and fresh in proportion to
   the two rates instead, rounded, with at least `explore_min` lane of the lower-rate type when it
   had none in the last `explore_every` - 1 batches. A resume lane needs a ranked incumbent (else it
   runs fresh). When two fresh attempts of one batch ended with the same rank and CPU within
   `same_cpu_tol` (seeds do not act), later batches run at most one lane of each type. Lanes left
   out are not launched; with `depth_bonus` (default) the plan clock charges a batch its largest
   budget x lanes used / --parallel, so the doubling goes on for more batches in the same --time.
4. Stops, checked before each later batch, b-d each behind an option that is off by default
   (stop_near_miss, stop_futility, stop_capacity): `clean`; `near-miss` (legal incumbent with 1..near_max
   opens, the last batch closed nothing, and there is a --final pass: it gets the plan time left);
   `futility` (opens closed expected in the plan time left at the best rate < min_gain, incumbent
   opens > near_max); `capacity` (>= 2 batches, incumbent opens > cap_min_opens, the best fresh
   counts of the last two batches within cap_tol, resume lanes improved the incumbent by less than
   cap_resume_tol in the last batch).

plan() is a pure function of the history (finished attempts: k, seed, budget, cpu_s, rank,
resumed_from, batch) and the plan seconds left: no clock, no randomness. Every plan is a decision
record with the numbers that made it. Only counted-work mode (KAE_BUDGET=work) is scheduled; in time
mode make() logs one line and returns None, so the wrapper keeps its fixed schedule. Stdlib only.
"""
import json
import math
from pathlib import Path

PRIORS_FILE = Path(__file__).resolve().with_name("sched_priors.json")
TYPES = ("fresh", "resume")
OPTIONS = dict(
    probe_n=0,              # fresh attempts in batch 0; 0 = --parallel (2 with fixed_placement)
    fixed_placement=False,  # the method keeps the input placement: seeds only permute the routing order
    lanes_fresh=1,          # later batches without adapt: this many fresh lanes ...
    lanes_resume=1,         # ... and this many resume lanes (fresh when there is no ranked incumbent)
    depth_bonus=True,       # the plan clock charges a batch max budget x lanes used / --parallel
    adapt=False,            # split --parallel lanes by the two rates instead (with explore_min / explore_every)
    explore_min=1,          # adapt: lanes of the lower-rate type when it is due
    explore_every=2,        # it is due when it had no lane in the last explore_every - 1 batches
    same_cpu_tol=0.02,      # two fresh attempts with one rank and CPU within this share: seeds do not act
    stop_near_miss=False,   # stop rules b-d are off by default: replayed on stored logs they lost 3-20
    stop_futility=False,    # clean boards per method, and a perfect stop rule saves only 7-10 % of CPU
    stop_capacity=False,
    near_max=5,             # near-miss: incumbent opens 1..near_max
    min_gain=1.0,           # futility: fewer opens than this expected from the plan time left
    cap_min_opens=20,       # capacity: incumbent opens above this
    cap_tol=0.10,           # capacity: best fresh counts of the last two batches this close
    cap_resume_tol=0.05,    # capacity: resume lanes improved the incumbent by less than this share
    priors=None,            # {type: {bucket: {per_cpu_h, b0_s}}}; None = sched_priors.json
)
BUCKETS = ((0, "0"), (5, "1-5"), (20, "6-20"), (100, "21-100"))


def load_opts(text):
    """--sched-opts: '' (defaults), a JSON object, or a JSON file. Unknown keys are refused (a typo
    must not silently run the defaults)."""
    if not text:
        user = {}
    elif text.lstrip().startswith("{"):
        user = json.loads(text)
    else:
        user = json.loads(Path(text).read_text())
    bad = sorted(set(user) - set(OPTIONS))
    if bad:
        raise ValueError(f"unknown --sched-opts keys: {bad} (known: {sorted(OPTIONS)})")
    o = dict(OPTIONS, **user)
    if o["priors"] is None:
        o["priors"] = {t: v for t, v in json.loads(PRIORS_FILE.read_text()).items() if t in TYPES}
    return o


def bucket(opens):
    for top, name in BUCKETS:
        if opens <= top:
            return name
    return ">100"


def kind(att):
    return "fresh" if att.get("resumed_from") is None else "resume"


def _rank(att):
    r = att.get("rank") if att else None
    return tuple(r) if r is not None else None


def incumbent(history):
    """The best ranked attempt (lowest rank, the earliest of equals: the wrapper's `best`), None."""
    best = None
    for att in history:
        r = _rank(att)
        if r is not None and (best is None or r < _rank(best)):
            best = att
    return best


def _batches(history):
    out = {}
    for att in history:
        out.setdefault(att["batch"], []).append(att)
    return [out[b] for b in sorted(out)]


def _best(atts):
    ranked = [a for a in atts if _rank(a) is not None]
    return min(ranked, key=_rank) if ranked else None


def _closed(inc, att):
    """Opens `att` closed against the incumbent `inc` before its batch (0 when it is no better
    on legality, or there was no incumbent)."""
    if inc is None or att is None or _rank(att)[0] > _rank(inc)[0]:
        return 0
    return max(0, _rank(inc)[2] - _rank(att)[2])


def charged(max_budget, lanes, parallel, opts):
    """Plan seconds a batch costs: its largest budget, x lanes / parallel with depth_bonus."""
    return max_budget * (min(lanes, parallel) / parallel if opts["depth_bonus"] and parallel else 1.0)


def ledger(history, parallel=1, opts=None):
    """Per batch: the incumbent's opens before and after it, the best of each type, the credit of
    each type, the attempts and CPU of each type, and the batch's plan seconds (charged())."""
    rows, seen = [], []
    for atts in _batches(history):
        inc0 = incumbent(seen)
        seen += atts
        inc1 = incumbent(seen)
        row = dict(batch=atts[0]["batch"], inc_before=_rank(inc0)[2] if inc0 else None,
                   inc_after=_rank(inc1)[2] if inc1 else None,
                   plan_s=charged(max(a.get("budget") or 0 for a in atts), len(atts), parallel,
                                  opts or dict(depth_bonus=False)))
        for t in TYPES:
            mine = [a for a in atts if kind(a) == t]
            b = _best(mine)
            row[t] = dict(n=len(mine), best=_rank(b)[2] if b else None, closed=_closed(inc0, b),
                          cpu_s=round(sum(a.get("cpu_s") or 0.0 for a in mine), 1))
        rows.append(row)
    return rows


def rates(rows, inc_opens, opts):
    """Opens closed per CPU-second of each type, with the prior of the incumbent's opens bucket."""
    out = {}
    for t in TYPES:
        p = opts["priors"][t][bucket(inc_opens if inc_opens is not None else 0)]
        b0 = float(p["b0_s"])
        a0 = float(p["per_cpu_h"]) * b0 / 3600.0
        closed = sum(r[t]["closed"] for r in rows)
        cpu = sum(r[t]["cpu_s"] for r in rows)
        out[t] = dict(rate=(a0 + closed) / (b0 + cpu), a0=round(a0, 3), b0_s=b0, closed=closed, cpu_s=round(cpu, 1))
    return out


def seeds_do_not_act(history, tol):
    """The first pair of fresh attempts of one batch with the same rank and CPU within `tol`
    (a deterministic command run twice), as evidence, else None."""
    for atts in _batches(history):
        fr = [a for a in atts if kind(a) == "fresh" and _rank(a) is not None]
        for i, x in enumerate(fr):
            for y in fr[i + 1:]:
                cx, cy = x.get("cpu_s") or 0.0, y.get("cpu_s") or 0.0
                if _rank(x) == _rank(y) and abs(cx - cy) <= tol * max(cx, cy, 1e-9):
                    return dict(batch=x["batch"], ks=[x["k"], y["k"]], rank=list(_rank(x)), cpu_s=[cx, cy])
    return None


def _since(rows, t):
    """Batches since the last one with a lane of type t (all of them when none had one)."""
    n = 0
    for r in reversed(rows):
        if r[t]["n"]:
            break
        n += 1
    return n


def plan(history, batch, plan_left_s, ctx, opts):
    """The decision before batch `batch`: {action: launch, lanes: [k to resume from, or None for
    fresh, ...], budget} or {action: stop, reason, message}, with the numbers behind it.
    ctx: parallel, first_s, growth, has_final."""
    P = int(ctx["parallel"])
    budget = ctx["first_s"] * ctx["growth"] ** batch
    d = dict(batch=batch, plan_left_s=round(plan_left_s, 1), budget=round(budget, 1))
    if batch == 0:
        n = opts["probe_n"] or (2 if opts["fixed_placement"] else P)
        d.update(action="launch", why="probe", lanes=[None] * min(n, P), fresh=min(n, P), resume=0)
        return d
    rows = ledger(history, P, opts)
    inc = incumbent(history)
    ir = _rank(inc)
    opens = ir[2] if ir else None
    rt = rates(rows, opens, opts)
    d.update(incumbent=dict(k=inc["k"], rank=list(ir)) if inc else None,
             rates_per_cpu_h={t: round(rt[t]["rate"] * 3600, 3) for t in TYPES},
             credit={t: dict(closed=rt[t]["closed"], cpu_s=rt[t]["cpu_s"], a0=rt[t]["a0"], b0_s=rt[t]["b0_s"])
                     for t in TYPES})
    last = rows[-1] if rows else None

    def stop(reason, message, **nums):
        d.update(action="stop", reason=reason, message=message, **nums)
        return d

    # a. clean (the wrapper stops at once on a clean board; this only records it)
    if ir and ir[:2] == (0, 0):
        return stop("clean", f"#{inc['k']} is clean")
    # b. near-miss: a few opens the last batch did not close go to the final pass with the plan time left
    if (opts["stop_near_miss"] and ir and ir[0] == 0 and 1 <= opens <= opts["near_max"] and ctx.get("has_final") and last
            and last["inc_before"] is not None and last["inc_after"] >= last["inc_before"]):
        return stop("near-miss", f"stopped: {opens} opens, the last batch closed none; the final pass gets "
                    f"the {plan_left_s:.0f} s of plan left", opens=opens, last_batch=last)
    plan_used = sum(r["plan_s"] for r in rows)
    cpu_all = sum(r[t]["cpu_s"] for r in rows for t in TYPES)
    cpu_per_plan_s = cpu_all / plan_used if plan_used > 0 and cpu_all > 0 else float(P)
    best_t = max(TYPES, key=lambda t: (rt[t]["rate"] if (t == "fresh" or ir) else -1.0, t == "fresh"))
    expected = rt[best_t]["rate"] * plan_left_s * cpu_per_plan_s
    # c. futility
    if opts["stop_futility"] and ir and opens > opts["near_max"] and expected < opts["min_gain"]:
        return stop("futility", f"stopped: {opens} opens, {expected:.2f} more expected closed in the plan time "
                    f"left at the best rate ({best_t}); see the blocked report", opens=opens,
                    expected_closed=round(expected, 3), best_type=best_t, cpu_per_plan_s=round(cpu_per_plan_s, 3))
    # d. capacity
    if opts["stop_capacity"] and len(rows) >= 2 and ir and opens > opts["cap_min_opens"]:
        f1, f2 = rows[-2]["fresh"]["best"], rows[-1]["fresh"]["best"]
        rb, ib = last["resume"]["best"], last["inc_before"]
        if f1 is not None and f2 is not None and rb is not None and ib:
            spread = abs(f1 - f2) / max(f1, f2, 1)
            gain = (ib - rb) / ib
            if spread <= opts["cap_tol"] and gain < opts["cap_resume_tol"]:
                return stop("capacity", f"stopped: {opens} opens stable across seeds and budgets; see the "
                            "blocked report", opens=opens, fresh_best=[f1, f2], fresh_spread=round(spread, 4),
                            resume_best=rb, resume_gain=round(gain, 4))
    # lanes
    if not opts["adapt"]:
        nr = min(opts["lanes_resume"], P) if ir else 0
        n = dict(resume=nr, fresh=min(opts["lanes_fresh"] + (0 if ir else opts["lanes_resume"]), P - nr))
        why = f"fixed lanes {opts['lanes_resume']} resume + {opts['lanes_fresh']} fresh" + (
            "" if ir else "; no ranked incumbent: resume lanes run fresh")
    elif ir is None:
        n = dict(fresh=P, resume=0)
        why = "adapt; no ranked incumbent: all fresh"
    else:
        rf, rr = rt["fresh"]["rate"], rt["resume"]["rate"]
        nr = int(math.floor(P * rr / (rr + rf) + 0.5)) if rr + rf > 0 else 0
        n = dict(fresh=P - nr, resume=nr)
        why = "adapt: split by rate"
        low = "fresh" if rf <= rr else "resume"
        due = _since(rows, low) >= max(1, opts["explore_every"]) - 1
        if due and n[low] < opts["explore_min"]:
            n[low] = min(P, opts["explore_min"])
            n["resume" if low == "fresh" else "fresh"] = P - n[low]
            why += f"; explore {low}"
    dup = seeds_do_not_act(history, opts["same_cpu_tol"])
    if dup:
        n = {t: min(1, v) for t, v in n.items()}
        d["seeds_do_not_act"] = dup
        why += "; seeds do not act: at most one lane of each type"
    used = n["fresh"] + n["resume"]
    d.update(action="launch", why=why, fresh=n["fresh"], resume=n["resume"],
             lanes=([inc["k"]] * n["resume"] if inc else []) + [None] * n["fresh"], expected_closed=round(expected, 3),
             plan_charge_s=round(charged(budget, used, P, opts), 1), depth_bonus=bool(opts["depth_bonus"]))
    return d


class Return:
    """The stateful side for restart.py: numbers the batches, keeps the lanes of the current one
    and every decision. lane() is asked once per attempt slot; `new_batch` when none runs."""

    def __init__(self, opts, parallel, first_s, growth, has_final, log=print):
        self.opts, self.log = opts, log
        self.ctx = dict(parallel=parallel, first_s=first_s, growth=growth, has_final=bool(has_final))
        self.kb, self.batch, self.lanes, self.budget = {}, -1, [], 0.0
        self.decisions, self.stop, self.plan_left_s = [], None, None

    def history(self, done):
        return [dict(k=d["k"], seed=d.get("seed"), budget=d.get("budget"), cpu_s=d.get("cpu_s"), rank=d.get("rank"),
                     resumed_from=d.get("resumed_from"), batch=self.kb[d["k"]])
                for d in done if isinstance(d.get("k"), int) and d["k"] in self.kb]

    def lane(self, done, left, new_batch, k):
        """(budget, k of the attempt whose board to resume or None) for attempt k, None: no more
        attempts in this batch (or a stop)."""
        self.plan_left_s = left
        if new_batch:
            if self.stop:
                return None
            self.batch += 1
            d = plan(self.history(done), self.batch, left, self.ctx, self.opts)
            self.decisions.append(d)
            if d["action"] == "stop":
                self.stop = d["reason"]
                self.log(f"sched return: {d['message']}")
                return None
            self.lanes, self.budget = list(d["lanes"]), d["budget"]
            self.log(f"sched return: batch {self.batch} {d['resume']} resume + {d['fresh']} fresh at "
                     f"{self.budget:.0f}s ({d['why']}" + (f"; rates/CPU-h {d['rates_per_cpu_h']}" if self.batch else "")
                     + ")")
        if not self.lanes:
            return None
        self.kb[k] = self.batch
        return self.budget, self.lanes.pop(0)

    def charge(self, max_budget, lanes):
        """Plan seconds the batch just launched costs (charged()), recorded in its decision."""
        c = charged(max_budget, lanes, self.ctx["parallel"], self.opts)
        if self.decisions and self.decisions[-1].get("action") == "launch":
            self.decisions[-1].update(launched=lanes, plan_charged_s=round(c, 1))
        return c

    def final_s(self, reserve, plan_left_s):
        """The final pass's seconds after a near-miss stop: max(its reserve, the plan time left)."""
        s = max(reserve, plan_left_s)
        self.decisions.append(dict(action="final", reason=self.stop, reserve_s=round(reserve, 1),
                                   plan_left_s=round(plan_left_s, 1), final_s=round(s, 1)))
        self.log(f"sched return: final pass gets {s:.0f}s (reserve {reserve:.0f}s, plan left {plan_left_s:.0f}s)")
        return s

    def summary(self, done, plan_left_s):
        stop = self.stop
        inc = incumbent(self.history(done))
        if stop is None and inc is not None and _rank(inc)[:2] == (0, 0):
            stop = "clean"
        return dict(policy="return", opts=self.opts, decisions=self.decisions, stop=stop,
                    plan_left_s=round(plan_left_s, 1))


def make(policy, opts_text, work, parallel, first_s, growth, has_final, log=print):
    """The scheduler for --sched `policy`, None in time mode (the fixed schedule runs; one line says so)."""
    if policy != "return":
        raise ValueError(f"unknown --sched {policy!r}")
    opts = load_opts(opts_text)
    if not work:
        log("sched return: acts only in counted-work mode (KAE_BUDGET=work); fixed schedule")
        return None
    return Return(opts, parallel, first_s, growth, has_final, log)
