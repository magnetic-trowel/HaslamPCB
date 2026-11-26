# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where an evaluation used a prior although its operating facts state the value: every ledger parameter whose
source is `prior`, and every observer reference whose src_class is `prior`, for which the board's operating facts
(`.operating.json`) hold a value for that subject and parameter. Such a gap is a fact the evaluator never read (a
switch rating that stayed in a hard term, a parameter under another name).

    python facts_vs_prior.py --facts DIR [--facts DIR ...] EVAL.ev.json ...

The facts of board <id> are <DIR>/<id>.operating.json (the first DIR that has it). Prints one line per gap and a
count per (subject kind, parameter); exits 0."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def _norm(name):
    """A parameter's name without its unit suffix, lower case: 'V_max_V' -> 'v_max', 'theta_jb_C_W' -> 'theta_jb'."""
    n = name.lower()
    n = re.sub(r'_(v|a|hz|s|f|h|w|ohm|c_w|k_w|mohm|nh|pf|uf)$', '', n)
    return {"switch_v_max": "v_max", "i_switch": "i"}.get(n, n)


def _facts_for(facts, subject):
    """The facts dict that states the ledger subject's values: cells.<sid> for a cell, parts.<ref> for a part's
    heat or DC parameters, nets.<net> for a rail's."""
    kind, _, rest = subject.partition(":")
    if subject.startswith("cell:"):
        return (facts.get("cells") or {}).get(subject) or {}
    ref = rest.split("@", 1)[0]
    if kind in ("heat", "dc", "part"):
        return (facts.get("parts") or {}).get(ref) or (facts.get("nets") or {}).get(ref) or {}
    return (facts.get("parts") or {}).get(subject) or (facts.get("nets") or {}).get(subject) or {}


def _rated_terms(intent):
    """{cell id: V} of the intent's switch-rating terms (intent_from_spec writes a spec's switch_V_max_V as a hard
    overshoot.peak term whose source names the rating)."""
    out = {}
    for t in (intent or {}).get("terms") or []:
        obs = ((t.get("where") or {}).get("observer") or "")
        m = re.search(r"switch rating ([0-9.]+) V", t.get("source") or "")
        if t.get("obs") == "overshoot.peak" and obs.startswith("overshoot:") and m:
            out[obs.split(":", 1)[1]] = float(m.group(1))
    return out


def gaps(ev, facts, intent=None):
    out = []
    rated = _rated_terms(intent)
    for p in ev.get("ledger") or []:
        if p.get("source") != "prior":
            continue
        f = _facts_for(facts, p["subject"])
        hit = [k for k in f if _norm(k) == _norm(p["name"]) and f[k] not in (None, [], "")]
        if hit:
            out.append(("ledger", p["subject"], p["name"], hit[0], f[hit[0]], p.get("basis", "")[:80]))
    for o in ev.get("observations") or []:
        ref = o.get("reference") or {}
        if ref.get("src_class") != "prior" or o.get("id") != "overshoot.peak":
            continue
        sid = (o.get("scope") or {}).get("source", "").replace("cell:cell:", "cell:", 1)
        f = (facts.get("cells") or {}).get(sid) or {}
        hit = [k for k in f if _norm(k) == "v_max"]
        if hit:
            out.append(("reference", sid, "overshoot bound", hit[0], f[hit[0]], ref.get("basis", "")[:80]))
        elif sid in rated:
            out.append(("reference", sid, "overshoot bound", "intent term switch rating", rated[sid],
                        ref.get("basis", "")[:80]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--facts", action="append", required=True, help="a folder of <id>.operating.json")
    ap.add_argument("evals", nargs="+")
    a = ap.parse_args(argv)
    count, boards, nofacts = Counter(), 0, 0
    for e in a.evals:
        bid = Path(e).name.split(".ev.json")[0]
        fp = next((Path(d) / f"{bid}.operating.json" for d in a.facts if (Path(d) / f"{bid}.operating.json").exists()), None)
        if fp is None:
            nofacts += 1
            continue
        try:
            ev, facts = json.loads(Path(e).read_text()), json.loads(fp.read_text())
        except (OSError, ValueError) as x:
            print(f"{bid}: unreadable ({type(x).__name__})")
            continue
        boards += 1
        ip = fp.with_name(f"{bid}.intent.json")
        intent = json.loads(ip.read_text()) if ip.exists() else None
        for where, subj, name, key, val, basis in gaps(ev, facts, intent):
            print(f"{bid}\t{where}\t{subj}\t{name}\tfacts {key}={val}\t{basis}")
            count[(subj.split(":")[0], name)] += 1
    print(f"# {boards} evaluations with facts, {nofacts} without; gaps by (subject kind, parameter):")
    for k, n in count.most_common():
        print(f"#   {k[0]} {k[1]}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
