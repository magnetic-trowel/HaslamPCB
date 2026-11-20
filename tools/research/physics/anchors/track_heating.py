# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anchor check 3: IPC-2221 and the Brooks-Adam IPC-2152 fit against the tabulated points of
docs/topics/rules/power/high-current.md ("Trace width").

Criteria (fixed before the run, docs/research/physics/anchors-2611.md):
  PASS   each function reproduces each printed value to its last printed digit (+-0.5 of that digit;
         rises under 10 K, printed without a decimal, +-1 K)
  FAIL   any value outside
  claim  "IPC-2221 is conservative against IPC-2152" holds only if the IPC-2221 rise is at least the
         Brooks-Adam rise at every tabulated point

Run:  PYTHONPATH=haslam/src python tools/research/physics/anchors/track_heating.py
Exit code: 0 pass, 1 fail. Pure Python; instant.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'haslam' / 'src'))

from haslam.excite import dc as DC  # noqa: E402
from haslam.route import critical_physics as CP  # noqa: E402

OZ = {1: 0.035, 2: 0.070}
# high-current.md, "3 mm track, rise (K)": copper oz -> current A -> (IPC-2221, IPC-2152). The first run
# (2026-11-20) failed on two cells printed one too high, 146 (1 oz, 15 A, IPC-2152; computed 145.50) and
# 14 (2 oz, 10 A, IPC-2221; computed 13.49); the doc was corrected and these are its values now.
RISE_3MM = {
    1: {5: (9, 16), 8: (25, 41), 10: (42, 65), 12: (64, 93), 15: (106, 145)},
    2: {5: (3, 8), 8: (8, 21), 10: (13, 32), 12: (20, 47), 15: (34, 73)},
}
# widths at 10 K on 1 oz: (formula, current A, printed mm, half of the last printed digit)
WIDTHS = [
    ('ipc2221', 1.0, 0.30, 0.005), ('ipc2221', 5.0, 2.77, 0.005),
    ('ipc2221', 5.0, 2.8, 0.05), ('ipc2221', 10.0, 7.2, 0.05),
    ('ipc2152', 5.0, 4.6, 0.05), ('ipc2152', 10.0, 15.0, 0.5),
]


def bisect(f, lo, hi):
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if (f(lo) > 0) == (f(mid) > 0):
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def main():
    bad = 0
    colder = []
    misses = []
    print('3 mm outer track, rise in K: computed (printed in high-current.md)')
    print(f'  {"oz":>2s} {"A":>3s}  {"IPC-2221":>16s}  {"IPC-2152 fit":>16s}  {"2152/2221":>9s}')
    for oz, row in RISE_3MM.items():
        for cur, (p21, p52) in row.items():
            d21 = DC.ipc_dT(cur, 3.0, OZ[oz], external=True)
            d52 = DC.ipc2152_dT(cur, 3.0, OZ[oz])
            assert abs(d21 - CP.ipc2221_dT(cur, 3.0, OZ[oz])) < 1e-9 and abs(d52 - CP.ipc2152_dT(cur, 3.0, OZ[oz])) < 1e-9
            marks = []
            for name, d, p in (('IPC-2221', d21, p21), ('IPC-2152 fit', d52, p52)):
                ok = abs(d - p) <= (1.0 if p < 10 else 0.5)
                bad += not ok
                marks.append('' if ok else ' !')
                if not ok:
                    misses.append((oz, cur, name, d, p))
            if d21 < d52:
                colder.append((oz, cur))
            print(f'  {oz:2d} {cur:3d}  {d21:8.1f} ({p21:3d}){marks[0]:2s}  {d52:8.1f} ({p52:3d}){marks[1]:2s}  {d52 / d21:9.2f}')
    print('widths at 10 K on 1 oz, mm: computed (printed)')
    for law, cur, printed, tol in WIDTHS:
        w = CP.ipc2221_width(cur, 10.0, 0.035) if law == 'ipc2221' else CP.ipc2152_width(cur, 10.0, 0.035)
        ok = abs(w - printed) <= tol + 1e-12
        bad += not ok
        print(f'  {law} {cur:4.0f} A: {w:7.3f} ({printed:g}){"" if ok else " !"}')
        back = CP.ipc2221_dT(cur, w, 0.035) if law == 'ipc2221' else CP.ipc2152_dT(cur, w, 0.035)
        assert abs(back - 10.0) < 1e-6
    n = sum(len(r) for r in RISE_3MM.values()) * 2 + len(WIDTHS)
    print(f'{n - bad}/{n} tabulated values reproduced')
    for oz, cur, name, d, p in misses:
        print(f'  miss: {oz} oz, {cur} A, {name}: computed {d:.2f} K, printed {p} K')

    print('\nclaim "IPC-2221 is conservative against IPC-2152":')
    print(f'  IPC-2221 reads the lower rise at {len(colder)} of {sum(len(r) for r in RISE_3MM.values())} tabulated points'
          f' -> the claim {"holds" if not colder else "does not hold"} on the table')
    for oz, t in OZ.items():
        for dT in (10.0, 20.0, 40.0):
            i_x = bisect(lambda i: CP.ipc2152_width(i, dT, t) - CP.ipc2221_width(i, dT, t), 0.01, 100.0)
            w_x = CP.ipc2221_width(i_x, dT, t)
            print(f'  {oz} oz, sized for {dT:g} K: equal widths at {i_x:.2f} A ({w_x:.2f} mm); above it IPC-2152 asks for the'
                  f' wider track (x{CP.ipc2152_width(5, dT, t) / CP.ipc2221_width(5, dT, t):.2f} at 5 A,'
                  f' x{CP.ipc2152_width(10, dT, t) / CP.ipc2221_width(10, dT, t):.2f} at 10 A), below it the narrower'
                  f' (x{CP.ipc2152_width(0.5, dT, t) / CP.ipc2221_width(0.5, dT, t):.2f} at 0.5 A)')
    print('  inner layers: IPC-2221 internal (k = 0.024) against the same fit, widths at 10 K, 1 oz:')
    for cur in (1, 5, 10):
        print(f'    {cur:2d} A: IPC-2221 internal {CP.ipc2221_width(cur, 10.0, 0.035, internal=True):.2f} mm,'
              f' Brooks-Adam (external chart) {CP.ipc2152_width(cur, 10.0, 0.035):.2f} mm')
    print('  sizing setting HASLAM_TRACK_HEAT (track_width), outer layer, 10 K, 1 oz, mm:')
    for cur in (0.5, 1, 2, 5, 10):
        print(f'    {cur:4g} A: ' + ', '.join(f'{law} {CP.track_width(cur, 10.0, 0.035, law=law):.2f}' for law in CP.HEAT_LAWS))
    print(f'CHECK 3 VERDICT: {"PASS" if not bad else "FAIL"} (tabulated values);'
          f' conservative claim: {"holds" if not colder else "REJECTED"}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
