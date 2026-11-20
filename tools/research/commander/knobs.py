# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generated inventory of the knobs a commander can turn, and of the loop-back decisions they serve.

    python tools/research/commander/knobs.py            # (re)write the doc and knobs.json
    python tools/research/commander/knobs.py --check    # exit 1 when either is stale

Introspects, from the code (never by hand):
- the `--set` registries: kae.route.constraints.DEFAULTS (also KAE_<NAME> text variables),
  kae.route.bridge.DEFAULT_OPTS, kae.joint.loop.DEFAULTS, kae.joint.stages.STAGE_KEYS;
- option keys the route and joint code reads (`o.get("k")`, `opts["k"]`, ...) that neither a registry
  nor a stage-internal DEFAULTS (INTERNAL: critical, critical_taut, finish, incremental, power_copper,
  taut) names; a heuristic list (the reader may be another dict also called `o`);
- the argparse flags of `kae`, `kae.route.cli`, `kae.joint.cli` and tools/kaeres/restart.py;
- every KAE_* environment variable read (os.environ / os.getenv / setting_env) under kae/src,
  bench/src and tools/kaeres.

LOOPBACK below is the only hand-kept table: an expert's loop-back decision, the knob(s) that act on
it today, scope, effect and whether the scorer allows it. Every knob it names must exist in the
introspected set, so the doc cannot name a knob that the code lost (main() raises). Writes
docs/topics/workflow/commander-knobs.md and tools/research/commander/knobs.json.
"""
import argparse
import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/topics/workflow/commander-knobs.md"
JSON = Path(__file__).resolve().parent / "knobs.json"
SRC = ROOT / "kae/src"

# decision, knobs (names in the inventory: a --set key, "ENV:KAE_X", "<cli> --flag"), scope, effect, scorer
LOOPBACK = [
    ("Rotate a named part", ["kae place --angles"], "global step only", "none per part", "yes"),
    ("Move a part; region, near, group, corridor", ["kae place --fix"], "hold in place (place only)",
     "none beyond hold", "yes"),
    ("Flip a part; side policy", [], "-", "none", "yes"),
    ("Via-in-pad", ["ball_escapes"], "ball-grid escape plans", "plan and certificate; via-in-pad not laid", "yes"),
    ("Via size, microvia", [], "-", "one via per net class", "no (rules)"),
    ("Neck-down", ["neckdown"], "global", "full", "yes"),
    ("Layer mask per net or class", ["planes", "plane_cost", "plane_strict_share"], "board plane layers",
     "board-level only", "per net yes; new layer no"),
    ("Relax a board rule", [], "-", "diagnosis only (blocked, fab)", "no"),
    ("Relax a kae default", ["ignored_clearance_floor", "pad_entry_overlap", "kae place --severity"],
     "global", "full", "yes"),
    ("Pin or gate swap", [], "-", "none", "no (pad nets hashed)"),
    ("Add a layer; grow the outline", [], "-", "certificates only", "no"),
    ("Net order, per-net effort", ["kae.route.cli route --seed"], "permutes order", "indirect", "yes"),
    ("More passes, rounds, time", ["passes", "rounds", "router_share", "max_iters", "kae.route.cli route --time"],
     "global", "full", "yes"),
    ("Placer term weights", ["escape_band", "escape_band_w", "kae place --anneal-args"], "global", "full", "yes"),
]

REGISTRIES = [  # (name, module, attribute, how a joint run spells the key)
    ("constraints", "kae.route.constraints", "DEFAULTS", "{k}"),
    ("bridge", "kae.route.bridge", "DEFAULT_OPTS", "bridge.{k}"),
    ("loop", "kae.joint.loop", "DEFAULTS", "{k}"),
    ("stages", "kae.joint.stages", "STAGE_KEYS", "{k}"),
]
CLIS = [("kae", "kae.cli"), ("kae.route.cli", "kae.route.cli"), ("kae.joint.cli", "kae.joint.cli"),
        ("restart.py", ROOT / "tools/kaeres/restart.py")]
ENV_DIRS = [SRC / "kae", ROOT / "bench/src", ROOT / "tools/kaeres"]
ENV_RE = re.compile(r"""(?:environ(?:\.get|\.setdefault|\.pop)?\s*[\[(]|getenv\s*\()\s*['"](KAE_[A-Z0-9_]+)['"]""")
SETENV_RE = re.compile(r"""setting_env\(\s*['"]([a-z0-9_]+)['"]""")
OPT_RE = re.compile(r"""\b(?:o|opts|self\.opts|options)(?:\.get\(\s*|\[\s*)['"]([a-z][a-z0-9_]*)['"]""")
OPT_DIRS = [SRC / "kae/route", SRC / "kae/joint"]
# stage-internal option dicts: their keys are filled by the calling stage, not by --set
INTERNAL = ["kae.route.critical", "kae.route.critical_taut", "kae.route.finish", "kae.route.incremental",
            "kae.route.power_copper", "kae.route.taut"]


def _rel(p):
    return Path(p).resolve().relative_to(ROOT).as_posix()


def _comments(module):
    """{key: first comment line after `key=` in the module's DEFAULTS-like dict(...) literals}."""
    src = Path(importlib.util.find_spec(module).origin)
    lines = src.read_text(encoding="utf-8").splitlines()
    out = {}
    for node in ast.walk(ast.parse("\n".join(lines))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "dict":
            for kw in node.keywords:
                if kw.arg and kw.arg not in out:
                    line = lines[kw.value.end_lineno - 1]
                    out[kw.arg] = line.split("#", 1)[1].strip() if "#" in line else ""
    return out


def _default(v):
    return v if isinstance(v, (bool, int, float, str, type(None))) else repr(v)


def registry_knobs():
    knobs = []
    for reg, mod, attr, spell in REGISTRIES:
        m = __import__(mod, fromlist=[attr])
        val = getattr(m, attr)
        notes = _comments(mod)
        for k in sorted(val):
            knobs.append(dict(name=k, surface="set", registry=f"{mod}.{attr}", joint=spell.format(k=k),
                              route=reg in ("constraints", "bridge"),
                              default=_default(val[k]) if isinstance(val, dict) else None,
                              text_var=f"KAE_{k.upper()}" if reg == "constraints" else None,
                              note=notes.get(k, "")))
    return knobs


def unregistered_keys(known):
    """Option keys the route and joint code reads that no registry names: {key: [file, ...]}."""
    seen = {}
    for d in OPT_DIRS:
        for f in sorted(d.glob("*.py")):
            for k in OPT_RE.findall(f.read_text(encoding="utf-8")):
                if k not in known:
                    seen.setdefault(k, set()).add(_rel(f))
    return {k: sorted(v) for k, v in sorted(seen.items())}


class _Got(Exception):
    def __init__(self, parser):
        self.parser = parser


def _parser(target):
    """The ArgumentParser a CLI's main() builds, caught at parse_args (main does nothing else)."""
    orig = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        raise _Got(self)
    argparse.ArgumentParser.parse_args = grab
    argv = sys.argv
    try:
        if isinstance(target, Path):
            spec = importlib.util.spec_from_file_location("_kae_knobs_cli", target)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        else:
            mod = __import__(target, fromlist=["main"])
        sys.argv = ["x"]
        try:
            mod.main() if isinstance(target, Path) else mod.main([])
        except _Got as g:
            return g.parser
        raise RuntimeError(f"{target}: main() did not parse arguments")
    finally:
        argparse.ArgumentParser.parse_args = orig
        sys.argv = argv


def _flags(parser, prefix):
    out = []
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in sorted(act.choices.items()):
                out += _flags(sub, f"{prefix} {name}")
        elif act.option_strings and not isinstance(act, argparse._HelpAction):
            flag = max(act.option_strings, key=len)
            out.append(dict(name=f"{prefix} {flag}", surface="cli", cli=prefix, flag=flag,
                            default=_default(act.default), choices=list(act.choices) if act.choices else None,
                            note=" ".join((act.help or "").split())[:160]))
    return out


def cli_knobs():
    out = []
    for name, target in CLIS:
        out += _flags(_parser(target), name)
    return sorted(out, key=lambda k: k["name"])


def env_knobs(constraint_keys):
    seen = {}
    for d in ENV_DIRS:
        for f in sorted(d.rglob("*.py")):
            t = f.read_text(encoding="utf-8", errors="replace")
            names = set(ENV_RE.findall(t)) | {"KAE_" + k.upper() for k in SETENV_RE.findall(t)}
            for n in names:
                seen.setdefault(n, set()).add(_rel(f))
    return [dict(name=f"ENV:{n}", surface="env", var=n, files=sorted(fs),
                 text_var_too=n[4:].lower() in constraint_keys) for n, fs in sorted(seen.items())]


def inventory():
    reg = registry_knobs()
    internal = set().union(*(__import__(m, fromlist=["DEFAULTS"]).DEFAULTS for m in INTERNAL))
    known = {k["name"] for k in reg} | {"modules"} | internal
    loose = unregistered_keys(known)
    cons = {k["name"] for k in reg if k["registry"].endswith("constraints.DEFAULTS")}
    inv = dict(schema="kae.commander-knobs/1", set=reg,
               unregistered=[dict(name=k, surface="set-unregistered", files=v) for k, v in loose.items()],
               cli=cli_knobs(), env=env_knobs(cons))
    names = {k["name"] for sec in ("set", "unregistered", "cli", "env") for k in inv[sec]}
    rows, missing = [], []
    for dec, ks, scope, effect, scorer in LOOPBACK:
        missing += [k for k in ks if k not in names]
        rows.append(dict(decision=dec, knobs=ks, scope=scope, effect=effect, scorer=scorer))
    if missing:
        raise SystemExit(f"LOOPBACK names knobs the code no longer has: {', '.join(missing)}")
    inv["loopback"] = rows
    return inv


def _cell(v):
    return str(v).replace("|", "/").replace("\n", " ")


def _short(note, n=70):
    note = _cell(note)
    return note if len(note) <= n else note[:n - 1].rsplit(" ", 1)[0] + " ..."


def render(inv):
    sets, cli, env, loose = inv["set"], inv["cli"], inv["env"], inv["unregistered"]
    by_reg = {}
    for k in sets:
        by_reg.setdefault(k["registry"], []).append(k)
    L = ["# Commander knobs (generated)", "",
         "Scope: every knob a commander can turn today, introspected from the code, and the expert loop-back "
         "decisions they serve. Generated by `tools/research/commander/knobs.py` (machine-readable copy: "
         "`tools/research/commander/knobs.json`); do not edit by hand, re-run it. The menu that ranks these "
         "knobs: `kae.commander.menu` (doc `loopback-menu.md`, branch `d7-loopback-menu`).",
         "Keys: knob inventory, --set keys, KAE_ text variables, KAE_ environment variables, loop-back "
         "decisions, commander knobs, unregistered option keys", "",
         "## Counts", "", "| Surface | Count |", "|---|---|"]
    for reg, ks in by_reg.items():
        L.append(f"| `--set` `{reg}` | {len(ks)} |")
    L += [f"| `--set` keys read but in no registry | {len(loose)} |",
          f"| text variables `KAE_<NAME>` (constraints keys) | {sum(1 for k in sets if k['text_var'])} |",
          f"| environment variables `KAE_*` read | {len(env)} |"]
    for c, _ in CLIS:
        L.append(f"| flags of `{c}` | {sum(1 for k in cli if k['cli'].split()[0] == c)} |")
    L += ["", "Traps: `kae.route.cli --set` does not validate keys (a typo is ignored); `kae.joint.cli` does, and "
          "spells bridge keys `bridge.<key>`; a project's `KAE_<NAME>` text variable beats `--set` for the "
          "constraints keys; `kae place` has no `--set`.", "",
          "## Loop-back decisions", "", "| Decision | Knob today | Scope | Effect | Scorer allows |", "|---|---|---|---|---|"]
    for r in inv["loopback"]:
        ks = ", ".join(f"`{k}`" for k in r["knobs"]) or "none"
        L.append(f"| {r['decision']} | {ks} | {r['scope']} | {r['effect']} | {r['scorer']} |")
    L += ["", "## `--set` keys", "", "Route: constraints and bridge keys (`kae.route.cli --set k=v`). Joint: all four "
          "registries (`kae.joint.cli --set`, bridge keys as `bridge.k`).", ""]
    for reg, ks in by_reg.items():
        L += [f"### {reg}", "", "| Key | Default | Note |", "|---|---|---|"]
        for k in ks:
            d = "" if k["default"] is None else f"`{_cell(k['default'])}`"
            L.append(f"| `{k['name']}` | {d} | {_short(k['note'])} |")
        L.append("")
    L += ["### Read but in no registry", "",
          "Found by pattern (`o.get(\"k\")`, `opts[\"k\"]`) in kae/src/kae/route and joint, minus every registry "
          "and the stage-internal DEFAULTS; some are other dicts that happen to be called `o`. Joint rejects "
          "them as `--set` keys; route passes them through unchecked.", ""]
    L.append(", ".join(f"`{k['name']}`" for k in loose) or "none")
    L += ["", "## Environment variables", "",
          "Variables marked * are also a constraints key (text variable and `--set` win over them).", ""]
    L.append(", ".join(f"`{k['var']}`{'*' if k['text_var_too'] else ''}" for k in env))
    L += ["", "## CLI flags", ""]
    groups = {}
    for k in cli:
        groups.setdefault(k["cli"], []).append(k["flag"])
    for g, fl in groups.items():
        L.append(f"- `{g}`: " + ", ".join(f"`{f}`" for f in fl))
    return "\n".join(L) + "\n"


def outputs():
    inv = inventory()
    return render(inv), json.dumps(inv, indent=1, sort_keys=True, default=str) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the doc or knobs.json is stale")
    a = ap.parse_args(argv)
    doc, js = outputs()
    if a.check:
        stale = [p for p, t in ((DOC, doc), (JSON, js)) if not p.exists() or p.read_text(encoding="utf-8") != t]
        if stale:
            print("stale, re-run tools/research/commander/knobs.py: " + ", ".join(_rel(p) for p in stale))
            return 1
        return 0
    DOC.write_text(doc, encoding="utf-8")
    JSON.write_text(js, encoding="utf-8")
    print(f"{_rel(DOC)}: {len(doc.split())} words; {_rel(JSON)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
