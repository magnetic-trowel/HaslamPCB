# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Board selection for fr-neck-gated-ab (`neck`) and fr-ripup-ab (`rip`): python3 select.py neck 30 / rip 20
import json,csv,os,random,collections,sys
S=os.environ.get('KAE_BOARD_TAGS', '/var/tmp/' + os.environ.get('USER', '') + '/board-tags') + '/structural'
U={}
for l in open(f'{S}/usability.jsonl'):
    r=json.loads(l); U[r['id']]=r
T={}
for l in open(f'{S}/tags.jsonl'):
    r=json.loads(l); T[r['id']]={k:v.get('value') for k,v in r['tags'].items()}
F={}
for l in open(f'{S}/features.jsonl'):
    r=json.loads(l); F[r['id']]=r
FB={r['board']:r for r in csv.DictReader(open(os.path.expanduser('~/kae-baselines/experiments/fr-baseline/results.csv'))) if r['method']=='fr-fork master'}
used=set()
for e in ['fr-settings-ab','fr-ladder-ab','e09-sweep']:
    used|=set(open(os.path.expanduser(f'~/kae-baselines/experiments/{e}/boards.txt')).read().split())
fp_vals=collections.Counter(t.get('fine_pitch') for t in T.values()); print('fine_pitch values',fp_vals.most_common(12))
pg_vals=collections.Counter(t.get('pad_gap') for t in T.values()); print('pad_gap values',pg_vals.most_common(12))
def pads(b):
    try: return int(FB[b]['pads'])
    except: return F.get(b,{}).get('n_pads',0)
def opens(b):
    try: return int(FB[b]['unconnected'])
    except: return None
def pool(cond):
    out=[]
    for b,u in U.items():
        if not u.get('usable_route_test') or b in used or b not in T: continue
        o=opens(b)
        if o is None or o<10: continue           # mechanism: the pinned-lineage fork leaves opens
        if not cond(b): continue
        out.append(b)
    return out
def one_per_family(bs,n,seed=2611):
    rng=random.Random(seed); bs=sorted(bs); rng.shuffle(bs); fam=set(); out=[]
    for b in bs:
        f=U[b].get('repo_family')
        if f in fam: continue
        fam.add(f); out.append(b)
        if len(out)>=n: break
    return out
def fine(b): return T[b].get('fine_pitch') == '<=0.4'
def gap_ok(b): return T[b].get('pad_gap') in ('<=0.10','<=0.15','<=0.20')
which=sys.argv[1]
if which=='neck':
    P=pool(lambda b: (pads(b)>=1000 or fine(b)) and gap_ok(b))
    sel=one_per_family(P,int(sys.argv[2]) if len(sys.argv)>2 else 30)
else:
    P=pool(lambda b: pads(b)>1000)
    e09=[b for b in open(os.path.expanduser('~/kae-baselines/experiments/e09-sweep/boards.txt')).read().split() if pads(b)>1000]
    print('e09 big',len(e09))
    sel=e09+one_per_family([b for b in P if U[b].get('repo_family') not in {U.get(x,{}).get('repo_family') for x in e09}],int(sys.argv[2]) if len(sys.argv)>2 else 20)
print('pool',len(P),'families',len({U[b].get('repo_family') for b in P}),'selected',len(sel))
for b in sel: print(f"{b[:55]:55s} pads {pads(b):5d} fr-open {opens(b)} fp {T[b].get('fine_pitch')} gap {T[b].get('pad_gap')} L{T[b].get('layer_count')} rd {T[b].get('route_demand')}")
open(f'{which}-boards.txt','w').write('\n'.join(sel)+'\n')
