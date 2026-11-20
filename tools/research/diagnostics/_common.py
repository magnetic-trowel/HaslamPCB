# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers of the stage-0 diagnostics (opens_variance, placement_rank, bus_inversions).

Owners, owner bootstrap, the read-only kaeres index, board parsing and rank statistics. No host paths: the results
store comes from `--results` or `$KAE_RESULTS`, everything else is an argument.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def store_path(arg: str | None) -> Path:
    """Results store root from `--results`, else `$KAE_RESULTS`."""
    p = arg or os.environ.get('KAE_RESULTS')
    if not p:
        sys.exit('results store not given: pass --results DIR or set KAE_RESULTS')
    return Path(p).expanduser()


def add_store_arg(ap) -> None:
    ap.add_argument('--results', help='results store root (default: $KAE_RESULTS)')


def open_index(store: Path) -> sqlite3.Connection:
    """The kaeres sqlite index, opened read-only."""
    return sqlite3.connect(f'file:{store}/index.sqlite?mode=ro', uri=True)


# ---- owners ---------------------------------------------------------------------------------------------------

def owner_of(board: str) -> str:
    """Owner of a board id: the id up to the first hyphen (the corpus prefixes ids with the repository owner)."""
    return board.split('-')[0]


def owner_from_repo(repo: str | None, default: str) -> str:
    """Owner from a repository URL (`https://host/owner/name`), lower case; `default` when there is none."""
    m = re.match(r'https?://[^/]+/([^/]+)', (repo or '').lower())
    return m.group(1) if m else default


def owners_from_results_csv(path) -> dict:
    """board -> owner from an experiment's results.csv `repo` column (second-last path element of the repo URL)."""
    out = {}
    for r in csv.DictReader(open(path)):
        repo = r.get('repo')
        out[r['board']] = repo.rstrip('/').split('/')[-2].lower() if repo else r['board']
    return out


def owners_from_usability(path) -> dict:
    """board -> owner from a tag-suite `usability.jsonl` (rows with `id` and `repo`)."""
    out = {}
    for line in open(path):
        d = json.loads(line)
        out[d['id']] = owner_from_repo(d.get('repo'), d['id'])
    return out


def owner_bootstrap(units: dict, stat, n: int = 2000, rng: random.Random | None = None, level: float = 0.95):
    """Percentile CI of `stat(list of items)` resampling owners with replacement.

    units: owner -> list of items. A resample concatenates the item lists of the drawn owners. Draws where `stat`
    returns None are dropped. Returns (lo, hi), or (None, None) when no draw gave a value.
    """
    rng = rng or random.Random(0)
    keys = sorted(units)
    out = []
    for _ in range(n):
        s = []
        for k in rng.choices(keys, k=len(keys)):
            s.extend(units[k])
        v = stat(s)
        if v is not None:
            out.append(v)
    out.sort()
    if not out:
        return None, None
    a = (1 - level) / 2
    return out[int(a * len(out))], out[int((1 - a) * len(out)) - 1]


def owner_groups(owners: list) -> list:
    """Index lists of items grouped by owner, owners in sorted order (for numpy bootstraps)."""
    g: dict = {}
    for i, o in enumerate(owners):
        g.setdefault(o, []).append(i)
    return [g[o] for o in sorted(g)]


# ---- rank statistics ------------------------------------------------------------------------------------------

def ranks(v):
    """Average ranks (0-based), ties share the mean rank."""
    o = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y) -> float:
    """Spearman rank correlation with average ranks for ties; nan when a side is constant."""
    a, b = ranks(list(x)), ranks(list(y))
    n = len(a)
    if n < 2:
        return float('nan')
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((u - ma) ** 2 for u in a))
    sb = math.sqrt(sum((u - mb) ** 2 for u in b))
    return sum((u - ma) * (v - mb) for u, v in zip(a, b)) / (sa * sb) if sa and sb else float('nan')


def auc(score, label) -> float:
    """Mann-Whitney AUC: probability that a positive scores above a negative (ties count half)."""
    r = ranks(list(score))
    p = sum(1 for y in label if y)
    q = len(label) - p
    if not p or not q:
        return float('nan')
    sr = sum(r[i] + 1 for i, y in enumerate(label) if y)
    return (sr - p * (p + 1) / 2) / (p * q)


def pairwise_accuracy(pairs) -> float | None:
    """pairs: (prediction difference, outcome difference). Share where the signs agree; a tied prediction counts 0.5.
    Pairs with a tied outcome are left out."""
    s = []
    for dp, dy in pairs:
        if dy == 0:
            continue
        t = math.copysign(1, dy) * (0 if dp == 0 else math.copysign(1, dp))
        s.append(1.0 if t > 0 else 0.5 if t == 0 else 0.0)
    return sum(s) / len(s) if s else None


def within_board_spearman(rows) -> float | None:
    """rows: (board, prediction, outcome). Mean over boards (>= 3 rows, both sides varying) of the Spearman rho."""
    by: dict = {}
    for b, p, y in rows:
        by.setdefault(b, []).append((p, y))
    v = [spearman([p for p, _ in L], [y for _, y in L]) for L in by.values() if len(L) >= 3]
    v = [x for x in v if x == x]
    return sum(v) / len(v) if v else None


# ---- board parsing --------------------------------------------------------------------------------------------

def kae_load(path):
    """Parse a .kicad_pcb with the repo's kae loader (rules off). kae/src of this checkout goes on sys.path."""
    src = str(REPO / 'kae' / 'src')
    if src not in sys.path:
        sys.path.insert(0, src)
    from kae.board.kicad_file import load
    return load(str(path), rules=False)


def footprints(board):
    return board.footprints.values() if isinstance(board.footprints, dict) else board.footprints


def parts_with_pads(path) -> dict:
    """ref -> dict(x, y, rot, side, locked, pads=[(number, net, x, y)]) for pads with a net (no NPTH)."""
    out = {}
    for fp in footprints(kae_load(path)):
        out[fp.ref] = dict(x=fp.x, y=fp.y, rot=fp.rot, side=fp.side, locked=bool(fp.locked),
                           pads=[(p.number, p.net, p.x, p.y) for p in fp.pads if p.kind != 'np_thru_hole' and p.net])
    return out


def write_out(out_dir, name: str, text: str) -> None:
    """Print `text`; with an out dir also write it to OUT/name."""
    print(text)
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / name).write_text(text + '\n')
