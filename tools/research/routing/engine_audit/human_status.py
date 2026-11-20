#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""human_status: can a board be finished at all? For each board of a list, the human layout's own score from the
results index: open connections, DRC errors and the commonest error types, beside footprints and layers. A router
benchmark that sums open connections over boards whose human layout is itself unfinished measures the boards.

  human_status.py --boards @ids.txt [--store DIR] [--max-errors N] [--finishable OUT.txt]

--store: the results store (default $KAE_RESULTS). --finishable writes the ids whose human layout has no open
connection (and at most --max-errors errors, default: any number). Boards without a human evaluation are listed as
unknown and are not written."""
import argparse
import json
import os
import sqlite3
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boards", required=True, help="@file with one board id per line, or a comma list")
    ap.add_argument("--store", default=os.environ.get("KAE_RESULTS", ""))
    ap.add_argument("--max-errors", type=int)
    ap.add_argument("--finishable")
    a = ap.parse_args(argv)
    if not a.store:
        ap.error("--store or $KAE_RESULTS")
    ids = ([l.strip() for l in open(a.boards[1:]) if l.strip() and not l.startswith("#")] if a.boards.startswith("@")
           else [x for x in a.boards.split(",") if x])
    c = sqlite3.connect(f"file:{a.store}/index.sqlite?mode=ro", uri=True)
    ok, counts = [], dict(complete=0, open=0, unknown=0)
    print(f"{'board':52s} {'fp':>5s} {'L':>2s} {'open':>5s} {'errors':>6s}  status / commonest error types")
    for b in ids:
        meta = c.execute("select footprints, layers from boards where id=?", (b,)).fetchone() or (None, None)
        q = c.execute("select e.unconnected, e.errors, e.clean, e.errors_by_type from evals e join runs r on r.board=e.board "
                      "and r.run=e.run join methods m on m.id=r.method_id where e.board=? and m.runner='reference' "
                      "and e.unconnected is not null order by e.rowid desc limit 1", (b,)).fetchone()
        if q is None:
            counts["unknown"] += 1
            print(f"{b[:52]:52s} {str(meta[0]):>5s} {str(meta[1]):>2s} {'-':>5s} {'-':>6s}  unknown: no human evaluation")
            continue
        opens, errors, clean, by = q
        types = sorted((json.loads(by) if by else {}).items(), key=lambda kv: -kv[1])[:3]
        status = "clean" if clean else ("complete" if not opens else "UNFINISHED")
        counts["open" if opens else "complete"] += 1
        if not opens and (a.max_errors is None or (errors or 0) <= a.max_errors):
            ok.append(b)
        print(f"{b[:52]:52s} {str(meta[0]):>5s} {str(meta[1]):>2s} {opens:5d} {errors or 0:6d}  {status} "
              + ", ".join(f"{k} {v}" for k, v in types))
    print(f"\n{len(ids)} boards: human layout complete {counts['complete']}, unfinished {counts['open']}, unknown {counts['unknown']}")
    if a.finishable:
        with open(a.finishable, "w") as f:
            f.write("".join(x + "\n" for x in ok))
        print(f"{len(ok)} finishable ids -> {a.finishable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
