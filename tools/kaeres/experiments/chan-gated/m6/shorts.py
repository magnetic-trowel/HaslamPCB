# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# pad-to-pad copper overlaps of different nets between parts, per run output, and the parts' gap to the edge
import sys, gzip, glob, os, json, tempfile, collections
import shapely
from shapely.geometry import Polygon
from kae.board.kicad_file import load
from kae.place.problem import pad_corners
from kae.board import transform
def pads(b):
    out=[]
    for f in b.footprints:
        for pd in f.pads:
            lays=[l for l in (pd.layers or []) if l.endswith('.Cu')]
            if not lays: continue
            cs=pad_corners(pd)
            x,y=transform.pads_xy(cs[:,0],cs[:,1],f.x,f.y,f.rot,f.side)
            sides=set()
            for l in lays:
                if l=='*.Cu': sides|={'F','B'}
                elif l=='F.Cu': sides.add('F' if f.side in ('F','front',1) or True else 'B')
                elif l=='B.Cu': sides.add('B')
            # SMD pad layers are given in library frame; flip for back-side footprints
            if str(f.side).upper().startswith('B') and '*.Cu' not in lays:
                sides={'B' if s=='F' else 'F' for s in sides}
            out.append((f.ref,pd.name if hasattr(pd,'name') else '',pd.net or '',sides,Polygon(list(zip(x,y)))))
    return out
for b in sys.argv[1:]:
    res={}
    for d in sorted(glob.glob(os.path.expanduser(f'~/kae-baselines/boards/{b}/runs/*'))):
        arm={'25339b55':'control','f5882879':'chan3'}.get(d.split('.')[-2]);
        if not arm: continue
        with tempfile.NamedTemporaryFile(suffix='.kicad_pcb') as t:
            t.write(gzip.open(d+'/output.kicad_pcb.gz').read()); t.flush(); B=load(t.name)
        P=pads(B); geoms=[p[4] for p in P]; tree=shapely.STRtree(geoms)
        hits=collections.Counter(); nets=collections.Counter()
        for i,(ref,nm,net,sd,g) in enumerate(P):
            for j in tree.query(g, predicate='intersects'):
                if j<=i: continue
                r2,n2,net2,sd2,g2=P[j]
                if r2==ref or (net and net==net2) or not (sd & sd2): continue
                hits[tuple(sorted((ref,r2)))]+=1; nets[tuple(sorted((net,net2)))]+=1
        ol=shapely.union_all([o for o in B.outline if o.area>0]) if B.outline else None
        res[d.split('/')[-1][-11:]]=dict(arm=arm,pad_overlaps=sum(hits.values()),pairs=hits.most_common(6),nets=nets.most_common(4))
    print(b); 
    for k,v in res.items(): print(' ',v['arm'],k[-2:],v['pad_overlaps'],v['pairs'][:5])
