# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""One table of a layout A/B: arms x seeds -> completion, DRC and the intent's physics (brief-to-board G13).

    python compare_ab.py RUNDIR [--md OUT.md] [--json OUT.json]

Reads RUNDIR/<arm>/s<seed>/eval/{drc.json,status.json} as eval_ab.sh writes them (KiCad DRC of the re-opened
board; kae.intent status under the run's one intent file). Per run: unconnected items, DRC errors by type, the
intent's tiers (hard violations, limit and cost in mW_eq) and every term's value; per arm: the mean and range
over its seeds. A run without an eval is listed as missing, never dropped.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def one(d):
    r = dict(run=f"{d.parent.name}/{d.name}")
    ev = d / "eval"
    try:
        drc = json.loads((ev / "drc.json").read_text())
        errs = [v for v in drc.get("violations") or [] if v.get("severity") == "error"]
        by = {}
        for v in errs:
            by[v["type"]] = by.get(v["type"], 0) + 1
        r.update(unconnected=len(drc.get("unconnected_items") or []), errors=len(errs), by_type=by,
                 parity=len(drc.get("schematic_parity") or []))
    except (OSError, ValueError):
        r["missing"] = "drc"
    try:
        st = json.loads((ev / "status.json").read_text())
        r["complete"] = st.get("complete")
        r["tiers"] = st.get("tiers")
        r["terms"] = {t["id"]: dict(value=t.get("value"), met=t.get("met"), contribution=t.get("contribution"),
                                    dominant=t.get("dominant")) for t in st.get("terms") or []}
        if st.get("why_incomplete"):
            r["why_incomplete"] = st["why_incomplete"]
    except (OSError, ValueError):
        r.setdefault("missing", "status")
    return r


def _num(s):
    try:
        return float(str(s).split()[0])
    except (ValueError, IndexError):
        return None


def summary(rows):
    arms = {}
    for r in rows:
        arms.setdefault(r["run"].split("/")[0], []).append(r)
    out = {}
    for arm, rs in sorted(arms.items()):
        ok = [r for r in rs if "missing" not in r]
        agg = dict(runs=len(rs), scored=len(ok))
        for k in ("unconnected", "errors"):
            xs = [r[k] for r in ok if k in r]
            if xs:
                agg[k] = dict(mean=round(statistics.mean(xs), 2), min=min(xs), max=max(xs))
        for k in ("hard", "limit", "cost"):
            # an incomplete status prices none of the terms its missing sources feed: its tiers are not a score
            xs = [r["tiers"][k] for r in ok if r.get("tiers") and r.get("complete") is not False]
            if xs:
                agg[k] = dict(mean=round(statistics.mean(xs), 3), min=min(xs), max=max(xs))
        terms = sorted({t for r in ok for t in (r.get("terms") or {})})
        for t in terms:
            xs = [_num(r["terms"][t]["value"]) for r in ok if t in (r.get("terms") or {})]
            xs = [x for x in xs if x is not None]
            met = [r["terms"][t]["met"] for r in ok if t in (r.get("terms") or {}) and r["terms"][t]["met"] is not None]
            unit = next((str(r["terms"][t]["value"]).split()[1] for r in ok if t in (r.get("terms") or {})
                         and len(str(r["terms"][t]["value"]).split()) > 1), "")
            if xs:
                agg.setdefault("term", {})[t] = dict(mean=round(statistics.mean(xs), 4), min=min(xs), max=max(xs),
                                                     unit=unit, met=f"{sum(met)}/{len(met)}" if met else "")
        out[arm] = agg
    return out


def markdown(rows, summ):
    lines = ["| run | unconnected | DRC errors | hard | limit | cost | unmet terms |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if "missing" in r:
            lines.append(f"| {r['run']} | missing {r['missing']} | | | | | |")
            continue
        t = r.get("tiers") or {}
        if r.get("complete") is False:
            t = {k: "incomplete" for k in ("hard", "limit", "cost")}
        unmet = [k for k, v in (r.get("terms") or {}).items() if v.get("met") is False]
        lines.append(f"| {r['run']} | {r.get('unconnected')} | {r.get('errors')} {r.get('by_type') or ''} | "
                     f"{t.get('hard', '')} | {t.get('limit', '')} | {t.get('cost', '')} | {', '.join(unmet)} |")
    lines += ["", "| arm | scored | unconnected (mean, range) | limit | cost | term means |", "|---|---|---|---|---|---|"]
    for arm, a in summ.items():
        u = a.get("unconnected") or {}
        terms = "; ".join(f"{k} {v['mean']:g} {v['unit']} (met {v['met']})" for k, v in (a.get("term") or {}).items())
        lines.append(f"| {arm} | {a['scored']}/{a['runs']} | {u.get('mean', '')} [{u.get('min', '')}, {u.get('max', '')}] | "
                     f"{(a.get('limit') or {}).get('mean', '')} | {(a.get('cost') or {}).get('mean', '')} | {terms} |")
    why = [f"- {r['run']}: {r['why_incomplete']}" for r in rows if r.get("why_incomplete")]
    if why:
        lines += ["", "Incomplete evaluations (tiers left out of the arm means):"] + why
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    runs = sorted(p for p in Path(a.run).glob("*/s*") if p.is_dir())
    rows = [one(d) for d in runs]
    summ = summary(rows)
    md = markdown(rows, summ)
    print(md)
    if a.md:
        Path(a.md).write_text(md + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(runs=rows, arms=summ), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
