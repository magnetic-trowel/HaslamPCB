# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Board selection for margin-gate (seeded, one board per repo); writes dense-hi/dense-lo/sparse lists.
#   select.py BOARD_TAGS_DIR   (the board-tag extractor's output: suites/, structural/)
import json, os, random, collections, sys
T = sys.argv[1]
S = T + '/suites/'
U = {}
for l in open(T + '/structural/usability.jsonl'):
    r = json.loads(l); U[r['id']] = r
F = {}
for l in open(T + '/structural/features.jsonl'):
    r = json.loads(l); F[r['id']] = r
used = set(open(os.path.expanduser('~/kae-baselines/experiments/margin-ab/boards.txt')).read().split())
def suite(n): return [x.strip() for x in open(S + n) if x.strip()]
def ok(b): return U.get(b, {}).get('usable_route_test') and U[b].get('prepared_task') and b not in used and b in F
def one_per_repo(ids, n, seed):
    rnd = random.Random(seed); ids = sorted(set(ids)); rnd.shuffle(ids)
    seen, out = set(), []
    for b in ids:
        r = U[b]['repo']
        if r in seen: continue
        seen.add(r); out.append(b)
        if len(out) == n: break
    return out
dense = [b for b in suite('pad_density.dense.txt') + suite('pad_density.very_dense.txt') if ok(b)]
hi = one_per_repo([b for b in dense if F[b]['pads_per_cm2_per_layer'] >= 4.0], 90, 1)
lo = one_per_repo([b for b in dense if F[b]['pads_per_cm2_per_layer'] < 4.0 and U[b]['repo'] not in {U[x]['repo'] for x in hi}], 40, 2)
taken = {U[x]['repo'] for x in hi + lo}
sp = one_per_repo([b for b in suite('pad_density.sparse.txt') if ok(b) and U[b]['repo'] not in taken and F[b]['n_footprints'] >= 15], 20, 3)
for name, l in (('dense-hi', hi), ('dense-lo', lo), ('sparse', sp)):
    open(name + '.boards.txt', 'w').write('\n'.join(l) + '\n')
    c = collections.Counter(F[b]['cu_layers'] for b in l)
    pads = sorted(F[b]['n_pads'] for b in l)
    print(name, len(l), dict(c), 'pads median', pads[len(pads)//2], 'max', pads[-1])
