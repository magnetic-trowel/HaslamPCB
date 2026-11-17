# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""polish-replay: opens after iteration 0 (the bridge pass on the kept board) vs after the windows, from adapter logs."""
import csv,os,re,gzip,glob
E=os.path.expanduser('~/kae-baselines/experiments/polish-replay2/results.csv')
rows={}
for r in csv.DictReader(open(E)):
    if r['attempt']=='0' and r['method'].startswith('kae preplay2 '):
        rows.setdefault(r['board'],{})['copy' if ' copy ' in r['method'] else 'pol']=r
tot=[0,0,0,0]; n=0; agg={'iter0':0,'windows':0,'lastmile':0}
for b,v in sorted(rows.items()):
    if len(v)<2 or v['pol']['status']!='ok': continue
    d=glob.glob(os.path.expanduser(f"~/kae-baselines/boards/{b}/runs/kae-preplay2-polish11*.a0/adapter.log.gz"))[0]
    t=gzip.open(d,'rt',errors='replace').read()
    i0=re.search(r'iter 0: (\d+) unconnected',t); its=re.findall(r'iter (\d+): window .*?: (\d+) unconnected.*?-> (kept|discarded|\w+)',t)
    lm=re.findall(r'last mile on the kept board \(.*?\): (kept|discarded)',t)
    fin=re.search(r'final (\d+) unconnected',t)
    oc=int(v['copy']['unconnected']); op=int(v['pol']['unconnected'])
    s=f"{b[:40]:40s} copy {oc:4d} iter0 {i0.group(1) if i0 else '-':>4} final {fin.group(1) if fin else '-':>4} scored {op:4d} windows kept {sum(k=='kept' for _,_,k in its)}/{len(its)} lastmile {lm}"
    if op!=oc: print(s)
    n+=1
import math,statistics as st
A=[];I=[];F=[]
for b,v in sorted(rows.items()):
    if len(v)<2 or v['pol']['status']!='ok': continue
    d=glob.glob(os.path.expanduser(f"~/kae-baselines/boards/{b}/runs/kae-preplay2-polish11*.a0/adapter.log.gz"))[0]
    t=gzip.open(d,'rt',errors='replace').read()
    i0=re.search(r'iter 0: (\d+) unconnected',t)
    oc=int(v['copy']['unconnected']); op=int(v['pol']['unconnected']); ec,ep=int(v['copy']['errors']),int(v['pol']['errors'])
    ok=op if (op,ep)<=(oc,ec) else oc
    i=int(i0.group(1)) if i0 else oc
    A.append(oc);I.append(min(i,oc));F.append(ok)
print('copy',sum(A),'after iter0 (kae count)',sum(I),'final kept',sum(F))
