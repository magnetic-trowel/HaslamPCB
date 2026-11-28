# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refill every zone of a board and save it (KiCad's Python): `refill.py IN.kicad_pcb [OUT.kicad_pcb]`.

Routers and post-passes write zones without fills; gates that read copper from the file (width_check.py,
haslam's evaluator) need the fills KiCad would compute (obd-solar FRICTION.md #68)."""
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(sys.argv[2] if len(sys.argv) > 2 else sys.argv[1], b)
print(f"refilled {len(list(b.Zones()))} zones")
