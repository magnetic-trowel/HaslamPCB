# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Design 4 micro test: checkpoint replay of the stored BR near-miss boards, last mile alone (control) vs
# last mile + conflict-set closure (closure). One board, one arm per call; kicad-cli DRC on the written board.
# usage: python closure_micro.py BOARD ARM(control|closure) [TIME=120]
import gzip, json, os, shutil, subprocess, sys, time, glob
D = os.environ['D4']        # the design-4 folder: cs_near.json, work/<board>/in-BR/ (cs_run.py's input rebuild)
RES = os.environ.get('KAE_RESULTS') or os.path.expanduser('~/kae-baselines')
b, arm = sys.argv[1], sys.argv[2]
T = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
x = next(r for r in json.load(open(f'{D}/cs_near.json'))['BR'] if r['board'] == b)
run = f"{RES}/boards/{b}/runs/{x['run']}"
wd = f'{D}/micro/{b}/{arm}'
shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
inp = f'{D}/work/{b}/in-BR/board.kicad_pcb'
with gzip.open(run + '/output.kicad_pcb.gz', 'rb') as f, open(f'{wd}/routed.kicad_pcb', 'wb') as g:
    shutil.copyfileobj(f, g)
sys.path.insert(0, os.environ['KAE_SRC'])
from kae.route import drc, lastmile as LM
d0 = drc.run(drc.stage_board(f'{wd}/routed.kicad_pcb', inp, f'{wd}/drc0'), f'{wd}/drc0/drc.json')
s0 = drc.summary(d0)
cmd = [sys.executable, '-m', 'kae.route.cli', 'lastmile', inp, f'{wd}/routed.kicad_pcb', f'{wd}/out.kicad_pcb',
       '--time', str(T), '--report', f'{wd}/report.json']
if arm == 'closure':
    cmd += ['--set', 'closure=1']
t = time.time()
r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=os.environ['KAE_SRC']))
secs = round(time.time() - t, 1)
open(f'{wd}/cli.log', 'w').write(r.stderr[-200000:])
out = f'{wd}/out.kicad_pcb' if os.path.exists(f'{wd}/out.kicad_pcb') else f'{wd}/routed.kicad_pcb'
d1 = drc.run(drc.stage_board(out, inp, f'{wd}/drc1'), f'{wd}/drc1/drc.json')
s1 = drc.summary(d1)
recs = []
try:
    rep = json.load(open(f'{wd}/report.json'))
    def walk(o):
        if isinstance(o, dict):
            if 'closure' in o and isinstance(o['closure'], dict):
                recs.append(o['closure'])
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(rep)
except Exception as e:
    rep = dict(error=str(e))
res = dict(board=b, arm=arm, opens_before=s0['unconnected'], errors_before=s0['errors'], opens_after=s1['unconnected'],
           errors_after=s1['errors'], by_type_after=s1.get('by_type'), clean=(s1['unconnected'] == 0 and s1['errors'] <= s0['errors']),
           seconds=secs, rc=r.returncode, closure=recs)
json.dump(res, open(f'{wd}/result.json', 'w'), indent=1, default=str)
print(json.dumps(res, default=str)[:3000])
