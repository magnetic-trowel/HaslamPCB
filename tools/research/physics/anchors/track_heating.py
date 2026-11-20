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
# high-current.md, "3 mm track, rise (K)": copper oz -> current A -> (IPC-2221, IPC-2152)
RISE_3MM = {
    1: {5: (9, 16), 8: (25, 41), 10: (42, 65), 12: (64, 93), 15: (106, 146)},
    2: {5: (3, 8), 8: (8, 21), 10: (14, 32), 12: (20, 47), 15: (34, 73)},
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
    print('3 mm outer track, rise in K: computed (printed in high-current.md)')
    print(f'  {"oz":>2s} {"A":>3s}  {"IPC-2221":>16s}  {"IPC-2152 fit":>16s}  {"2152/2221":>9s}')
    for oz, row in RISE_3MM.items():
        for cur, (p21, p52) in row.items():
            d21 = DC.ipc_dT(cur, 3.0, OZ[oz], external=True)
            d52 = DC.ipc2152_dT(cur, 3.0, OZ[oz])
            assert abs(d21 - CP.ipc2221_dT(cur, 3.0, OZ[oz])) < 1e-9 and abs(d52 - CP.ipc2152_dT(cur, 3.0, OZ[oz])) < 1e-9
            marks = []
            for d, p in ((d21, p21), (d52, p52)):
                ok = abs(d - p) <= (1.0 if p < 10 else 0.5)
                bad += not ok
                marks.append('' if ok else ' !')
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

    print('\nclaim "IPC-2221 is conservative against IPC-2152":')
    print(f'  IPC-2221 reads the lower rise at {len(colder)} of {sum(len(r) for r in RISE_3MM.values())} tabulated points'
          f' -> the claim {"holds" if not colder else "does not hold"} on the table')
    for oz, t in OZ.items():
        i_x = bisect(lambda i: CP.ipc2152_width(i, 10.0, t) - CP.ipc2221_width(i, 10.0, t), 0.01, 100.0)
        w_x = CP.ipc2221_width(i_x, 10.0, t)
        print(f'  {oz} oz, sized for 10 K: the two widths are equal at {i_x:.2f} A ({w_x:.2f} mm); above it IPC-2152 asks for'
              f' the wider track: x{CP.ipc2152_width(5, 10.0, t) / CP.ipc2221_width(5, 10.0, t):.2f} at 5 A,'
              f' x{CP.ipc2152_width(10, 10.0, t) / CP.ipc2221_width(10, 10.0, t):.2f} at 10 A;'
              f' at 0.5 A x{CP.ipc2152_width(0.5, 10.0, t) / CP.ipc2221_width(0.5, 10.0, t):.2f}')
        for w in (0.2, 0.5, 1.0, 3.0):
            i_e = bisect(lambda i: CP.ipc2152_dT(i, w, t) - CP.ipc2221_dT(i, w, t), 1e-3, 1e3)
            print(f'    {w:g} mm track: equal rise at {i_e:.2f} A ({CP.ipc2221_dT(i_e, w, t):.1f} K); IPC-2152 is the hotter above it')
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
