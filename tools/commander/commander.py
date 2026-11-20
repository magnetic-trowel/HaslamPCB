# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Outside commander: K invocations of a kae command, a chooser picking a knob between them.

    commander.py --input IN --output OUT --time T --seed S --invocations K
                 --commander null|rules|external|replay [--chooser-cmd CMD] [--choices FILE]
                 [--kind route|joint] [--log DIR] -- COMMAND...

COMMAND is one invocation, run with `sh -c`, with @IN@, @OUT@ (this invocation's own output),
@SEED@, @TIME@ (T/K seconds), @SET@ (the knobs: `--set k=v ...`, shell-quoted) and @REPORT@ (its
JSON report) replaced. Invocation i (0-based) gets seed S*1000+i under every commander, so arms are
paired invocation by invocation. After each: read the report, rank the board with kae.rank.board_rank
(illegal, not clean, unconnected, new errors, placement problems; read from the report's `final`,
`repair.final` or top level), keep the best output (atomic replace of OUT), stop when clean, build
the loop-back menu from all reports so far (kae.commander.menu.build_menu where installed, else an
empty menu), ask the chooser, apply its knob to the next invocation.

Commanders (choosers):
- null: next seed, no knobs.
- rules: the first menu item whose knob.kind is "set" or "flag", effect "full", scorer allowed,
  not tried yet. Knobs accumulate; a knob whose invocation ranked worse than the best is dropped again.
- replay: choices from a JSONL file, one line per asking (`{"invocation": i, "choose": id|null,
  "set": [...]}`; matched by invocation, else taken in order).
- external: CMD gets one JSON object on stdin (schema kae.commander-ask/1: board, invocation,
  history, menu, knobs: path of the knob list) and answers one on stdout
  (`{"choose": id|null, "set": ["k=v"], "reason": ""}`). A timeout, bad JSON, unknown item id or
  unknown key is logged as invalid and treated as null. choosers/top_item.py reimplements `rules`
  through this protocol; no LLM or API code lives here.

Every --set key is validated here against the registries (kae.route.cli ignores unknown keys
silently): route accepts bridge.DEFAULT_OPTS and constraints.DEFAULTS; joint accepts loop.DEFAULTS,
stages.STAGE_KEYS, constraints.DEFAULTS and bridge keys spelled bridge.KEY (a bare bridge key is
rewritten to it). The registries are read from the source with ast, so this file needs only stdlib.
Knobs of kind edit_input (rotate, move, flip a part) need a relations file (kae place --relations,
not built yet); they are logged as skipped.

Logs (--log, default OUT's directory/commander): decisions.jsonl, one line per invocation (board,
invocation, seed, knobs, rank, opens, top-5 menu, choice, chooser, reason, CPU seconds), and
summary.json.
"""
import argparse
import ast
import importlib.util
import json
import os
import resource
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KAE = ROOT / "kae/src/kae"
ASK_SCHEMA = "kae.commander-ask/1"
KNOBS_JSON = ROOT / "tools/research/commander/knobs.json"
CHOOSER_TIMEOUT_S = 60.0


# ----------------------------------------------------------------------------- registries and rank
def _literal_keys(path, name):
    """Keys of `NAME = dict(...)` or the strings of `NAME = frozenset({...})` in a source file."""
    for node in ast.parse(Path(path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            v = node.value
            if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "dict":
                return {kw.arg for kw in v.keywords if kw.arg}
            if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "frozenset" and v.args:
                return {e.value for e in v.args[0].elts if isinstance(e, ast.Constant)}
    raise ValueError(f"{path}: no {name}")


def registries(kae=KAE):
    return dict(bridge=_literal_keys(kae / "route/bridge.py", "DEFAULT_OPTS"),
                constraints=_literal_keys(kae / "route/constraints.py", "DEFAULTS"),
                loop=_literal_keys(kae / "joint/loop.py", "DEFAULTS") | {"modules"},
                stages=_literal_keys(kae / "joint/stages.py", "STAGE_KEYS"))


def check_set(kv, kind, reg):
    """(normalized "k=v", None) or (None, why invalid)."""
    k, eq, v = str(kv).partition("=")
    k = k.strip()
    if not eq or not k:
        return None, f"not KEY=VALUE: {kv!r}"
    if kind == "route":
        k = k[7:] if k.startswith("bridge.") else k
        ok = k in reg["bridge"] or k in reg["constraints"]
    else:
        if k in reg["bridge"] and k not in reg["constraints"] and k not in reg["loop"] and k not in reg["stages"]:
            k = "bridge." + k
        ok = (k in reg["loop"] or k in reg["stages"] or k in reg["constraints"]
              or (k.startswith("bridge.") and k[7:] in reg["bridge"]))
    return (f"{k}={v}", None) if ok else (None, f"unknown {kind} key {k!r}")


def _rank_module():
    spec = importlib.util.spec_from_file_location("_kae_rank", KAE / "rank.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RANK = _rank_module()


def counts(rep):
    """(unconnected, new errors, illegal) of a kae report, or None when it has none."""
    if not isinstance(rep, dict):
        return None
    for d in (rep.get("final"), (rep.get("repair") or {}).get("final"), rep):
        if isinstance(d, dict) and isinstance(d.get("unconnected"), (int, float)):
            err = d.get("new_errors", d.get("errors", 0)) or 0
            ill = d.get("illegal", d.get("placement_errors", 0)) or 0
            return int(d["unconnected"]), int(err), int(ill)
    return None


def rank_of(rep, out_exists):
    c = counts(rep) if out_exists else None
    return None if c is None else tuple(RANK.board_rank(c[0], c[1], c[2]))


# ----------------------------------------------------------------------------- menu
def build_menu(reports, kind):
    """The loop-back menu (kae.commander.menu) of the reports so far; {"menu": []} without it."""
    try:
        from kae.commander.menu import build_menu as bm
    except ImportError:
        return {"menu": [], "note": "kae.commander.menu not installed"}
    try:
        return bm(reports)
    except Exception as e:  # a report the menu cannot read must not stop the run
        return {"menu": [], "note": f"menu failed: {type(e).__name__}: {e}"}


def knob_sets(item, kind):
    """The "k=v" settings of a menu item's knob for `kind`, or None when it has none for it."""
    knob = item.get("knob") or {}
    piece = knob.get(kind) or []
    out = [piece[i + 1] for i in range(len(piece) - 1) if piece[i] == "--set"]
    flags = [p for i, p in enumerate(piece) if p.startswith("--") and p != "--set"
             and (i == 0 or piece[i - 1] != "--set")]
    return out, flags


def eligible(item, tried):
    knob = item.get("knob") or {}
    return (knob.get("kind") in ("set", "flag") and knob.get("effect") == "full"
            and (item.get("price") or {}).get("scorer", "allowed") == "allowed" and item.get("id") not in tried)


# ----------------------------------------------------------------------------- choosers
def choose_rules(menu, tried, kind):
    for it in menu.get("menu") or []:
        if eligible(it, tried):
            sets, _flags = knob_sets(it, kind)
            if sets:
                return dict(choose=it["id"], set=sets, reason=f"first eligible item (rank {it.get('rank')})")
    return dict(choose=None, set=[], reason="no eligible item")


def choose_replay(lines, i, used):
    for n, d in enumerate(lines):
        if n not in used and d.get("invocation") == i:
            used.add(n)
            return d
    for n, d in enumerate(lines):
        if n not in used and "invocation" not in d:
            used.add(n)
            return d
    return dict(choose=None, set=[], reason="replay file exhausted")


def choose_external(cmd, ask, timeout):
    try:
        p = subprocess.run(cmd, shell=True, input=json.dumps(ask, default=str), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "chooser timed out"
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None, f"chooser wrote nothing (exit {p.returncode})"
    try:
        d = json.loads(lines[-1])
    except ValueError:
        return None, "chooser answer is not JSON"
    if not isinstance(d, dict) or not isinstance(d.get("set", []), list):
        return None, "chooser answer is not {choose, set, reason}"
    return d, None


# ----------------------------------------------------------------------------- the loop
def _cpu():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime + r.ru_stime


def _replace(src, dst):
    tmp = Path(str(dst) + ".commander-tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _top(menu, n=5):
    return [dict(id=it.get("id"), rank=it.get("rank"), score=it.get("score"),
                 knob=(it.get("knob") or {}).get("kind")) for it in (menu.get("menu") or [])[:n]]


def run(a, command):
    inp, out = Path(a.input).resolve(), Path(a.output).resolve()
    logd = Path(a.log or out.parent / "commander").resolve()
    logd.mkdir(parents=True, exist_ok=True)
    reg = registries()
    per = float(a.time) / a.invocations
    replay = []
    if a.commander == "replay":
        replay = [json.loads(ln) for ln in Path(a.choices).read_text().splitlines() if ln.strip()]
    used, tried, active, history, reports = set(), set(), {}, [], []
    best = best_rank = None
    pending = dict(choose=None, set=[], reason="first invocation", chooser=a.commander, valid=True)
    decisions = (logd / "decisions.jsonl").open("w")
    t0 = time.monotonic()
    stop = "invocations"
    for i in range(a.invocations):
        seed = a.seed * 1000 + i
        d = logd / f"inv-{i}"
        d.mkdir(exist_ok=True)
        o, rp = d / out.name, d / "report.json"
        sets = sorted(active.values())
        c = command
        for k, v in (("@IN@", shlex.quote(str(inp))), ("@OUT@", shlex.quote(str(o))), ("@SEED@", str(seed)),
                     ("@TIME@", str(int(per))), ("@REPORT@", shlex.quote(str(rp))),
                     ("@SET@", " ".join(f"--set {shlex.quote(s)}" for s in sets))):
            c = c.replace(k, v)
        cpu0 = _cpu()
        with (d / "command.log").open("w") as lf:
            try:
                code = subprocess.run(c, shell=True, cwd=d, stdout=lf, stderr=subprocess.STDOUT,
                                      timeout=per * 1.5 + 60).returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
        cpu = round(_cpu() - cpu0, 2)
        try:
            rep = json.loads(rp.read_text())
        except (OSError, ValueError):
            rep = None
        rank = rank_of(rep, o.exists())
        if rep is not None:
            reports.append(rep)
        worse = rank is None or (best_rank is not None and rank > best_rank)
        if rank is not None and (best_rank is None or rank < best_rank):
            best, best_rank = i, rank
            _replace(o, out)
        if worse and pending.get("applied"):
            for s in pending["applied"]:                 # the new knob ranked worse than the best: drop it again
                active.pop(s.partition("=")[0], None)
        cn = counts(rep) if rep else None
        row = dict(board=inp.stem, invocation=i, seed=seed, knobs=sets, exit=code, rank=list(rank) if rank else None,
                   opens=cn[0] if cn else None, best=best, cpu_s=cpu, choice=pending.get("choose"),
                   chooser=pending.get("chooser"), reason=pending.get("reason"), valid=pending.get("valid", True))
        history.append(dict(invocation=i, seed=seed, knobs=sets, rank=row["rank"], opens=row["opens"],
                            choice=row["choice"]))
        clean = rank is not None and rank[1] == 0
        last = i == a.invocations - 1
        menu = {"menu": []} if (clean or last or a.commander == "null") else build_menu(reports, a.kind)
        row["menu_top5"] = _top(menu)
        if menu.get("note"):
            row["menu_note"] = menu["note"]
        decisions.write(json.dumps(row, default=str) + "\n")
        decisions.flush()
        if clean:
            stop = "clean"
            break
        if last:
            break
        pending = ask(a, i + 1, inp.stem, history, menu, reg, tried, replay, used)
        for s in pending.get("applied", []):
            active[s.partition("=")[0]] = s
        if pending.get("choose") is not None:
            tried.add(pending["choose"])
    decisions.close()
    summary = dict(board=inp.stem, commander=a.commander, kind=a.kind, invocations=len(history),
                   budget_s=float(a.time), per_invocation_s=per, best_invocation=best,
                   best_rank=list(best_rank) if best_rank else None, stop=stop,
                   wall_s=round(time.monotonic() - t0, 2), cpu_s=round(_cpu(), 2), output=out.exists() and best is not None)
    (logd / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def ask(a, i, board, history, menu, reg, tried, replay, used):
    """The chooser's decision for invocation i, validated: {choose, set, applied, reason, chooser, valid}."""
    ids = {it.get("id"): it for it in (menu.get("menu") or []) + (menu.get("ask") or [])}
    if a.commander == "null":
        return dict(choose=None, set=[], applied=[], reason="null: next seed", chooser="null", valid=True)
    if a.commander == "rules":
        d, why = choose_rules(menu, tried, a.kind), None
    elif a.commander == "replay":
        d, why = choose_replay(replay, i, used), None
    else:
        q = dict(schema=ASK_SCHEMA, board=board, invocation=i, kind=a.kind, history=history,
                 menu=menu.get("menu") or [], tried=sorted(tried), knobs=str(KNOBS_JSON))
        d, why = choose_external(a.chooser_cmd, q, a.chooser_timeout)
    if why is None and d.get("choose") is not None and d["choose"] not in ids:
        why = f"unknown item id {d['choose']!r}"
    if why is None and d.get("choose") is not None:
        kn = (ids[d["choose"]].get("knob") or {}).get("kind")
        if kn == "edit_input":
            return dict(choose=d["choose"], set=[], applied=[], chooser=a.commander, valid=True,
                        reason=f"skipped: edit_input knob needs a relations file (not built); {d.get('reason', '')}")
    applied = []
    if why is None:
        for kv in d.get("set") or []:
            norm, bad = check_set(kv, a.kind, reg)
            if bad:
                why = bad
                break
            applied.append(norm)
    if why is not None:
        return dict(choose=None, set=[], applied=[], chooser=a.commander, valid=False, reason=f"invalid: {why}")
    return dict(choose=d.get("choose"), set=d.get("set") or [], applied=applied, chooser=a.commander, valid=True,
                reason=str(d.get("reason", "")))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("commander.py: give the command after --", file=sys.stderr)
        return 2
    cut = argv.index("--")
    ap = argparse.ArgumentParser(prog="commander.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--time", type=float, required=True, help="total seconds; each invocation gets T/K")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--invocations", type=int, default=2, metavar="K")
    ap.add_argument("--commander", choices=("null", "rules", "external", "replay"), default="null")
    ap.add_argument("--chooser-cmd", help="external: the chooser command (JSON on stdin and stdout)")
    ap.add_argument("--chooser-timeout", type=float, default=CHOOSER_TIMEOUT_S)
    ap.add_argument("--choices", help="replay: JSONL of choices")
    ap.add_argument("--kind", choices=("route", "joint"), default="route")
    ap.add_argument("--log", help="log directory (default: OUT's directory/commander)")
    a = ap.parse_args(argv[:cut])
    command = " ".join(argv[cut + 1:])
    if a.invocations < 1 or not command:
        ap.error("need --invocations >= 1 and a command")
    if a.commander == "external" and not a.chooser_cmd:
        ap.error("--commander external needs --chooser-cmd")
    if a.commander == "replay" and not a.choices:
        ap.error("--commander replay needs --choices")
    s = run(a, command)
    print(json.dumps(s, default=str), flush=True)
    return 0 if s["output"] else 2


if __name__ == "__main__":
    sys.exit(main())
