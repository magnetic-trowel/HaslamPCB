# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-board return rows (return_board.measure) for every control/gs4/gs2 run of results.csv at the given attempts."""
import csv, json, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, sys.argv[4] if len(sys.argv) > 4 else "tools/kaeres")   # return_board.py of the pre-rename tree (branch ground-side-default)
import return_board  # noqa: E402
STORE = Path.home() / "haslam-baselines/boards"
ARMS = {"71e60a91475d": "ctl", "e4f3e4f5aa53": "gs4", "9aa13b1dae71": "gs2"}
csvp, out, atts = Path(sys.argv[1]), Path(sys.argv[2]), {int(x) for x in sys.argv[3].split(",")}
rows = [r for r in csv.DictReader(open(csvp)) if r["method_id"] in ARMS and int(r["attempt"]) in atts]
def one(r):
    p = STORE / r["board"] / "runs" / r["run"] / "output.kicad_pcb.gz"
    try:
        m = return_board.measure(p)
        m = {k: v for k, v in m.items() if isinstance(v, (int, float, str)) or v is None}
    except Exception as e:  # noqa: BLE001
        m = {"error": f"{type(e).__name__}: {e}"}
    return r["board"], ARMS[r["method_id"]], int(r["attempt"]), m
res = {}
with ProcessPoolExecutor(8) as ex:
    for b, a, k, m in ex.map(one, rows, chunksize=2):
        res.setdefault(b, {}).setdefault(str(k), {})[a] = m
json.dump(res, open(out, "w"), indent=1)
print(len(rows), "runs")
