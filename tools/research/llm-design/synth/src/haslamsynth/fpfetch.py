# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`haslamsynth fp-fetch <C-number>`: JLC/EasyEDA's land pattern as a KiCad 10 footprint (FRICTION #16, #17, #18).

Steps:

1. GET `https://easyeda.com/api/products/<C>/components` through `haslamsynth.fetch` (throttled, cached);
2. convert it with easyeda2kicad's importer and exporter (optional dependency: `pip install -e '.[parts]'`;
   easyeda2kicad is AGPL-3.0, used as a separate library, not copied). It writes a legacy KiCad 5
   `(module ...)` file; the 3D-model reference is dropped;
3. add a hidden `Source` property (C-number, date, "no licence stated");
4. `kicad-cli fp upgrade` to the current format, rename to `--name` (default: EasyEDA's package name);
5. write `<design>/footprints/custom.pretty/<name>.kicad_mod` (`--design`), `--out DIR/<lib>.pretty`, or the
   cache; refuses to overwrite without `--force`;
6. print the pads; with `--check-part parts.py:NAME`, compare them with that part card's pin numbers
   (missing pads are an error, exit 1; extra pads, e.g. an exposed pad, a warning).

Licence: EasyEDA/LCSC land patterns carry no stated licence (FRICTION #27). The command says so on every
run and writes it into the footprint's `Source` property; record the decision in REUSE.toml before
committing one, or redraw it from the datasheet.
"""
from __future__ import annotations

import datetime
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import fetch
from .kicadlib import read_footprint

EASYEDA_API = "https://easyeda.com/api/products/{lcsc}/components"
LICENCE_NOTE = ("licence: EasyEDA/LCSC footprints have no stated licence (FRICTION #27); decide before committing "
                "(REUSE.toml entry, or redraw from the datasheet)")


class FpFetchError(RuntimeError):
    pass


def fetch_cad(lcsc, client=None, refresh=False):
    """EasyEDA's component record (the API's `result`) for a C-number."""
    c = client or fetch.client()
    url = EASYEDA_API.format(lcsc=lcsc)
    r = c.get(url, refresh=refresh, headers={"Accept": "application/json", "Referer": "https://easyeda.com/"})
    try:
        d = r.json()
    except ValueError as e:
        c.forget("GET", url)
        raise FpFetchError(f"{url}: not JSON ({e})") from e
    if not d or d.get("success") is False or not isinstance(d.get("result"), dict) or not d["result"]:
        c.forget("GET", url)
        raise FpFetchError(f"EasyEDA has no CAD data for {lcsc} ({str(d.get('message') or d.get('code') or '')[:80]})")
    if not (d["result"].get("packageDetail") or {}).get("dataStr"):
        raise FpFetchError(f"EasyEDA's record for {lcsc} has no footprint (packageDetail)")
    return d["result"]


def to_legacy(cad):
    """(EasyEDA package name, legacy `(module ...)` text) via easyeda2kicad."""
    try:
        from easyeda2kicad.easyeda.easyeda_importer import EasyedaFootprintImporter
        from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
    except ImportError as e:
        raise FpFetchError("easyeda2kicad is not installed: `uv pip install -e '.[parts]'` "
                           "(or pip install easyeda2kicad) in the synth venv") from e
    fp = EasyedaFootprintImporter(easyeda_cp_cad_data=cad).get_footprint()
    exp = ExporterFootprintKicad(footprint=fp)
    if hasattr(exp, "output"):
        exp.output.model_3d = None           # no 3D model files are fetched; drop the dangling reference
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "fp.kicad_mod"
        exp.export(footprint_full_path=str(p), model_3d_path="")
        return fp.info.name, p.read_text()


def add_source(legacy, lcsc, date=None):
    date = date or datetime.date.today().isoformat()
    prop = (f'\t(property "Source" "EasyEDA/LCSC {lcsc} via easyeda2kicad, fetched {date}; '
            f'no licence stated")\n')
    first, nl, rest = legacy.partition("\n")
    return first + nl + prop + rest


def upgrade(legacy, cli=None):
    """KiCad-10 text of a legacy footprint, via `kicad-cli fp upgrade`."""
    from .build import kicad_cli
    cmd = cli or kicad_cli()
    if not cmd:
        raise FpFetchError("kicad-cli not found (set HASLAM_KICAD_WRAP or install KiCad 10); the legacy file "
                           "would need `kicad-cli fp upgrade` by hand")
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.pretty", Path(td) / "out.pretty"
        src.mkdir()
        (src / "fp.kicad_mod").write_text(legacy)
        p = subprocess.run([*cmd, "fp", "upgrade", "--force", "--output", str(dst), str(src)],
                           capture_output=True, text=True, timeout=120)
        out = dst / "fp.kicad_mod"
        if p.returncode != 0 or not out.exists():
            raise FpFetchError(f"kicad-cli fp upgrade failed (rc {p.returncode}): {(p.stderr or p.stdout).strip()[:300]}")
        return out.read_text()


def rename(text, name):
    new, n = re.subn(r'^\(footprint\s+"[^"]*"', f'(footprint "{name}"', text, count=1)
    if not n:
        raise FpFetchError("upgraded file does not start with (footprint \"...\"")
    return new


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", s).strip("_")


def part_pins(spec):
    """{pin number: name} of a part card given as 'path/to/parts.py:NAME'."""
    path, sep, name = spec.rpartition(":")
    if not sep or not path:
        raise FpFetchError(f"--check-part {spec!r}: give path/to/parts.py:NAME")
    p = Path(path).resolve()
    if not p.exists():
        raise FpFetchError(f"--check-part: {p} not found")
    sys.path.insert(0, str(p.parent))
    try:
        mspec = importlib.util.spec_from_file_location(f"_parts_{abs(hash(str(p)))}", p)
        mod = importlib.util.module_from_spec(mspec)
        mspec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(p.parent))
    defn = getattr(mod, name, None)
    if defn is None or not hasattr(defn, "pins"):
        raise FpFetchError(f"--check-part: {p.name} has no part card {name}")
    if defn.pins:
        pins = {d.number: d.name for d in defn.pins}
    elif defn.symbol:
        from .kicadlib import SymbolLibs
        sym = SymbolLibs().get(defn.symbol)
        pins = {p.number: p.name for p in sym.pins}
    else:
        pins = {}
    pm = getattr(defn, "pinmap", {}) or {}
    return {pm.get(k, k): v for k, v in pins.items()}


def check_pads(pads, pins):
    """(card pins with no pad, pads with no card pin), both sorted naturally."""
    nat = lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]   # noqa: E731
    return sorted(set(pins) - set(pads), key=nat), sorted(set(pads) - set(pins), key=nat)


def dest_dir(design=None, out=None):
    if out:
        return Path(out)
    if design:
        return Path(design) / "footprints" / "custom.pretty"
    return fetch.cache_root() / "footprints" / "custom.pretty"


def run(lcsc, design=None, out=None, name=None, check_part=None, force=False, refresh=False, client=None,
        log=print, cli=None):
    lcsc = lcsc.strip().upper()
    if not re.fullmatch(r"C\d{2,}", lcsc):
        log(f"{lcsc}: give an LCSC C-number (e.g. C19272254); `haslamsynth parts search MPN` finds it")
        return 2
    try:
        pins = part_pins(check_part) if check_part else None
        cad = fetch_cad(lcsc, client=client, refresh=refresh)
        ee_name, legacy = to_legacy(cad)
        legacy = add_source(legacy, lcsc)
        fp_name = safe_name(name or ee_name)
        text = rename(upgrade(legacy, cli=cli), fp_name)
    except (FpFetchError, fetch.FetchError) as e:
        log(f"fp-fetch {lcsc}: {e}")
        return 2
    d = dest_dir(design, out)
    path = d / f"{fp_name}.kicad_mod"
    if path.exists() and not force:
        log(f"{path} exists; pass --force to replace it, or --name for another name")
        return 1
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    pads, head = read_footprint(path)
    lib = d.name[:-len(".pretty")] if d.name.endswith(".pretty") else d.name
    log(f"{lcsc}: EasyEDA package {ee_name} -> {path} ({head} format)")
    log(f"  use footprint=\"{lib}:{fp_name}\"; {len(pads)} pads: "
        + " ".join(check_pads(pads, {})[1]))
    log(f"  {LICENCE_NOTE}")
    log("  check the land pattern against the datasheet's recommended footprint before ordering boards")
    if pins is None:
        return 0
    missing, extra = check_pads(pads, pins)
    order = sorted(pins, key=lambda s: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)])
    log("  card pins (! = no pad): " + " ".join(f"{n}={pins[n]}" + ("" if n in pads else "!") for n in order))
    if extra:
        log(f"  warning: pads {extra} have no pin in {check_part} (exposed pad or mechanical? add the pin or "
            "leave them unconnected deliberately)")
    if missing:
        log(f"  ERROR: card pins {missing} have no pad: the card's numbering and the land pattern disagree")
        return 1
    log(f"  pads match {check_part}")
    return 0
