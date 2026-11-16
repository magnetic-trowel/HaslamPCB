# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage polish-replay's start boards: the board polish-merit's R arm (kae pmerit restarts 76fae3c, method
92b77cc37731) kept, for every board in boards.txt, as ~/.cache/kaebench/polish-replay-starts/<board>.kicad_pcb
(the methods read it there; the method sandbox can read ~/.cache/kaebench)."""
import glob
import gzip
import os
import shutil
from pathlib import Path

here = Path(__file__).parent
dst = Path(os.path.expanduser("~/.cache/kaebench/polish-replay-starts"))
dst.mkdir(parents=True, exist_ok=True)
for b in (here / "boards.txt").read_text().split():
    src = glob.glob(os.path.expanduser(f"~/kae-baselines/boards/{b}/runs/kae-pmerit-restarts-76fae3c.92b77cc3.a0/output.kicad_pcb.gz"))
    if not src:
        print("missing", b)
        continue
    with gzip.open(src[0], "rb") as f, open(dst / f"{b}.kicad_pcb", "wb") as g:
        shutil.copyfileobj(f, g)
print("staged", len(list(dst.glob("*.kicad_pcb"))))
