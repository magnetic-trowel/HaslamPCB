# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, glob, os, collections, random, math, statistics as S
strat={l.split('\t')[0]:l.split('\t')[1] for l in open('boards.tsv')}
R=collections.defaultdict(dict)
for f in glob.glob('out/*.jsonl'):
    b=os.path.basename(f)[:-6]
    for l in open(f):
        d=json.loads(l); R[(b,d['seed'])][d['arm']]=d
arms=['control','control2','gated']
keys=[k for k,v in R.items() if all(a in v for a in arms)]
print('board-seeds complete',len(keys),'of',len(R))
same=sum(R[k]['control']['poses_sha']==R[k]['control2']['poses_sha'] for k in keys); print('control twin identical',same,'of',len(keys))
rng=random.Random(1)
def boot_diff(ks, arm, f):
    boards=sorted({b for b,_ in ks}); by=collections.defaultdict(list)
    for k in ks: by[k[0]].append(k)
    obs=sum(f(R[k][arm])-f(R[k]['control']) for k in ks)
    xs=[]
    for _ in range(4000):
        sm=[rng.choice(boards) for _ in boards]; xs.append(sum(f(R[k][arm])-f(R[k]['control']) for b in sm for k in by[b]))
    xs.sort(); return obs, xs[100], xs[3900]
legal=lambda d: 1 if d['legal'] else 0
pe_nonedge=lambda d: sum(v for k,v in (d.get('place_errors') or {}).items() if k!='copper_edge_clearance')
pe_edge=lambda d: (d.get('place_errors') or {}).get('copper_edge_clearance',0)
sh=lambda d: d.get('part_shorts',0) or 0
for st in ('failing','crowded','headers'):
    ks=[k for k in keys if strat[k[0]]==st]
    print(f'\n== {st}: {len({b for b,_ in ks})} boards, {len(ks)} board-seeds')
    for a in arms:
        L=[R[k][a] for k in ks]
        hp=[R[k][a]['hpwl']/R[k]['control']['hpwl'] for k in ks if R[k][a].get('hpwl') and R[k]['control'].get('hpwl')]
        line=f"  {a:8s} legal {sum(map(legal,L)):3d}/{len(L)}  pe(non-edge) {sum(map(pe_nonedge,L)):4d}  edge_clr {sum(map(pe_edge,L)):4d}  shorts {sum(map(sh,L)):4d}  hpwl gm {math.exp(S.mean(math.log(x) for x in hp)):.3f}"
        if a!='control':
            o,lo,hi=boot_diff(ks,a,legal); line+=f"  dLegal {o:+d} [{lo:+d},{hi:+d}]"
            o2,lo2,hi2=boot_diff(ks,a,pe_nonedge); line+=f"  dPE {o2:+d} [{lo2:+d},{hi2:+d}]"
            o3,lo3,hi3=boot_diff(ks,a,sh); line+=f"  dShort {o3:+d} [{lo3:+d},{hi3:+d}]"
        print(line)
    # flips per board for 'all' and 'headers'
    for a in ('gated',):
        fl=collections.Counter()
        for k in ks:
            d=legal(R[k][a])-legal(R[k]['control'])
            if d: fl[(k[0][:28],d)]+=1
        print('   flips',a,dict(fl))
