# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Freerouting settings each stage of a layout.sh run actually used, from the files the run leaves behind.

    layout_settings.py OUTDIR [--json OUT] [--keys k1,k2]

A recipe variant (HASLAM_LAYOUT_SET="bridge.neckdown=1") used to be checked by grepping leftovers (obd-solar
FRICTION.md #72). Freerouting writes its whole settings snapshot into each run's result file; the bridge keeps a copy
wherever HASLAM_FR_RAW_DIR points (haslam.route.freerouting._keep_raw). restart.py points it at each attempt and packs
the copies into <restarts>/fr-telemetry.tar; layout.sh points it at OUTDIR/work/fr-raw for every other command
(the open-alt phase, resumes). Nothing here changes how the board is routed.

Reads every fr-telemetry.tar under OUTDIR/work and OUTDIR/work/fr-raw/*.result.json(.gz), plus restart.py's
summary.json (the phase commands) and OUTDIR/eval/layout_set.json (what layout.sh passed). Writes OUTDIR/eval/
settings.json (unless --json) and prints one line per distinct group of settings: where the runs were, how many, the
watched keys (--keys, default WATCH) and every key whose value differs between the groups.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import tarfile
from pathlib import Path

WATCH = ("autorouter.start_necked", "automatic_neckdown", "neck_width_um", "min_trace_width_um", "fanout.enabled",
         "autorouter.max_passes", "optimizer.enabled", "optimizer.max_passes", "job_timeout",
         "autorouter.ignore_net_classes")
BUDGET = ("job_timeout",)       # each run's own time budget: listed per group, not a reason to split one


def flatten(d, pre=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{pre}{k}."))
        else:
            out[f"{pre}{k}"] = v
    return out


def _settings(raw: bytes):
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    s = d.get("settings_snapshot")
    if not isinstance(s, dict):
        return None
    s = {k: v for k, v in flatten(s).items() if not k.endswith(("result_json", "input_file", "output_file"))}
    return dict(generated_at=d.get("generated_at"), app_version=d.get("app_version"), settings=s)


def runs(outdir):
    """Every Freerouting run with a kept result file: {where, attempt, generated_at, app_version, settings}."""
    work = Path(outdir) / "work"
    found = []
    for tar in sorted(work.rglob("fr-telemetry.tar")):
        where = str(tar.parent.relative_to(work))
        with tarfile.open(tar) as t:
            for m in t.getmembers():
                if not m.name.endswith(".result.json.gz"):
                    continue
                r = _settings(gzip.decompress(t.extractfile(m).read()))
                if r:
                    found.append(dict(where=where, attempt=m.name.split("/")[0], **r))
    for p in sorted((work / "fr-raw").glob("*.result.json*")) if (work / "fr-raw").is_dir() else []:
        raw = gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
        r = _settings(raw)
        if r:
            found.append(dict(where="fr-raw (outside restart.py's attempts: open-alt phase, resume)",
                              attempt=p.name.split(".")[0], **r))
    return sorted(found, key=lambda r: (r["generated_at"] or "", r["where"]))


def groups(found, keys=WATCH):
    """Runs grouped by identical settings; `differs` the keys whose value is not the same in every run."""
    allk = sorted({k for r in found for k in r["settings"]})
    differs = [k for k in allk if len({json.dumps(r["settings"].get(k)) for r in found}) > 1]
    show = list(dict.fromkeys([k for k in keys if any(k in r["settings"] for r in found)] + differs))
    out = {}
    for r in found:
        sig = json.dumps({k: r["settings"].get(k) for k in allk if k not in BUDGET}, sort_keys=True)
        g = out.setdefault(sig, dict(runs=0, where={}, settings={k: r["settings"].get(k) for k in show
                                                                 if k not in BUDGET}))
        g["runs"] += 1
        g["where"].setdefault(r["where"], []).append(r["attempt"])
        for k in BUDGET:
            if k in show and r["settings"].get(k) not in g["settings"].setdefault(k, []):
                g["settings"][k].append(r["settings"].get(k))
    return list(out.values()), [k for k in differs if k not in BUDGET]


def summary(outdir, keys=WATCH):
    outdir = Path(outdir)
    found = runs(outdir)
    gs, differs = groups(found, keys)
    rep = dict(outdir=str(outdir), freerouting_runs=len(found), groups=gs, differs=differs)
    ls = outdir / "eval" / "layout_set.json"
    if ls.exists():
        rep["layout_set"] = json.loads(ls.read_text())
    phases = []
    for s in sorted((outdir / "work").rglob("summary.json")):
        try:
            d = json.loads(s.read_text())
        except ValueError:
            continue
        for ph in d.get("phases") or []:
            phases.append(dict(where=str(s.parent.relative_to(outdir / "work")), k=ph.get("k"),
                               attempts=ph.get("attempts"), command=ph.get("command")))
    rep["phases"] = phases
    return rep


def lines(rep):
    out = [f"{rep['freerouting_runs']} Freerouting runs with a kept result file, {len(rep['groups'])} distinct "
           f"settings" + (f"; keys that differ: {', '.join(rep['differs'])}" if rep["differs"] else "")]
    if rep.get("layout_set"):
        out.append("layout.sh options: " + json.dumps(rep["layout_set"]))
    for g in rep["groups"]:
        where = "; ".join(f"{w}: {','.join(sorted(a))}" for w, a in g["where"].items())
        out.append(f"{g['runs']} run(s) [{where}]: " + " ".join(f"{k}={json.dumps(v)}" for k, v in g["settings"].items()))
    if not rep["freerouting_runs"]:
        out.append("no result files kept (a run older than this script, or every telemetry part dropped)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("outdir")
    ap.add_argument("--json")
    ap.add_argument("--keys", help="comma list of settings keys to show (flattened, e.g. autorouter.start_necked)")
    a = ap.parse_args(argv)
    rep = summary(a.outdir, tuple(a.keys.split(",")) if a.keys else WATCH)
    out = Path(a.json) if a.json else Path(a.outdir) / "eval" / "settings.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1))
    print("\n".join(lines(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
