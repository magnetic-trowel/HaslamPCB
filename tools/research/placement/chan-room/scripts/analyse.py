# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, glob, os, collections, math, random
rows=[]
for f in glob.glob('out/*.jsonl'):
    b=os.path.basename(f).rsplit('.',2)[0]
    if 'cap-multiplier' in b: continue
    for l in open(f):
        d=json.loads(l); d['board']=b; d['u']=max(d['util']); rows.append(d)
print('runs',len(rows),'boards',len(set(r['board'] for r in rows)))
bins=[(0.40,0.55),(0.55,0.65),(0.65,0.70),(0.70,0.75),(0.75,0.80),(0.80,0.85),(0.85,1.0)]
print('bin        control           chan3')
for lo,hi in bins:
    out=[]
    for a in ('control','chan3'):
        R=[r for r in rows if r['arm']==a and lo<=r['u']<hi]
        out.append(f"{sum(r['failed'] for r in R):3d}/{len(R):3d} ({100*sum(r['failed'] for r in R)/max(1,len(R)):3.0f}%) b{len(set(r['board'] for r in R))}")
    print(f'{lo:.2f}-{hi:.2f}  {out[0]}  {out[1]}')
# per board failure point: lowest step u with >=2/3 fail and >=2/3 at all higher steps
fp={}
for b in sorted(set(r['board'] for r in rows)):
    for a in ('control','chan3'):
        st=collections.defaultdict(list)
        for r in rows:
            if r['board']==b and r['arm']==a: st[r['step']].append(r)
        us=sorted(((max(v[0]['util']),sum(x['failed'] for x in v),len(v)) for v in st.values()))
        pt=None
        for i,(u,f,n) in enumerate(us):
            if all(ff*3>=2*nn for _,ff,nn in us[i:]): pt=u; break
        fp[(b,a)]=pt
    print(b[:40], 'control',fp[(b,'control')],'chan3',fp[(b,'chan3')], [(round(u,3),f,n) for u,f,n in us][:3])
# logistic fit per arm (simple IRLS) + board bootstrap
def fit(R):
    w0,w1=0.0,0.0
    for _ in range(100):
        g0=g1=h00=h01=h11=0
        for r in R:
            x=r['u']; p=1/(1+math.exp(-(w0+w1*x))); y=r['failed']
            g0+=y-p; g1+=(y-p)*x; v=p*(1-p)+1e-9; h00+=v; h01+=v*x; h11+=v*x*x
        det=h00*h11-h01*h01
        if det<=0: break
        w0+=(h11*g0-h01*g1)/det; w1+=(-h01*g0+h00*g1)/det
        if abs(w1)>500: break
    return w0,w1
def uq(w,q): return (math.log(q/(1-q))-w[0])/w[1] if w[1] else float('nan')
boards=sorted(set(r['board'] for r in rows))
rng=random.Random(1)
res={}
for a in ('control','chan3'):
    R=[r for r in rows if r['arm']==a]; w=fit(R)
    bs=[]
    for _ in range(500):
        sm=[rng.choice(boards) for _ in boards]; RR=[r for b in sm for r in R if r['board']==b]
        ww=fit(RR); bs.append((uq(ww,.1),uq(ww,.5)))
    bs=[x for x in bs if all(math.isfinite(v) for v in x)]; bs.sort(key=lambda x:x[0]); l10=(bs[12][0],bs[-13][0]); bs.sort(key=lambda x:x[1]); l50=(bs[12][1],bs[-13][1])
    res[a]=w; print(a,'u10 %.3f [%.3f,%.3f] u50 %.3f [%.3f,%.3f]'%(uq(w,.1),*l10,uq(w,.5),*l50))
# excess curve
for u in [0.55+0.025*i for i in range(14)]:
    pc=1/(1+math.exp(-(res['control'][0]+res['control'][1]*u))); pa=1/(1+math.exp(-(res['chan3'][0]+res['chan3'][1]*u)))
    print(f'u {u:.3f} ctl {pc:.2f} chan3 {pa:.2f} excess {pa-pc:+.2f}')
