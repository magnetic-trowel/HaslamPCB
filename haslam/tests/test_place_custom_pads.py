# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""place_custom_pad_copper: custom pads modelled by their anchor and primitives."""
def test_custom_pad_copper_bounds_the_primitives():
    from shapely.geometry import box
    from haslam.place.problem import pad_lib_rect
    from haslam.board.model import Pad
    p = Pad(number="4", net="", kind="smd", shape="custom", size=(1.0, 1.0), lx=0.0, ly=0.0, lrot=0.0, x=0.0, y=0.0,
            layers=["F.Cu"], outline=box(-0.5, -0.5, 20.0, 3.0))
    anchor = pad_lib_rect(p)
    full = pad_lib_rect(p, custom=True)
    assert abs(anchor[2] - 0.5) < 1e-9 and abs(full[2] - 20.0) < 1e-9 and abs(full[3] - 3.0) < 1e-9
    q = Pad(number="1", net="", kind="smd", shape="rect", size=(1.0, 2.0), lx=1.0, ly=0.0, lrot=0.0, x=1.0, y=0.0,
            layers=["F.Cu"])
    assert pad_lib_rect(q, custom=True) == pad_lib_rect(q)          # other shapes unchanged


def test_custom_pad_copper_setting_defaults_off():
    from haslam.route.constraints import DEFAULTS
    assert DEFAULTS["place_custom_pad_copper"] == 0
