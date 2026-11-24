# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A synthetic board of the ways same-net copper touches, to compare kae's connectivity models with KiCad's
(our own design, no third-party copper)."""
import uuid


def connectivity_board(path):
    """Write a board with one net per case of same-net copper to `path`; return the case nets. KiCad 10.0.7's
    connectivity (pcbnew_io.copper_items --clusters, zones refilled) joins every case's copper but C9's."""
    nets = ["", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"]
    u = lambda: str(uuid.uuid4())                                   # noqa: E731
    n = nets.index
    out = ['(kicad_pcb (version 20240108) (generator "pcbnew") (generator_version "8.0")',
           '(general (thickness 1.6) (legacy_teardrops no)) (paper "A4")',
           '(layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))', '(setup (pad_to_mask_clearance 0))']
    out += [f'(net {i} "{x}")' for i, x in enumerate(nets)]

    def pad(ref, x, y, net):
        return (f'(footprint "t:P" (layer "F.Cu") (uuid "{u()}") (at {x} {y}) (property "Reference" "{ref}" (at 0 0) '
                f'(layer "F.SilkS") (uuid "{u()}") (effects (font (size 1 1)))) (attr smd) (pad "1" smd rect (at 0 0) '
                f'(size 1 1) (layers "F.Cu") (net {n(net)} "{net}") (uuid "{u()}")))')

    def track(a, b, net, layer="F.Cu"):
        return (f'(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width 0.4) (layer "{layer}") (net {n(net)}) '
                f'(uuid "{u()}"))')

    def via(x, y, net):
        return f'(via (at {x} {y}) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net {n(net)}) (uuid "{u()}"))'

    def zone(net, y):     # x 10..20
        return (f'(zone (net {n(net)}) (net_name "{net}") (layer "F.Cu") (uuid "{u()}") (hatch edge 0.5) '
                f'(connect_pads yes (clearance 0.2)) (min_thickness 0.2) (filled_areas_thickness no) '
                f'(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)) '
                f'(polygon (pts (xy 10 {y}) (xy 20 {y}) (xy 20 {y + 10}) (xy 10 {y + 10}))))')
    y = lambda k: 20 * k                                            # noqa: E731
    # C1 a track crossing a fill, both ends outside; C2 a track ending 0.1 mm before the fill (its cap reaches in);
    # C3 a track ending 0.1 mm before a pad; C4 two tracks crossing in an X; C5 a track passing over a pad;
    # C6 a via 0.3 mm outside the fill (its disc reaches in); C7 a track ending in the fill; C8 a T junction;
    # C9 a track ending 0.3 mm before the fill (its cap 0.1 mm short): apart
    out += [zone("C1", y(0)), pad("A1", 2, y(0) + 5, "C1"), pad("B1", 15, y(0) + 8, "C1"),
            track((2, y(0) + 5), (28, y(0) + 5), "C1"),
            zone("C2", y(1)), pad("A2", 2, y(1) + 5, "C2"), pad("B2", 15, y(1) + 8, "C2"),
            track((2, y(1) + 5), (9.9, y(1) + 5), "C2"),
            pad("A3", 2, y(2) + 5, "C3"), pad("B3", 15, y(2) + 5, "C3"), track((2, y(2) + 5), (14.4, y(2) + 5), "C3"),
            pad("A4", 2, y(3) + 2, "C4"), pad("B4", 2, y(3) + 8, "C4"),
            track((2, y(3) + 2), (12, y(3) + 8), "C4"), track((2, y(3) + 8), (12, y(3) + 2), "C4"),
            pad("A5", 2, y(4) + 5, "C5"), pad("B5", 8, y(4) + 5, "C5"), track((2, y(4) + 5), (14, y(4) + 5), "C5"),
            zone("C6", y(5)), pad("A6", 2, y(5) + 5, "C6"), pad("B6", 15, y(5) + 8, "C6"),
            track((2, y(5) + 5), (5, y(5) + 5), "C6"), via(5, y(5) + 5, "C6"),
            track((5, y(5) + 5), (9.7, y(5) + 5), "C6", "B.Cu"), via(9.7, y(5) + 5, "C6"),
            zone("C7", y(6)), pad("A7", 2, y(6) + 5, "C7"), pad("B7", 15, y(6) + 8, "C7"),
            track((2, y(6) + 5), (11, y(6) + 5), "C7"),
            pad("A8", 2, y(7) + 2, "C8"), pad("B8", 8, y(7) + 8, "C8"),
            track((2, y(7) + 2), (14, y(7) + 2), "C8"), track((8, y(7) + 8), (8, y(7) + 2.15), "C8"),
            zone("C9", y(8)), pad("A9", 2, y(8) + 5, "C9"), pad("B9", 15, y(8) + 8, "C9"),
            track((2, y(8) + 5), (9.7, y(8) + 5), "C9"),
            f'(gr_rect (start -2 -2) (end 32 {y(9)}) (layer "Edge.Cuts") (stroke (width 0.1) (type default)) '
            f'(fill none) (uuid "{u()}"))', ')']
    path.write_text("\n".join(out) + "\n")
    return nets[1:]
