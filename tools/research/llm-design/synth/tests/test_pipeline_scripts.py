# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The design pipeline's scripts (synth/scripts) on synthetic inputs; no KiCad needed."""
import gzip
import importlib.util
import io
import json
import tarfile
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _result(neck, passes=20, timeout="00:08:00"):
    return json.dumps(dict(generated_at="2026-11-28T06:00:00Z", app_version="2.5.1", settings_snapshot=dict(
        autorouter=dict(start_necked=False, max_passes=passes), automatic_neckdown=neck, job_timeout=timeout,
        result_json="/x/y.json"))).encode()


def test_layout_settings_groups_runs_and_names_what_differs(tmp_path):
    ls = _load("layout_settings")
    d = tmp_path / "work" / "restarts" / "policy1" / "restarts"
    d.mkdir(parents=True)
    with tarfile.open(d / "fr-telemetry.tar", "w") as t:
        for name, raw in (("a0/1-1-board.result.json.gz", _result(True)),
                          ("a1/2-2-board.result.json.gz", _result(True, timeout="00:07:59")),
                          ("a4/3-3-board.result.json.gz", _result(False, passes=4)),
                          ("a4/3-3-board.log.gz", b"log")):
            data = gzip.compress(raw)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    (tmp_path / "work" / "fr-raw").mkdir()
    (tmp_path / "work" / "fr-raw" / "9-9-board.result.json").write_bytes(_result(True))
    rep = ls.summary(tmp_path)
    assert rep["freerouting_runs"] == 4
    assert rep["differs"] == ["automatic_neckdown", "autorouter.max_passes"]     # job_timeout is a budget
    by = {json.dumps(sorted(g["where"].items())): g for g in rep["groups"]}
    assert len(rep["groups"]) == 2
    on = next(g for g in rep["groups"] if g["settings"]["automatic_neckdown"])
    assert on["runs"] == 3 and on["where"]["restarts/policy1/restarts"] == ["a0", "a1"]
    assert sorted(on["settings"]["job_timeout"]) == ["00:07:59", "00:08:00"]
    assert any("fr-raw" in w for w in on["where"])
    assert "result_json" not in json.dumps(by)
    txt = "\n".join(ls.lines(rep))
    assert "automatic_neckdown=false" in txt and "2 distinct settings" in txt


# ---------------------------------------------------------------------------------------------- pipeline warnings
def test_warning_table_counts_and_reasons():
    pl = _load("pipeline")
    v = lambda t, s="warning": dict(type=t, severity=s, items=[])
    drc = dict(violations=[v("silk_overlap")] * 3 + [v("track_dangling")] * 2 + [v("clearance", "error")])
    t = pl.warning_table(drc, {"silk_overlap": "assembly drawing only", "_note": "x", "track_dangling": " "})
    assert t == [dict(type="silk_overlap", count=3, reason="assembly drawing only"),
                 dict(type="track_dangling", count=2, reason="")]


# ---------------------------------------------------------------------------------------------- fab_outputs CPL
def _fp(ref, fpid, rot, bottom=False, smd=True, npads=2, x=10.0, y=20.0, pcx=None, pcy=None):
    return dict(ref=ref, fpid=fpid, rot=rot, bottom=bottom, smd=smd, npads=npads, x=x, y=y,
                pcx=x if pcx is None else pcx, pcy=y if pcy is None else pcy)


def test_cpl_rotation_table_and_convention():
    fo = _load("fab_outputs")
    table = fo.load_rotations()
    assert len(table) > 40 and table[0][1] == "^Bosch_LGA-"
    # first match wins, on the name without its library
    assert fo.match_rotation("Package_TO_SOT_SMD:SOT-23", table)[2] == 180
    assert fo.match_rotation("Package_TO_SOT_SMD:SOT-23-5", table)[1] == "^SOT-23"
    assert fo.match_rotation("Capacitor_SMD:C_0603_1608Metric", table) is None
    # top: KiCad's rotation + correction; Y negated (KiCad's Y-down board, JLC's Y-up frame)
    ref, mx, my, layer, rot, rec, hit = fo.cpl_row(_fp("Q1", "Package_TO_SOT_SMD:SOT-23", 270), table)
    assert (mx, my, layer, rot, hit) == ("10.0000mm", "-20.0000mm", "Top", "90", True)
    assert rec["pattern"] == "^SOT-23" and rec["kicad_rot"] == 270
    # bottom: 180 - KiCad's, then the correction; X kept positive
    *_, rot, rec, _ = fo.cpl_row(_fp("Q2", "Package_TO_SOT_SMD:SOT-23", 90, bottom=True), table)
    assert rot == "270" and rec["side"] == "bottom"
    *_, rot, _, hit = fo.cpl_row(_fp("R1", "Resistor_SMD:R_0603_1608Metric", -90), table)
    assert rot == "270" and not hit
    # through-hole: the pads' centre, not the footprint origin
    row = fo.cpl_row(_fp("J1", "TerminalBlock_Phoenix:X", 90, smd=False, npads=2, pcx=10.0, pcy=17.46), table)
    assert row[1:3] == ("10.0000mm", "-17.4600mm")


def test_cpl_polarised_parts_are_flagged():
    fo = _load("fab_outputs")
    assert fo.polarised("D3", "Diode_SMD:D_SMA", 2) and fo.polarised("C9", "Capacitor_SMD:CP_Elec_8x10", 2)
    assert fo.polarised("U1", "custom:LTC_FE20", 21) and fo.polarised("J3", "Connector_USB:USB_C", 8)
    assert not fo.polarised("R1", "Resistor_SMD:R_0603_1608Metric", 2)
    assert not fo.polarised("C1", "Capacitor_SMD:C_0805_2012Metric", 2)


def test_review_compose_recolours_layers_in_order():
    rr = _load("review_render")
    a = ('<?xml?>\n<svg width="10mm" height="5mm">\n<g style="stroke:#C83434; fill:#C83434">A</g>\n'
         '<g style="fill:#FFFFFF">h</g>\n</svg>\n')
    b = '<?xml?>\n<svg width="10mm" height="5mm">\n<g style="stroke:#B4DBD2">B</g>\n</svg>\n'
    s = rr.compose([(a, "#111111"), (b, "#222222")])
    assert s.count("<svg") == 1 and s.index(">A<") < s.index(">B<")
    assert "#C83434" not in s and "#B4DBD2" not in s and "#FFFFFF" in s and "#222222" in s
