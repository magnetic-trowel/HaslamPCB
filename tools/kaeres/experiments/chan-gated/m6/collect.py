# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import json, glob, gzip, re, os, sys
E=os.path.expanduser('~/kae-baselines/experiments/chan-gated-m6')
ids={'25339b55':'control','f5882879':'chan3'}
trim=json.load(open(E+'/TRIM-2026-11-20.json'))
parked=set(trim['parked_boards'])
out=[]
for b in open(E+'/boards.txt').read().split():
    for d in glob.glob(os.path.expanduser(f'~/kae-baselines/boards/{b}/runs/*')):
        m=re.search(r'\.([0-9a-f]{8})\.a(\d)$',d)
        if not m or m.group(1) not in ids: continue
        r=json.load(open(d+'/run.json'))
        sc=None
        for f in glob.glob(d+'/evals/*.json'):
            j=json.load(open(f))
            if 'score' in j: sc=j['score']
        row=dict(board=b,arm=ids[m.group(1)],seed=int(m.group(2)),status=r.get('status'),parked=b in parked)
        if sc:
            row.update(unc=sc.get('unconnected'),start=sc.get('start_unconnected'),errors=sc.get('errors'),
                       etypes=sc.get('errors_by_type'),legal=sc.get('legal'),wl=sc.get('track_length_mm'),
                       completion=sc.get('completion'),clean=sc.get('clean'),perr=sc.get('placement_errors'))
        try:
            t=gzip.open(d+'/adapter.log.gz','rt').read()
            mm=re.findall(r'"channel": (\{[^}]*\})',t)
            if mm: row['chan']=json.loads(mm[-1])
        except Exception as e: pass
        js=r.get('job_steps') or {}
        row['cpu']=(js.get('run') or {}).get('cgroup_cpu_s')
        out.append(row)
json.dump(out,open('./runs.json','w'))
print(len(out), sum(1 for r in out if r.get('unc') is not None))
