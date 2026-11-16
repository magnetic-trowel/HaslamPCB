#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze the wave-1 maps of place-history-b-maps (PLAN.md): for every board, the maps run's phist.tar
goes to $KAE_HOME/phist-b-maps/<input key>/ (the key, the input's sha256 to 16 hex, is in the run's
adapter.log), read-only, and a table of the maps (attempts, peak, coverage, sha256) is printed.
An existing frozen directory is never changed: a different map there is an error.

    freeze.py [--results ~/kae-baselines] [--dry]
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path

import numpy as np

here = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("KAE_RESULTS", str(Path.home() / "kae-baselines")))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    res = Path(a.results)
    exp = json.loads((res / "experiments" / "place-history-b-maps" / "experiment.json").read_text())
    mid = exp["methods"][0]["id"]
    root = Path(os.environ.get("KAE_HOME", Path.home() / ".cache" / "kaebench")) / "phist-b-maps"
    rows, bad = [], 0
    for bid in (here / "boards.txt").read_text().split():
        runs = [r for r in (res / "boards" / bid / "runs").glob(f"*.{mid[:8]}.a0") if (r / "run.json").exists()]
        if not runs:
            print(f"{bid}: no maps run yet")
            bad += 1
            continue
        r = runs[0]
        log = gzip.open(r / "adapter.log.gz", "rt", errors="replace").read()
        m = re.findall(r"phist-b: input ([0-9a-f]{16})", log)
        if not m or not (r / "phist.tar").exists():
            print(f"{bid}: {r.name} has no key or no phist.tar")
            bad += 1
            continue
        key, maps = m[-1], {}
        with tarfile.open(r / "phist.tar") as t:
            for mem in t.getmembers():
                if mem.isfile() and re.fullmatch(r"h-\d+-\d+\.npz", Path(mem.name).name):
                    maps[Path(mem.name).name] = t.extractfile(mem).read()
        hs = [np.load(io.BytesIO(b))["h"] for b in maps.values()]
        h = np.mean(hs, axis=0) if hs else np.zeros(1)
        on = h[h > 0]
        d = root / key
        if d.exists():
            have = {p.name: p.read_bytes() for p in d.glob("h-*.npz")}
            if have != maps:
                print(f"{bid}: {d} exists with other maps")
                bad += 1
                continue
        elif not a.dry:
            d.mkdir(parents=True)
            for n, b in maps.items():
                (d / n).write_bytes(b)
                (d / n).chmod(0o444)
            d.chmod(0o555)
        rows.append(dict(board=bid, key=key, files=len(maps), peak=round(float(h.max()), 3),
                         coverage=round(on.size / h.size, 4), bins=int(h.size), mean_on=round(float(on.mean()), 3) if on.size else 0,
                         sha=hashlib.sha256(b"".join(maps[n] for n in sorted(maps))).hexdigest()[:16]))
    print(json.dumps(rows, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
