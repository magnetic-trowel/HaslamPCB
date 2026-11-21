#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""side-front-ab verdict, step 1: read every arm's attempt-0 run (score, KAE_SIDE line, per-seed judge lines).

Usage: extract_runs.py OUT.json   (reads ~/kae-baselines; boards.jsonl beside this file)
"""
import json,os,gzip,re,sys
R=os.path.expanduser('~/kae-baselines/boards')
X=os.path.expanduser('~/kae-baselines/experiments/side-front-ab')
meta={json.loads(l)['id']:json.loads(l) for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'boards.jsonl'))}
arms={'C':'kae-side-control-d0cee65-restarts.7c606bbb.a0','P':'kae-side-passives-d0cee65-restarts.38ea1b89.a0','R':'kae-side-rule-d0cee65-restarts.0d6ea305.a0'}
out=[]
pat=re.compile(r'end #(\d+) rc (\S+) \(illegal, not clean, unconnected, new errors, outside\) \(([^)]*)\)')
seedpat=re.compile(r'start #(\d+) seed (\d+) budget (\d+)s( from #(\d+))?')
for b in open(X+'/boards.txt').read().split():
    row={'board':b,**{k:meta[b][k] for k in ('pads','merit','fill','back_smd','front_smd')}}
    for a,d in arms.items():
        p=f'{R}/{b}/runs/{d}'
        if not os.path.isdir(p): continue
        rj=json.load(open(p+'/run.json'))
        ev={}
        if os.path.exists(p+'/evals/afa09d34bc94.json'):
            ev=json.load(open(p+'/evals/afa09d34bc94.json')).get('score') or {}
        side=None; seeds={}; starts={}
        try:
            for line in gzip.open(p+'/adapter.log.gz','rt',errors='replace'):
                if line.startswith('KAE_SIDE '): side=json.loads(line[9:])
                m=seedpat.search(line)
                if m: starts[int(m.group(1))]={'seed':int(m.group(2)),'from':m.group(5)}
                m=pat.search(line)
                if m:
                    v=[int(x) for x in m.group(3).split(',')]
                    seeds[int(m.group(1))]={'rc':m.group(2),'v':v}
        except Exception as e: pass
        per={}
        for i,s in seeds.items():
            st=starts.get(i,{})
            per[i]={**s,**st}
        row[a]={'status':rj.get('status'),'valid':ev.get('valid'),'legal':ev.get('legal'),'clean':ev.get('clean'),
          'unc':ev.get('unconnected'),'start_unc':ev.get('start_unconnected'),'errors':ev.get('errors'),'ebt':ev.get('errors_by_type'),
          'pe':ev.get('placement_errors'),'cpu':(rj.get('method_usage') or {}).get('cpu_s'),'side':side,'per':per,'finished':rj.get('finished'),
          'scored':bool(ev)}
    out.append(row)
json.dump(out,open(sys.argv[1],'w'))
