# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.board.sexpr and kae.board.model: parsing, block stripping, JSON round trip."""
import json
from pathlib import Path

from kae.board import kicad_file, sexpr
from kae.board.model import Board

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def test_parse_nested_strings_and_escapes():
    t = sexpr.parse('(a (b "x y" 1.5) (c "q\\"uote" "back\\\\slash" "") d)')
    assert t == ["a", ["b", "x y", "1.5"], ["c", 'q"uote', "back\\slash", ""], "d"]
    assert sexpr.first(t, "b") == ["b", "x y", "1.5"]
    assert sexpr.value(t, "b") == "x y"
    assert sexpr.kids(t, "zz") == []


def test_parse_parens_inside_strings():
    t = sexpr.parse('(p "a(b)c" (q ")"))')
    assert t == ["p", "a(b)c", ["q", ")"]]


def test_flag_forms():
    assert sexpr.flag(["fp", "lib", "locked"], "locked")
    assert sexpr.flag(["fp", ["locked", "yes"]], "locked")
    assert sexpr.flag(["fp", ["locked"]], "locked")
    assert not sexpr.flag(["fp", ["locked", "no"]], "locked")
    assert not sexpr.flag(["fp", "lib"], "locked")


def test_strip_blocks_pretty_and_single_line():
    pretty = ('(kicad_pcb\n\t(zone\n\t\t(net "GND")\n\t\t(filled_polygon\n\t\t\t(layer "F.Cu")\n'
              '\t\t\t(pts\n\t\t\t\t(xy 0 0) (xy 1 0) (xy 1 1)\n\t\t\t)\n\t\t)\n\t\t(polygon (pts (xy 0 0)))\n'
              '\t)\n\t(embedded_files\n\t\t(file (name "a(b).ttf") (data |abc|))\n\t)\n)\n')
    t = sexpr.parse(sexpr.strip_blocks(pretty))
    z = sexpr.first(t, "zone")
    assert sexpr.first(z, "filled_polygon") is None and sexpr.first(z, "polygon") is not None
    assert sexpr.first(t, "embedded_files") is None
    one_line = '(kicad_pcb (zone (filled_polygon (layer "F.Cu") (pts (xy 0 0))) (polygon (pts (xy 1 1)))))'
    t = sexpr.parse(sexpr.strip_blocks(one_line))
    assert t == ["kicad_pcb", ["zone", ["polygon", ["pts", ["xy", "1", "1"]]]]]


def test_strip_blocks_one_line_block_in_a_pretty_file():
    """A filled_polygon written on one line (other writers than KiCad): the next line equal to
    "<indent>)" belonged to the next zone's filled_polygon, the span to it balanced, and
    everything between was cut, zone B with it."""
    text = ('(kicad_pcb\n\t(zone\n\t\t(name "A")\n\t\t(filled_polygon (layer "F.Cu") (pts (xy 0 0)))\n\t)\n'
            '\t(zone\n\t\t(name "B")\n\t\t(filled_polygon\n\t\t\t(layer "F.Cu")\n\t\t\t(pts (xy 0 0))\n\t\t)\n'
            '\t\t(polygon (pts (xy 1 1)))\n\t)\n)\n')
    t = sexpr.parse(sexpr.strip_blocks(text))
    zones = [sexpr.value(z, "name") for z in sexpr.kids(t, "zone")]
    assert zones == ["A", "B"]
    assert all(sexpr.first(z, "filled_polygon") is None for z in sexpr.kids(t, "zone"))
    assert sexpr.first(sexpr.kids(t, "zone")[1], "polygon") is not None


def test_board_json_round_trip():
    b = kicad_file.load(FIXTURE)
    d = json.loads(json.dumps(b.to_dict()))
    b2 = Board.from_dict(d)
    assert b2 == b
    assert b2.footprints[0].pads[0] == b.footprints[0].pads[0]
    assert b2.outline[0].equals(b.outline[0]) and len(b2.outline[0].interiors) == len(b.outline[0].interiors)
    assert isinstance(b2.footprints[0].pads[0].size, tuple)
    # tolerant of fields from a newer writer
    d["footprints"][0]["new_field"] = 1
    d["new_board_field"] = 2
    assert Board.from_dict(d).footprints[0].ref == b.footprints[0].ref


def test_a_quote_inside_an_unquoted_atom_is_an_ordinary_character():
    """KiCad's lexer opens a quoted string only at the start of a token: a KiCad 5 field such as
    `'/"` is one atom. Reading its '"' as a string start swallowed the following footprints
    (39 of 507 on one corpus board)."""
    from kae.board import sexpr
    t = ('(kicad_pcb (module A (fp_text value \'/" (at 0 0)) (pad 1 smd)) '
         '(module B (fp_text value "x y" (at 1 1))) (net 0 "a\\"b"))')
    r = sexpr.parse(t)
    assert [m[1] for m in sexpr.kids(r, "module")] == ["A", "B"]
    assert r[1][2] == ["fp_text", "value", "'/\"", ["at", "0", "0"]]
    assert r[2][2][2] == "x y" and r[3] == ["net", "0", 'a"b']
    assert sexpr.block_end(t, t.index("(module A")) == t.index(" (module B")
