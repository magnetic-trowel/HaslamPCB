#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rewrite `haslamres exp submit --dry-run`'s job file so every job runs both arms of the same seeds, side by side.

haslamres splits a board's runs into chunks by method cost, which for two equally priced arms puts all control runs in
one job and all xing runs in another. Here each board gets one job per pair of attempts, running
control@a, xing@a, xing@a+1, control@a+1 (the arm that goes first alternates). The commands are haslamres's own
(`haslamres.py job --experiment E --board B --method ID@N ...`); resources come from haslamres's estimate() for the four
runs, with the timeout doubled (the original experiment lost 8 large-board jobs at 1x).

  interleave.py JOBS.jsonl > JOBS-interleaved.jsonl
"""
import importlib.util, json, re, sys
from pathlib import Path

src = Path(sys.argv[1])
jobs = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
spec = importlib.util.spec_from_file_location("haslamres", Path(__file__).resolve().parents[2] / "haslamres.py")
K = importlib.util.module_from_spec(spec); spec.loader.exec_module(K)
exp = re.search(r"--experiment (\S+)", jobs[0]["cmd"]).group(1)
e = K.load_exp(exp)
ctl, xing = (K.find_method(m["id"]) for m in e["methods"])
rows = K.corpus_rows()
seen = []
for j in jobs:
    b = re.search(r"--board (\S+)", j["cmd"]).group(1)
    if b not in seen:
        seen.append(b)
base = {b: next(j for j in jobs if f"--board {b}" in j["cmd"]) for b in seen}
for b in seen:
    need = set(K.missing(e, b))
    head = base[b]["cmd"].split(" --method")[0]
    for i, a in enumerate(range(0, e["attempts"], 2)):
        order = [(ctl, a), (xing, a), (xing, a + 1), (ctl, a + 1)]
        order = [(m, n) for m, n in order if n < e["attempts"] and (m["id"], n) in need]
        if not order:
            continue
        est = K.estimate(rows[b], [m for m, _ in order])
        t = int(est["timeout"].rstrip("s")) * 2
        print(json.dumps(dict(cmd=head + "".join(f" --method {m['id']}@{n}" for m, n in order),
                              name=f"{exp}:{b}:s{a + 3}-{a + 4}", cpus=base[b]["cpus"], mem=est["mem"],
                              disk=est["disk"], timeout=f"{t}s", size_mb=est["size_mb"])))
