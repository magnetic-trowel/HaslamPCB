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
