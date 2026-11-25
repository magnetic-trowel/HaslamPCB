# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import gzip,re,sys
def zero(path):
    t=(gzip.open if path.endswith('.gz') else open)(path,'rt',errors='replace').read()
    n=0
    for m in re.finditer(r"\((segment|arc)\b", t):
        seg=t[m.start():m.start()+600]
        w=re.search(r"\(width ([0-9.]+)\)", seg)
        if w and float(w.group(1))==0: n+=1
    return n
for p in sys.argv[1:]:
    z=zero(p)
    if z: print(z,p)
