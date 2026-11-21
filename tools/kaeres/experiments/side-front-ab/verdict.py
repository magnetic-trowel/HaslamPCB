#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""side-front-ab verdict, step 2: the pre-registered exclusions and paired comparisons (PLAN.md).

Usage: verdict.py [--all]   (reads data.json from extract_runs.py in the current directory;
--all keeps the boards the 2026-11-13 addendum excludes, for the transparency view)
"""
import json,random,math,collections,sys
d=json.load(open('data.json'))
t=json.load(open(os.path.expanduser('~/kae-baselines/experiments/side-front-ab/TRIM-2026-11-20.json')))
parked=set(t['parked_boards'])
excl={}
keep=[]
for r in d:
    b=r['board']
    if not all(a in r for a in 'CPR'):
        excl[b]='parked (trim)' if b in parked else ('no runs' if not any(a in r for a in 'CPR') else 'incomplete'); continue
    if b in parked: excl[b]='parked (trim)'; continue
    if all(r[a]['status']=='no_output' for a in 'CPR'): excl[b]='no_output in every arm'; continue
    sd=r['P']['side'] or r['R']['side']
    if sd['board_area_mm2']<=0 or sd['front_fill_before']>1: excl[b]=f"area {sd['board_area_mm2']} fill {sd['front_fill_before']}"; continue
    if any(r[a]['status']=='ok' and not r[a]['scored'] for a in 'CPR'): excl[b]='scored by another DRC evaluator (C,R rerun 2026-11-20)'; continue
    keep.append(r)
INCL_ALL = '--all' in sys.argv
if INCL_ALL:
    keep=[r for r in d if all(a in r for a in 'CPR') and r['board'] not in parked and not any(r[a]['status']=='ok' and not r[a]['scored'] for a in 'CPR')]
print('kept',len(keep),'excluded',collections.Counter(v.split(' ')[0] for v in excl.values()))
for b,v in sorted(excl.items()):
    if v!='no runs': print('  ',b,v)
def ok(x): return x['status']=='ok' and x['scored']
def clean(x): return ok(x) and bool(x['clean'])
def legal(x): return ok(x) and bool(x['legal'])
random.seed(1)
def boot(vals,f,n=4000):
    s=[];N=len(vals)
    for _ in range(n):
        smp=[vals[random.randrange(N)] for _ in range(N)]
        s.append(f(smp))
    s.sort();return s[int(.025*n)],s[int(.975*n)]
def mcnemar(b,c):
    n=b+c
    if n==0: return 1.0
    k=min(b,c); p=sum(math.comb(n,i) for i in range(k+1))/2**n
    return min(1,2*p)
def signflip(diffs,n=20000):
    obs=abs(sum(diffs)); cnt=0
    for _ in range(n):
        if abs(sum(x if random.random()<.5 else -x for x in diffs))>=obs-1e-12: cnt+=1
    return cnt/n
def compare(rows,A,B,label):
    o=[]
    nb=len(rows)
    cA=sum(clean(r[A]) for r in rows); cB=sum(clean(r[B]) for r in rows)
    up=sum(clean(r[B]) and not clean(r[A]) for r in rows); dn=sum(clean(r[A]) and not clean(r[B]) for r in rows)
    lA=sum(legal(r[A]) for r in rows); lB=sum(legal(r[B]) for r in rows)
    lup=sum(legal(r[B]) and not legal(r[A]) for r in rows); ldn=sum(legal(r[A]) and not legal(r[B]) for r in rows)
    dc=[(clean(r[B])-clean(r[A])) for r in rows]; dl=[(legal(r[B])-legal(r[A])) for r in rows]
    ci_c=boot(dc,lambda s:sum(s)/len(s)); ci_l=boot(dl,lambda s:sum(s)/len(s))
    both=[r for r in rows if ok(r[A]) and ok(r[B])]
    pr=[(r[A]['unc'],r[B]['unc']) for r in both]
    sa=sum(a for a,b in pr); sb=sum(b for a,b in pr)
    ci_o=boot(pr,lambda s:sum(b for a,b in s)/max(1,sum(a for a,b in s)))
    p_o=signflip([b-a for a,b in pr])
    ea=sum(r[A]['errors'] for r in both); eb=sum(r[B]['errors'] for r in both)
    ci_e=boot([(r[A]['errors'],r[B]['errors']) for r in both],lambda s:sum(b for a,b in s)/max(1,sum(a for a,b in s)))
    # heterogeneity
    lo=hi=0
    for a,b in pr:
        if a>0 and b<=0.8*a: lo+=1
        elif (a>0 and b>=1.2*a) or (a==0 and b>0): hi+=1
    print(f"\n## {label}: {B} vs {A}  boards {nb}, both ok {len(both)}")
    print(f" cp1 {cA/nb:.3f} -> {cB/nb:.3f}  diff {100*(cB-cA)/nb:+.1f} pp CI [{100*ci_c[0]:+.1f},{100*ci_c[1]:+.1f}] +{up}/-{dn} McNemar p={mcnemar(up,dn):.3f}")
    print(f" legal {lA/nb:.3f} -> {lB/nb:.3f} diff {100*(lB-lA)/nb:+.1f} pp CI [{100*ci_l[0]:+.1f},{100*ci_l[1]:+.1f}] +{lup}/-{ldn} p={mcnemar(lup,ldn):.3f}")
    print(f" opens {sa} -> {sb} ratio {sb/max(1,sa):.3f} CI [{ci_o[0]:.3f},{ci_o[1]:.3f}] sign-flip p={p_o:.4f}; boards fewer/more/same opens {sum(b<a for a,b in pr)}/{sum(b>a for a,b in pr)}/{sum(a==b for a,b in pr)}")
    print(f" DRC errors {ea} -> {eb} ratio {eb/max(1,ea):.3f} CI [{ci_e[0]:.3f},{ci_e[1]:.3f}]")
    print(f" heterogeneity: B lower by >=20% on {lo} ({100*lo/len(pr):.0f}%), higher by >=20% on {hi} ({100*hi/len(pr):.0f}%)")
    ta=collections.Counter();tb=collections.Counter()
    for r in both:
        ta.update(r[A]['ebt'] or {}); tb.update(r[B]['ebt'] or {})
    ks=sorted(set(ta)|set(tb),key=lambda k:-(ta[k]+tb[k]))
    print(' per-type:',', '.join(f"{k} {ta[k]}->{tb[k]}" for k in ks))
    noA=sum(r[A]['status']!='ok' for r in rows); noB=sum(r[B]['status']!='ok' for r in rows)
    print(f" no_output {A} {noA}, {B} {noB}")
    # per-seed paired
    ps=[];bd=[]
    for r in both:
        pa=r[A]['per']; pb=r[B]['per']
        com=[i for i in pa if i in pb and pa[i]['v'] is not None and pb[i]['v'] is not None and pa[i]['rc']=='0' and pb[i]['rc']=='0']
        if not com: continue
        da=[pa[i]['v'][2] for i in com]; db=[pb[i]['v'][2] for i in com]
        ps+= list(zip(da,db)); bd.append((sum(da)/len(com),sum(db)/len(com)))
    sa2=sum(a for a,b in bd); sb2=sum(b for a,b in bd)
    ci=boot(bd,lambda s:sum(b for a,b in s)/max(1e-9,sum(a for a,b in s)))
    print(f" per-attempt opens paired by seed: {len(ps)} pairs on {len(bd)} boards, mean/board {sa2/len(bd):.2f} -> {sb2/len(bd):.2f} ratio {sb2/sa2:.3f} CI [{ci[0]:.3f},{ci[1]:.3f}] sign-flip p={signflip([b-a for a,b in bd]):.4f}")
    # first wave seeds 0-3 only (fresh from input)
    bd0=[]
    for r in both:
        pa=r[A]['per']; pb=r[B]['per']
        com=[i for i in map(str,range(4)) if i in pa and i in pb and pa[i]['v'] and pb[i]['v'] and pa[i]['rc']=='0' and pb[i]['rc']=='0']
        if com: bd0.append((sum(pa[i]['v'][2] for i in com)/len(com),sum(pb[i]['v'][2] for i in com)/len(com)))
    a0=sum(a for a,b in bd0);b0=sum(b for a,b in bd0); ci=boot(bd0,lambda s:sum(b for a,b in s)/max(1e-9,sum(a for a,b in s)))
    print(f" first-wave seeds 0-3: {len(bd0)} boards ratio {b0/a0:.3f} CI [{ci[0]:.3f},{ci[1]:.3f}] p={signflip([b-a for a,b in bd0]):.4f}")
    # near miss: C within 5 opens of clean (1..5) on attempt 0 or per seed
    nm=[(r[A]['unc'],r[B]['unc'],r['board']) for r in both if 1<=r[A]['unc']<=5 or 1<=r[B]['unc']<=5]
    cl_a=sum(a==0 for a,b,_ in nm); cl_b=sum(b==0 for a,b,_ in nm)
    print(f" near-miss boards (either arm 1-5 opens, attempt 0): {len(nm)}; opens {sum(a for a,b,_ in nm)} -> {sum(b for a,b,_ in nm)}; reach 0 opens {cl_a} -> {cl_b}; B fewer/more {sum(b<a for a,b,_ in nm)}/{sum(b>a for a,b,_ in nm)}")
    # per seed near miss: seed pairs where A in 1..5
    sp=[(a,b) for a,b in ps if 1<=a<=5 or 1<=b<=5]
    print(f"   per seed: {len(sp)} seed pairs near clean, opens {sum(a for a,b in sp)} -> {sum(b for a,b in sp)}, zero-open seeds {sum(a==0 for a,b in sp)} -> {sum(b==0 for a,b in sp)}")
    big=[(r[A]['unc'],r[B]['unc']) for r in both if r['pads']>400]
    if big:
        ci=boot(big,lambda s:sum(b for a,b in s)/max(1,sum(a for a,b in s)))
        print(f" big boards (>400 pads): {len(big)}, opens {sum(a for a,b in big)} -> {sum(b for a,b in big)} ratio {sum(b for a,b in big)/max(1,sum(a for a,b in big)):.3f} CI [{ci[0]:.3f},{ci[1]:.3f}] p={signflip([b-a for a,b in big]):.4f}")
    small=[(r[A]['unc'],r[B]['unc']) for r in both if r['pads']<=400]
    ci=boot(small,lambda s:sum(b for a,b in s)/max(1,sum(a for a,b in s)))
    print(f" boards <=400 pads: {len(small)}, opens {sum(a for a,b in small)} -> {sum(b for a,b in small)} ratio {sum(b for a,b in small)/max(1,sum(a for a,b in small)):.3f} CI [{ci[0]:.3f},{ci[1]:.3f}] p={signflip([b-a for a,b in small]):.4f}")
    cpuA=sorted(r[A]['cpu'] or 0 for r in both); cpuB=sorted(r[B]['cpu'] or 0 for r in both)
    print(f" CPU h total {sum(cpuA)/3600:.1f} -> {sum(cpuB)/3600:.1f}")
for A,B in (('C','R'),('C','P')):
    compare(keep,A,B,'all kept')
    compare([r for r in keep if r['merit']],A,B,'merit')
# side stats
for a in 'PR':
    s=[r[a]['side'] for r in keep if r[a]['side']]
    print(a,'flips median',sorted(x['flips'] for x in s)[len(s)//2],'to_back total',sum(x.get('to_back',0) for x in s),
      'back_smd before/after',sum(x['back_smd_before'] for x in s),sum(x['back_smd_after'] for x in s),'single reflow',sum(bool(x['single_reflow']) for x in s),'of',len(s))
