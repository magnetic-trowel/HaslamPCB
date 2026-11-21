# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, math, random, statistics as S, collections
R=json.load(open('./runs.json'))
by=collections.defaultdict(dict)
for r in R:
    if r.get('unc') is None or r['status']!='ok': continue
    by[r['board']][(r['arm'],r['seed'])]=r
boards=[b for b,v in by.items() if all((a,s) in v for a in ('control','chan3') for s in range(3))]
print('boards complete',len(boards),'of',len(by))
L=lambda x: math.log1p(x)
rng=random.Random(1)
def boot(vals,f=S.mean,n=10000):
    xs=[f([rng.choice(vals) for _ in vals]) for _ in range(n)]; xs.sort(); return xs[int(.025*n)],xs[int(.975*n)]
def signflip(d,n=20000):
    o=abs(S.mean(d)); return sum(abs(S.mean([x*rng.choice((-1,1)) for x in d]))>=o-1e-12 for _ in range(n))/n
# board mean delta
D=[S.mean(L(by[b][('chan3',s)]['unc']) for s in range(3))-S.mean(L(by[b][('control',s)]['unc']) for s in range(3)) for b in boards]
m=S.mean(D); lo,hi=boot(D)
print(f'board-mean dlog1p {m:+.4f} = {math.expm1(m)*100:+.1f}% CI [{math.expm1(lo)*100:+.1f},{math.expm1(hi)*100:+.1f}] p={signflip(D):.3f} lower/higher {sum(d<0 for d in D)}/{sum(d>0 for d in D)} sd {S.stdev(D):.3f} MDE80 {math.expm1(2.8*S.stdev(D)/math.sqrt(len(D)))*100:.1f}%')
# per-attempt paired by seed
P=[L(by[b][('chan3',s)]['unc'])-L(by[b][('control',s)]['unc']) for b in boards for s in range(3)]
# cluster bootstrap by board
pb={b:[L(by[b][('chan3',s)]['unc'])-L(by[b][('control',s)]['unc']) for s in range(3)] for b in boards}
xs=[]
for _ in range(10000):
    smp=[rng.choice(boards) for _ in boards]; xs.append(S.mean([x for b in smp for x in pb[b]]))
xs.sort(); pm=S.mean(P)
# seed SD within arm
sd=S.mean([S.pstdev([L(by[b][(a,s)]['unc']) for s in range(3)])**2*1.5 for b in boards for a in ('control','chan3')])**.5
print(f'per-attempt paired dlog1p {pm:+.4f} = {math.expm1(pm)*100:+.1f}% CI [{math.expm1(xs[250])*100:+.1f},{math.expm1(xs[9750])*100:+.1f}] lower/higher {sum(d<0 for d in P)}/{sum(d>0 for d in P)}; within-arm seed SD {sd:.3f}')
oc=sum(by[b][('control',s)]['unc'] for b in boards for s in range(3)); oa=sum(by[b][('chan3',s)]['unc'] for b in boards for s in range(3))
rs=[]
for _ in range(5000):
    smp=[rng.choice(boards) for _ in boards]
    c=sum(by[b][('control',s)]['unc'] for b in smp for s in range(3)); a=sum(by[b][('chan3',s)]['unc'] for b in smp for s in range(3)); rs.append(a/max(c,1))
rs.sort(); print(f'opens sum ctl {oc} chan3 {oa} ratio {oa/oc:.3f} CI [{rs[125]:.3f},{rs[4875]:.3f}]')
# near-miss: boards where control mean <=5 opens
nm=[b for b in boards if S.mean(by[b][('control',s)]['unc'] for s in range(3))<=5]
for name,a in (('control','control'),('chan3','chan3')):
    print(name,'clean runs',sum(by[b][(a,s)]['clean'] for b in boards for s in range(3)),'legal runs',sum(bool(by[b][(a,s)]['legal']) for b in boards for s in range(3)),
          'errors',sum(by[b][(a,s)]['errors'] for b in boards for s in range(3)),'wl',round(sum(by[b][(a,s)]['wl'] or 0 for b in boards for s in range(3))),
          'completion',round(S.mean(by[b][(a,s)]['completion'] for b in boards for s in range(3)),4),'cpu_h',round(sum(by[b][(a,s)]['cpu'] or 0 for b in boards for s in range(3))/3600,1),
          'near-miss boards opens', sum(by[b][(a,s)]['unc'] for b in nm for s in range(3)))
print('near-miss boards (control mean<=5):',len(nm))
# wl per routed connection
def wpc(a): return sum((by[b][(a,s)]['wl'] or 0) for b in boards for s in range(3))/sum(by[b][(a,s)]['start']-by[b][(a,s)]['unc'] for b in boards for s in range(3))
print('wl per routed conn ctl %.3f chan3 %.3f ratio %.3f'%(wpc('control'),wpc('chan3'),wpc('chan3')/wpc('control')))
# DRC by type
T=collections.Counter(); U=collections.Counter()
for b in boards:
    for s in range(3):
        T.update(by[b][('control',s)]['etypes'] or {}); U.update(by[b][('chan3',s)]['etypes'] or {})
for k in sorted(set(T)|set(U), key=lambda k:-(T[k]+U[k])):
    print(f'  {k:28s} {T[k]:6d} {U[k]:6d} {U[k]/max(T[k],1):.2f}')
# mechanism
fp=lambda a:[by[b][(a,s)].get('chan',{}).get('final_pairs') for b in boards for s in range(3)]
c,a=fp('control'),fp('chan3')
ok=[(x,y) for x,y in zip(c,a) if x is not None and y is not None]
print('final_pairs runs',len(ok),'sum ctl',sum(x for x,_ in ok),'chan3',sum(y for _,y in ok),'chan3 lower in',sum(y<x for x,y in ok),'higher',sum(y>x for x,y in ok))
# per-board table
rows=[]
for b,d in zip(boards,D):
    rows.append((d,b,[by[b][('control',s)]['unc'] for s in range(3)],[by[b][('chan3',s)]['unc'] for s in range(3)]))
rows.sort()
json.dump(rows,open('./perboard.json','w'))
for r in rows[:8]+[None]+rows[-8:]:
    print(r if r is None else f'{r[0]:+.2f} {r[1][:55]:55s} {r[2]} -> {r[3]}')
