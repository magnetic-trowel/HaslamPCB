# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fabrication profiles: one JSON file per fab process, every limit with its source.

haslamsynth writes a profile's `board` entries into the project's board setup (.kicad_pro rules), its `dru` entries
as custom rules at the top of the .kicad_dru (so design rules further down still win), and records the profile's
name in the project (text variable FAB_PROFILE) so preflight can check a board against it. Without a profile, KiCad's
defaults stand in for the fab's limits and a clean DRC says nothing about manufacturability (obd-solar FRICTION.md
#37).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT = "jlc-2layer-1oz"


def load(name):
    p = HERE / f"{name}.json"
    if not p.exists():
        raise ValueError(f"unknown fab profile {name!r}; profiles: {', '.join(names())}")
    return json.loads(p.read_text())


def names():
    return sorted(p.stem for p in HERE.glob("*.json"))


def board_rules(profile):
    """{.kicad_pro rule key: mm}."""
    return {k: v[0] for k, v in profile.get("board", {}).items()}


def dru_rules(profile):
    """Custom-rule text for the limits the board setup cannot express (plated pads differ from vias)."""
    d = {k: v[0] for k, v in profile.get("dru", {}).items()}
    src = profile.get("source", "")
    out = [f"# fab profile {profile['name']}: {src}"]
    if "pth_annular_width" in d:
        out.append(f'(rule "FAB:pth_annular_width"\n  (condition "A.Type == \'Pad\' && A.isPlated()")\n'
                   f'  (constraint annular_width (min {d["pth_annular_width"]}mm)))')
    if "pad_hole_to_hole" in d:
        out.append(f'(rule "FAB:pad_hole_to_hole"\n  (condition "A.Type == \'Pad\' && B.Type == \'Pad\'")\n'
                   f'  (constraint hole_to_hole (min {d["pad_hole_to_hole"]}mm)))')
    if "pth_hole_clearance" in d:
        out.append(f'(rule "FAB:pth_hole_clearance"\n  (condition "A.Type == \'Pad\' && A.isPlated()")\n'
                   f'  (constraint hole_clearance (min {d["pth_hole_clearance"]}mm)))')
    return "\n".join(out) + "\n"
