#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamres: a results store for routing and placement methods, keyed by board.

Three kinds of record, each identified by a hash of what defines it:
- method: a runnable recipe (code commits, binary hash, adapter or command, parameters, KiCad
  version) with a human-readable name. Same recipe, same id; any change, a new id.
- run: one method on one board (output board, logs, CPU, router report), under the board.
- evaluation: one scorer on one run (haslambench DRC score, haslam routed physics). A scorer is
  identified by the code it runs, so runs can be rescored without being re-run.
Experiments are views: a set of methods over a set of boards, with reports. A run that already
exists for a method on a board is reused by every later experiment.

  haslamres method add NAME --adapter freerouting --binary DIR/bin/freerouting --code router=SRC_OR_URL@REF [...]
  haslamres method add human --reference
  haslamres method list | show ID
  haslamres exp create NAME --method NAME_OR_ID [...] [--boards @FILE] [--harness REF] [--haslam REF] [--tier TIER]
  haslamres exp submit NAME [--limit N] [--only ids|@FILE]    # queue one haslamq job per board that lacks runs
  haslamres exp status NAME | report NAME | install-timer NAME
  haslamres sprint NAME --base bridge|staged --commit REF [--set K=V] [--arm N:K=V,...] [--suite S]   # arms vs the tag's stored control
  haslamres board ID                                          # every run and score of one board
  haslamres rerun RUN_DIR [--submit]                          # how to reproduce a run (or queue it again)
  haslamres index                                             # index.sqlite over every run and evaluation

Store (default ~/haslam-baselines, $HASLAM_RESULTS): see tools/haslamres/README.md for the layout.
"""
import argparse
import csv
import glob
import gzip
import hashlib
import json
import math
import os
import re
import resource
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = Path(os.path.expanduser(os.environ.get("HASLAM_RESULTS", "~/haslam-baselines")))
HASLAM_HOME = Path(os.path.expanduser(os.environ.get("HASLAM_HOME", "~/.cache/haslambench")))
CORPUS = Path(os.path.expanduser(os.environ.get("HASLAM_CORPUS", "~/haslam-boards")))
MB = 1 << 20
CHUNKS_MIN, CHUNKS_MAX = 2, 5  # jobs per board in `exp submit` (see cmd_exp_submit)
AS_LIMIT = 40 * (1 << 30)  # address-space cap for the harness tree (a runaway KiCad DRC once reached 100 GB)
SCHEMA = "haslamres/1"
HARNESS_REPO = "HaslamPCB"
# Files whose content defines haslambench's scoring (the DRC evaluator's identity)
SCORER_PATHS = ("bench/src/haslambench/score.py", "bench/src/haslambench/tools.py", "bench/src/haslambench/boardfiles.py",
                "bench/src/haslambench/kicad_scripts")


# ------------------------------------------------------------------ small helpers
def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ident(recipe):
    """12-hex id of a canonical JSON recipe."""
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "method"


def sh(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, text=True, capture_output=True, **kw).stdout.strip()


def git(repo, *args):
    return sh(["git", "-C", repo, *args])


def on_remote(repo, commit):
    """Whether anyone can fetch `commit`: a remote branch contains it, or a tag pushed to origin does
    (finished branches are kept as archive/* tags, and their commits stay linkable)."""
    if git(repo, "branch", "-r", "--contains", commit):
        return True
    tags = set(git(repo, "tag", "--contains", commit).split())
    if not tags:
        return False
    try:
        remote = {l.split("refs/tags/", 1)[1] for l in git(repo, "ls-remote", "--tags", "origin").splitlines()
                  if "refs/tags/" in l and not l.endswith("^{}")}
    except subprocess.CalledProcessError:
        return False
    return bool(tags & remote)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def gz(src, dst):
    with open(src, "rb") as fi, gzip.open(dst, "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)


def tail(path, n=40):
    try:
        return "\n".join(Path(path).read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def github_link(url, commit=None, ref=None):
    u = re.sub(r"\.git$", "", url or "")
    if not u.startswith("https://github.com/"):
        return None
    return f"{u}/commit/{commit}" if commit else f"{u}/tree/{ref}"


def env_sh():
    """HASLAM_* settings from the haslambench setup's env.sh (HASLAM_KICAD_WRAP: KiCad in its container)."""
    out = {}
    p = HASLAM_HOME / "env.sh"
    if p.exists():
        for line in p.read_text().splitlines():
            m = re.match(r'export (\w+)="?(.*?)"?$', line.strip())
            if m:
                out[m.group(1)] = m.group(2)
    return out


_KICAD_VERSION = []


def kicad_version():
    """KiCad's version string (kicad-cli version), asked once per process."""
    if not _KICAD_VERSION:
        _KICAD_VERSION.append(_kicad_version())
    return _KICAD_VERSION[0]


def _kicad_version():
    wrap = (os.environ.get("HASLAM_KICAD_WRAP") or env_sh().get("HASLAM_KICAD_WRAP", "")).split()
    try:
        return sh([*wrap, "kicad-cli", "version"]).splitlines()[-1].strip()
    except (subprocess.CalledProcessError, OSError, IndexError):
        return None


def main_repo():
    """The harness repo (where worktrees of frozen code are made)."""
    cfg = read_json(STORE / "config.json", {})
    if cfg.get("repo"):
        return cfg["repo"]
    repo = git(HERE, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(repo).parent)


# ------------------------------------------------------------------ code components
def resolve_code(spec, allow_dirty=False):
    """NAME=LOCAL_REPO[@REF] or NAME=URL@REF -> (name, component dict). A local repo must be at a
    commit some remote branch contains (pushed), unless allow_dirty: then uncommitted changes are
    frozen as a snapshot commit and saved as a patch."""
    name, _, src = spec.partition("=")
    if not name or not src:
        raise SystemExit(f"--code {spec!r}: use NAME=PATH[@REF] or NAME=URL@REF")
    if re.match(r"https?://", src):
        url, _, ref = src.rpartition("@") if "@" in src.split("//", 1)[1] else (src, "", "HEAD")
        refs = dict(reversed(l.split("\t")) for l in sh(["git", "ls-remote", url]).splitlines() if "\t" in l)
        commit = next((refs[k] for k in (f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}", f"refs/heads/{ref}", ref) if k in refs), None)
        if commit is None and re.fullmatch(r"[0-9a-f]{40}", ref):
            commit = ref
        if commit is None:
            raise SystemExit(f"{url}: ref {ref!r} not found")
        return name, dict(repo=url, ref=ref, commit=commit, link=github_link(url, commit))
    path, _, ref = src.partition("@")
    path = os.path.abspath(os.path.expanduser(path))
    top = git(path, "rev-parse", "--show-toplevel")
    commit = git(top, "rev-parse", ref or "HEAD")
    url = None
    try:
        url = git(top, "remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        pass
    url = re.sub(r"^git@github\.com:", "https://github.com/", url or "")
    comp = dict(repo=url or top, commit=commit, link=github_link(url, commit))
    pushed = on_remote(top, commit)
    dirty = not ref and bool(git(top, "status", "--porcelain", "--untracked-files=no"))
    if (dirty or not pushed) and not allow_dirty:
        why = "has uncommitted changes" if dirty else f"is at {commit[:7]}, which no remote branch or pushed tag contains"
        raise SystemExit(f"{name}: {top} {why}. Push it (so the method links to code anyone can fetch), "
                         "or pass --allow-dirty to freeze it as a local snapshot with a saved patch.")
    if dirty:
        snap = _snapshot(top)
        comp.update(commit=snap, base_commit=commit, dirty=True, link=None,
                    patch=git(top, "diff", commit, snap))
    elif not pushed:
        comp.update(unpushed=True, link=None)
    return name, comp


def _snapshot(top):
    idx = os.path.join(git(top, "rev-parse", "--absolute-git-dir"), f"haslamres-index-{os.getpid()}")
    env = dict(os.environ, GIT_INDEX_FILE=idx)
    try:
        subprocess.run(["git", "-C", top, "read-tree", "HEAD"], check=True, env=env)
        subprocess.run(["git", "-C", top, "add", "-u"], check=True, env=env)
        tree = subprocess.run(["git", "-C", top, "write-tree"], check=True, env=env, capture_output=True, text=True).stdout.strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)
    sha = git(top, "commit-tree", tree, "-p", "HEAD", "-m", "haslamres snapshot")
    git(top, "update-ref", f"refs/haslamres/{sha}", sha)
    return sha


def code_dir(commit):
    return STORE / "code" / f"{HARNESS_REPO}@{commit[:12]}"


def ensure_harness(commit, haslam=False, venv=True):
    """A frozen worktree of the harness repo at commit, with its venv (haslambench, or haslam for physics)."""
    d = code_dir(commit)
    venv_d = d.with_name(d.name + (".venv-haslam" if haslam else ".venv"))
    repo = main_repo()
    if not d.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "-C", repo, "worktree", "add", "--detach", str(d), commit])
    venv, want = venv_d, venv
    if want and not (venv / "bin" / "python").exists():
        uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
        subprocess.run([uv, "venv", "-q", "--python", "3.12", str(venv)], check=True)
        pkg = f"{d / 'haslam'}[fast]" if haslam else str(d / "bench")
        subprocess.run([uv, "pip", "install", "-q", "-p", str(venv / "bin" / "python"), "-e", pkg], check=True)
    return d, venv


def command_template(m, tpl=None):
    """A --command method's template with {code:NAME} (frozen checkout), {venv:NAME} and {py:NAME} (the
    haslam venv of that checkout, and its python) filled in, and the paths its sandbox must be able to read."""
    tpl, ro = tpl or m["recipe"]["runner"]["template"], []
    for name, comp in m["code"].items():
        d = code_dir(comp["commit"])
        kv = d.with_name(d.name + ".venv-haslam")
        if "{code:" + name + "}" in tpl:
            tpl, ro = tpl.replace("{code:" + name + "}", str(d)), ro + [d]
        for key, val in (("py", kv / "bin" / "python"), ("venv", kv)):
            if "{" + key + ":" + name + "}" in tpl:
                tpl, ro = tpl.replace("{" + key + ":" + name + "}", str(val)), ro + [d, kv]
    return tpl, list(dict.fromkeys(ro))


def ensure_method_code(m):
    """Frozen checkouts (and haslam venvs where the template asks for one) of a --command method's code."""
    if m["recipe"]["runner"]["type"] != "command":
        return
    tpl = m["recipe"]["runner"]["template"]
    for name, comp in m["code"].items():
        venv = "{py:" + name + "}" in tpl or "{venv:" + name + "}" in tpl
        if name != "harness" and (venv or "{code:" + name + "}" in tpl):
            ensure_harness(comp["commit"], haslam=venv, venv=venv)


def tree_ids(commit, paths):
    repo = main_repo()
    return {p: git(repo, "rev-parse", f"{commit}:{p}") for p in paths}


# ------------------------------------------------------------------ methods
def methods():
    return {p.stem: json.loads(p.read_text()) for p in sorted((STORE / "methods").glob("*.json"))}


def find_method(key):
    ms = methods()
    if key in ms:
        return ms[key]
    hits = [m for m in ms.values() if m["id"].startswith(key) or m["name"] == key or m["slug"] == key]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no method {key!r} (haslamres method list)")
    raise SystemExit(f"{key!r} names {len(hits)} methods ({', '.join(m['id'] for m in hits)}): use an id")


def cmd_method_add(a):
    comps = dict(resolve_code(s, a.allow_dirty) for s in a.code or [])
    harness = a.harness or "HEAD"
    if not a.reference:
        comps.setdefault("harness", resolve_code(f"harness={main_repo()}@{harness}" if harness != "HEAD"
                                                 else f"harness={main_repo()}", a.allow_dirty)[1])
    kicad = kicad_version()
    params = dict(kv.split("=", 1) for kv in a.param or [])
    if a.reference:
        runner = dict(type="reference")
        kind, params = "route", {}
    elif a.command:
        runner = dict(type="command", template=a.command)
        kind = a.kind
    else:
        if not a.binary:
            raise SystemExit("--binary is required for an adapter method")
        binary = Path(os.path.abspath(os.path.expanduser(a.binary)))
        root = binary.parent.parent if binary.parent.name == "bin" else binary.parent
        jar = next(iter(sorted(root.glob("lib/**/*.jar"))), None) or (binary if binary.suffix == ".jar" else None)
        runner = dict(type="haslambench-adapter", adapter=a.adapter,
                      binary_sha256=sha256_file(jar if jar else binary), binary_file=(jar or binary).name)
        kind = a.kind
        params.setdefault("timeout_s", str(a.timeout))
        params.setdefault("java_heap", "auto-v1")  # -Xmx from board size (see heap_gb)
        params.setdefault("java_processors", "2")
    recipe = dict(kind=kind, runner=runner, params=params, environment=dict(kicad=kicad, kicad_threads=a.kicad_threads),
                  code={k: {kk: vv for kk, vv in v.items() if kk in ("repo", "commit")} for k, v in comps.items()})
    mid = ident(recipe)
    path = STORE / "methods" / f"{mid}.json"
    if path.exists():
        m = read_json(path)
        print(f"already registered: {mid} {m['name']!r}")
        return mid
    m = dict(schema=SCHEMA, id=mid, name=a.name, slug=slugify(a.name), description=a.description or "",
             created=now(), recipe=recipe, code=comps, build=a.build)
    if runner["type"] == "haslambench-adapter":  # keep a copy of the exact binary, so the method can run again later
        dest = STORE / "bins" / f"{slugify(a.name)}-{runner['binary_sha256'][:8]}"
        if not dest.exists():
            tmp = dest.with_name(dest.name + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            if root == binary.parent and binary.suffix == ".jar":
                tmp.mkdir(parents=True)
                shutil.copy2(binary, tmp / binary.name)
            else:
                shutil.copytree(root, tmp, symlinks=True)
            os.replace(tmp, dest)
        bare_jar = root == binary.parent and binary.suffix == ".jar"
        m["binary"] = str(dest / (binary.name if bare_jar else binary.relative_to(root)))
        m["binary_source"] = str(binary)
        try:
            out = subprocess.run([m["binary"], "--help"], capture_output=True, text=True, timeout=120).stdout
            v = re.search(r"Freerouting v\S+", out)
            m["version"] = v.group(0) if v else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    for c in comps.values():
        if c.get("patch"):
            (STORE / "methods" / f"{mid}.{c['commit'][:12]}.patch").write_text(c.pop("patch"))
    write_json(path, m)
    print(f"registered {mid} {a.name!r}")
    print(json.dumps(m, indent=1))
    return mid


def cmd_method_list(a):
    for m in methods().values():
        code = ", ".join(f"{k}@{v['commit'][:7]}" for k, v in m["code"].items())
        print(f"{m['id']}  {m['name']:<28} {m['recipe']['kind']:<6} {m['recipe']['runner']['type']:<16} {code}  {m.get('version') or ''}")


def cmd_method_show(a):
    print(json.dumps(find_method(a.id), indent=1))


# ------------------------------------------------------------------ evaluators
DRC_REPORTS = (("drc.json", "drc"), ("placement/drc.json", "placement-drc"), ("routing/drc.json", "routing-drc"))


def keep_drc_reports(score_dir, evals_dir, eid):
    """The scorer's DRC reports of an attempt, gzipped beside its evaluation: <eid>.drc.json.gz (route and place
    tasks), <eid>.placement-drc.json.gz and <eid>.routing-drc.json.gz (joint tasks score the placement and the
    routing apart). With them a later scorer can re-judge the run without KiCad. Never overwrites."""
    kept = []
    for rel, tag in DRC_REPORTS:
        src, dst = Path(score_dir) / rel, Path(evals_dir) / f"{eid}.{tag}.json.gz"
        if src.exists() and not dst.exists():
            gz(src, dst)
            kept.append(dst.name)
    return kept


def evaluators_for(harness, haslam, kicad):
    """The DRC scorer and routed-physics evaluator a job at these commits applies, registered."""
    drc = dict(type="haslambench-drc", kicad=kicad, code=tree_ids(harness, SCORER_PATHS))
    phys = dict(type="haslam-physics", kicad=kicad, measure="board_physics fills=kicad fidelity=fast, physics_total (cap 5, missing 3)",
                code=dict(haslam=tree_ids(haslam, ["haslam/src"])["haslam/src"], script=tree_ids(harness, ["tools/haslamres/physics_board.py"])["tools/haslamres/physics_board.py"]))
    out = {}
    for key, recipe, commits in (("drc", drc, dict(harness=harness)), ("physics", phys, dict(haslam=haslam, harness=harness))):
        eid = ident(recipe)
        p = STORE / "evaluators" / f"{eid}.json"
        if not p.exists():
            write_json(p, dict(schema=SCHEMA, id=eid, name=key, recipe=recipe, created=now(),
                               commits={k: dict(commit=v, link=github_link("https://github.com/magnetic-trowel/HaslamPCB", v))
                                        for k, v in commits.items()}))
        out[key] = eid
    return out


# ------------------------------------------------------------------ boards and runs on disk
def board_dir(bid):
    return STORE / "boards" / bid


def run_name(m, attempt, suffix=""):
    return f"{m['slug']}.{m['id'][:8]}.a{attempt}{suffix}"


def board_runs(bid):
    """[(run dir, run.json)] of a board."""
    out = []
    for p in sorted((board_dir(bid) / "runs").glob("*/run.json")):
        r = read_json(p)
        if r:
            out.append((p.parent, r))
    return out


def find_run(bid, method_id, attempt=0, task_id=None):
    """The newest run of a method and attempt on a board, on task_id or a task of equal content (on_task)."""
    hits = [(d, r) for d, r in board_runs(bid) if r["method_id"] == method_id and r["attempt"] == attempt
            and (task_id is None or on_task(bid, r, task_id)) and not r.get("repro_of")]
    return hits[-1] if hits else (None, None)


# ------------------------------------------------------------------ task content and aliases
# A task id names a recipe (board file sha256, task spec, kind, KiCad), so a task spec bump gives every
# board a new task id although most boards' prepared inputs do not change. Each prepared task also gets
# a content hash: the files of its input and reference and the parts of task.json the scorer and the
# runner read. A run made on another task of the same board, kind and KiCad counts as made on this one
# when the task it ran on, as its own harness prepared it, has this task's content. Content is stored
# per harness commit in tasks/<id>/content.json: a task spec before 10 drew random uuids for boards
# whose files store none, so one task id could stand for several inputs, and only an input re-prepared
# by the run's own harness tells which (a random one never equals a later, seeded preparation).
CONTENT_VERSION = 1
# what the scorer and the runner read from task.json (score.py, runner.py), per input kind
_CONTENT_RECORD = ("pcb_sha256", "split", "has_project_rules")


def task_content(task, kind):
    """Content hash of a prepared task directory (haslambench's tasks/<board>) for one task kind; None when
    that kind's input is not there. Covers every file of reference/ and of the kind's input directory
    (drc.json reports, which carry a date, left out; their numbers are in the record), and the record's
    reference stats, pads outside the outline and the kind's task entry. Local paths (repo), the task
    spec and the round trip (a qualification verdict, not an input) are left out."""
    task = Path(task)
    ik = INPUT_KIND.get(kind, kind)
    rec = read_json(task / "task.json")
    if not rec or ik not in (rec.get("tasks") or {}) or not (task / ik).is_dir():
        return None
    ref = rec.get("reference") or {}
    keep = dict({k: rec.get(k) for k in _CONTENT_RECORD}, stats=ref.get("stats"), pads_outside=ref.get("pads_outside"),
                task=rec["tasks"][ik])
    files = []
    for top in ("reference", ik):
        for f in sorted((task / top).rglob("*")):
            if f.is_file() and f.name != "drc.json":
                files.append([str(f.relative_to(task)), sha256_file(f)])
    blob = json.dumps(dict(v=CONTENT_VERSION, kind=ik, record=keep, files=files), sort_keys=True, separators=(",", ":"))
    return f"v{CONTENT_VERSION}:" + hashlib.sha256(blob.encode()).hexdigest()


def task_meta(bid, tid):
    return read_json(board_dir(bid) / "tasks" / tid / "task.json")


def contents_of(bid, tid):
    """{harness commit: content hash} recorded for a stored task."""
    return read_json(board_dir(bid) / "tasks" / tid / "content.json", {}) or {}


def record_content(bid, tid, harness, content):
    p = board_dir(bid) / "tasks" / tid / "content.json"
    if content and p.parent.is_dir() and contents_of(bid, tid).get(harness) != content:
        write_json(p, dict(contents_of(bid, tid), **{harness: content}))


def run_prepared_by(r):
    """The harness commit that prepared the task a run ran on."""
    return r.get("task_prepared_by") or r.get("harness_commit")


def on_task(bid, r, tid):
    """Whether run r counts as a run on task tid: made on it, or on a task of the same board file, kind
    and KiCad whose content, as the run's harness prepared it, is a content recorded for tid."""
    if r.get("task_id") == tid:
        return True
    new, old = task_meta(bid, tid), task_meta(bid, r.get("task_id") or "")
    if not new or not old:
        return False
    a, b = new.get("recipe") or {}, old.get("recipe") or {}
    if any(a.get(k) != b.get(k) for k in ("board_sha256", "kind", "kicad")):
        return False
    mine = contents_of(bid, r["task_id"]).get(run_prepared_by(r) or "")
    return bool(mine) and mine in contents_of(bid, tid).values()


def evals_of(run_dir):
    return {p.stem: read_json(p) for p in sorted((Path(run_dir) / "evals").glob("*.json"))}


def corpus_rows():
    with open(CORPUS / "manifest.jsonl") as f:
        return {r["id"]: r for r in (json.loads(l) for l in f if l.strip())}


INPUT_KIND = {"joint": "place", "joint-fixed": "place-fixed"}  # task kind -> the input it runs on
PLACE_KINDS = ("place", "place-fixed")


def routed_board(kind, aj, adir):
    """The routed board of an attempt (haslambench attempt dir adir, attempt.json aj) that physics
    evaluates, None if there is none. Route tasks score score/board.kicad_pcb; joint tasks score the
    placement and the routing separately, the routed board is score/routing/board.kicad_pcb. A place
    task's score/board.kicad_pcb is the placement without copper (physics read every module as open
    or missing: 0xpolybit center-tap-rectifier 2 of 2 missing with its probe clean), so its routed
    board is the probe's, and a place run without a routed probe has none."""
    if aj.get("status") != "ok":
        return None
    if kind in PLACE_KINDS:
        sbs = (adir / "probe" / "score" / "board.kicad_pcb",) if (aj.get("probe") or {}).get("status") == "ok" else ()
    else:
        sbs = (adir / "score" / "board.kicad_pcb", adir / "score" / "routing" / "board.kicad_pcb")
    return next((sb for sb in sbs if sb.exists()), None)

LARGE_MB = 10  # board files above this are the slow, memory-heavy jobs


def spread_large(items, is_large, share=0.5):
    """Queue order: small items in their given order, large ones spaced evenly through the first
    `share` of the queue (not all first, which crowds memory; not last, which leaves a long tail)."""
    large = [x for x in items if is_large(x)]
    small = [x for x in items if not is_large(x)]
    if not large:
        return small
    span = max(len(large), int(round(share * (len(large) + len(small)))))
    slots = {int((i + 0.5) * span / len(large)) for i in range(len(large))}
    out, li, si = [], iter(large), iter(small)
    for pos in range(len(items)):
        nxt = next(li, None) if pos in slots else next(si, None)
        if nxt is None:  # one list ran out: the rest of the other
            nxt = next(si, None) if pos in slots else next(li, None)
        if nxt is not None:
            out.append(nxt)
    return out + list(li) + list(si)


def board_size_mb(row):
    p = CORPUS / row["path"] / "board.kicad_pcb"
    return p.stat().st_size / MB if p.exists() else 1.0


def heap_gb(size_mb):
    """java_heap=auto-v1: Freerouting -Xmx from the board file size."""
    return int(min(16, max(2, 2 + size_mb / 8)))


def method_timeout(m, row):
    """Seconds per attempt. With timeout_scale=sqrt-fp40, bigger boards get more: the base times
    sqrt(footprints / 40) when that is above 1, at most timeout_cap_s (default 4 h; a method whose
    own ceiling is longer, e.g. two counted-work phases at 4x their nominal budget, sets it)."""
    p = m["recipe"]["params"]
    t = int(p.get("timeout_s", 900))
    if p.get("timeout_scale") == "sqrt-fp40":
        cap = float(p.get("timeout_cap_s", 4 * 3600))
        t = int(min(cap, t * max(1.0, (row.get("footprints") or 0) / 40) ** 0.5))
    return t


def method_cpus(m):
    return int(m["recipe"]["params"].get("parallel", 1))


def estimate(row, ms):
    """Queue resources for one board's job (board files range from KB to 230 MB)."""
    s = board_size_mb(row)
    mem = 1.2 + 0.12 * s + 0.3 * heap_gb(s)  # GB, one step at a time; haslamq requeues an overrun with a corrected value
    t = sum(method_timeout(m, row) for m in ms)
    mem *= max([method_cpus(m) for m in ms] + [1])  # parallel restarts each hold a copy of the board
    return dict(size_mb=round(s, 2), mem=f"{mem:.1f}G", disk=f"{int(100 + 10 * s)}M",
                timeout=f"{int(min(JOB_TIMEOUT_MAX_S, t + job_overhead_s(s)))}s")


JOB_TIMEOUT_MAX_S = 24 * 3600   # haslamq's job timeout at most (a queued job holds its CPUs that long at worst)


def job_overhead_s(size_mb):
    """A job's wall time besides its methods' attempts on a board file of `size_mb` MB: preparing the
    board, scoring, physics."""
    return 3600 + 240 * size_mb


def plan_chunks(need, cost, overhead_s):
    """A board's (method, attempt) pairs as 2-5 jobs of about equal length (methods whole; more jobs
    for ~8 h of methods each, at most 5), so no single job runs every method back to back and the run
    has no long tail; each job prepares the board again, hence no more than 5. But never fewer jobs
    than it takes for each to fit JOB_TIMEOUT_MAX_S with its methods' timeouts (cost, seconds per
    method) and `overhead_s`: polarfire's three 39,000 s arms in one 24 h job (loop-win, 2026-11-17)
    ran into the job timeout and kept nothing. Longest first, to the least loaded."""
    k = max(1, min(len(need), CHUNKS_MAX, max(CHUNKS_MIN, math.ceil(sum(cost.values()) / (8 * 3600)))))
    room = JOB_TIMEOUT_MAX_S - overhead_s
    while k < len(need):
        chunks, load = _fill(need, cost, k)
        if max(load) <= room:
            return [ch for ch in chunks if ch]
        k += 1
    chunks, _ = _fill(need, cost, k)
    return [ch for ch in chunks if ch]


def _fill(need, cost, k):
    chunks, load = [[] for _ in range(k)], [0.0] * k
    for m, att in sorted(need, key=lambda x: -cost[x[0]]):
        i = load.index(min(load))
        chunks[i].append((m, att))
        load[i] += cost[m]
    return chunks, load


# ------------------------------------------------------------------ experiments
def exp_dir(name):
    return STORE / "experiments" / name


# environment an experiment may set for its jobs without changing any method's identity: settings
# that change no result (HASLAM_STEP_CACHE: haslam's step cache replays identical steps, time charged)
RESULT_NEUTRAL_ENV = ("HASLAM_STEP_CACHE",)


def exp_env(a):
    env = dict(kv.split("=", 1) for kv in a.env or [])
    bad = sorted(set(env) - set(RESULT_NEUTRAL_ENV))
    if bad:
        raise SystemExit(f"--env {bad}: only {RESULT_NEUTRAL_ENV} (settings that change no result) are allowed; "
                         "anything else belongs in the method's recipe")
    return env


def load_exp(name):
    e = read_json(exp_dir(name) / "experiment.json")
    if not e:
        raise SystemExit(f"no experiment {name!r}")
    return e


# Experiment tiers (docs/topics/verification/experiment-tiers.md): a sprint campaign is small and on cheap
# boards; the other tiers lift both limits and are recorded in experiment.json.
TIERS = {"sprint": dict(total_cpu_h=40.0, board_cpu_h=0.5), "ladder": None, "canary": None}


def control_costs(method_id, boards):
    """board -> mean CPU-h per run of one method on it, from its stored runs (run.json, not the index): the
    stored control's own single-attempt runs, the cost a sprint arm of the same base recipe is priced at.
    Boards without such a run are left out (the guard falls back to their history)."""
    out = {}
    for b in boards:
        if not board_dir(b).exists():
            continue
        cpu = [c for _, r in board_runs(b) if r["method_id"] == method_id and not r.get("repro_of")
               for c in [method_cpu_s(r)] if c]
        if cpu:
            out[b] = sum(cpu) / len(cpu) / 3600
    return out


def board_prices(boards, costs):
    """(known, hist, est): known = board -> CPU-h per method-run from `costs` (the control's own runs) or else
    its history in the index, for the boards that have either; hist and est as suites.history/estimator.
    None without an index and without costs."""
    import suites
    index = STORE / "index.sqlite"
    if index.exists():
        c = suites.open_index(index)
        hist = suites.history(c)
        est = suites.estimator(hist, dict(c.execute("SELECT id, footprints FROM boards")))
        c.close()
    elif costs:
        hist, est = {}, (lambda b: (0.0, False))
    else:
        return None
    return {b: costs.get(b, hist.get(b)) for b in boards if b in costs or b in hist}, hist, est


def tier_guard(tier, runs, what, costs=None, over_cap=None, arms=1):
    """Print the CPU-hours `what` is estimated to cost and exit unless it fits its tier. runs: board ->
    method-runs to make. A board costs `costs[board]` (CPU-h per method-run from the stored control's own
    runs, control_costs) when given; else its mean CPU-h per method-run in the index (suites.history); one
    with neither, the mean of its footprint band, and the per-board limit does not apply to it.
    over_cap: the reason the per-board limit is lifted (a board the question needs is over it); recorded by
    the caller. arms: treatment arms in the campaign; the total limit is per arm. Returns
    dict(cpu_h, over) for the record, or None without an index."""
    costs = costs or {}
    priced = board_prices(runs, costs)
    if priced is None:
        print(f"{what}: no {STORE / 'index.sqlite'}, so no CPU estimate and no check of tier {tier}; `haslamres index` builds it")
        return None
    known, hist, est = priced
    cost = lambda b: costs[b] if b in costs else est(b)[0]  # noqa: E731
    total = sum(cost(b) * n for b, n in runs.items())
    src = (f"{sum(b in costs for b in runs)} from the control's own runs, "
           f"{sum(b not in costs and b in hist for b in runs)} from board history, the others by size") if costs \
        else f"{sum(b in hist for b in runs)} with history, the others by size"
    print(f"{what}: estimated {total:.1f} CPU-h from board history ({sum(runs.values())} method-runs on {len(runs)} boards, "
          f"{src}); tier {tier}")
    lim = TIERS[tier]
    over = sorted((b for b, n in runs.items() if n and known.get(b, 0) > (lim or {}).get("board_cpu_h", math.inf)),
                  key=lambda b: (-known[b], b))
    rec = dict(cpu_h=round(total, 1), over={b: round(known[b], 2) for b in over})
    if not lim:
        return rec
    cap_total = lim["total_cpu_h"] * max(1, arms)
    if over and over_cap:
        print(f"{what}: the per-board limit of {lim['board_cpu_h']:g} CPU-h is lifted for {len(over)} boards "
              f"({', '.join(f'{b} {known[b]:.2f}' for b in over[:5])}{', ...' if len(over) > 5 else ''}): {over_cap}")
        over = []
    if total > cap_total or over:
        worst = f" and {len(over)} boards are over ({', '.join(f'{b} {known[b]:.1f}' for b in over[:3])}{', ...' if len(over) > 3 else ''})"
        per = f" ({lim['total_cpu_h']:g} per treatment arm, {arms} arms)" if arms > 1 else ""
        raise SystemExit(f"refused: tier {tier} allows {cap_total:g} CPU-h in all{per} and {lim['board_cpu_h']:g} CPU-h per "
                         f"method-run on a board; this is {total:.1f} CPU-h{worst if over else ''}.\n"
                         "Do this: run it on bench/suites/sprint-frontier.txt or sprint-quality.txt (--boards @FILE) with fewer "
                         "methods or attempts (haslamres sprint: --skip-over-cap leaves the boards over the limit out; "
                         "--allow-over-cap \"REASON\" keeps them when the question needs them, and the reason is recorded); "
                         "once it has passed sprint, add --tier ladder (--tier canary for the big boards).")
    return rec


def cmd_exp_create(a):
    d = exp_dir(a.name)
    if (d / "experiment.json").exists():
        raise SystemExit(f"experiment {a.name} exists")
    ms = [find_method(k) for k in a.method]
    repo = main_repo()
    harness = git(repo, "rev-parse", a.harness)
    haslam = git(repo, "rev-parse", a.haslam)
    for c in (harness, haslam):
        if not on_remote(repo, c):
            raise SystemExit(f"{c[:7]} is on no remote branch or pushed tag: push it first, so the experiment links to fetchable code")
    if a.boards:
        boards = Path(a.boards[1:]).read_text().split() if a.boards.startswith("@") else a.boards.split(",")
    else:
        boards = sorted(corpus_rows())
    print(f"freezing harness {harness[:7]} (prepare, human scoring, physics brief) and haslam {haslam[:7]} (physics)")
    ensure_harness(harness)
    ensure_harness(haslam, haslam=True)
    for m in ms:
        hc = (m["code"].get("harness") or {}).get("commit")
        if hc:
            ensure_harness(hc)
        ensure_method_code(m)
    # a method prepares its boards with its own harness: on another task spec its runs land on another
    # task and never count here (baseline-2611: freerouting 2.5.0 pinned to a spec-8 harness ran 552 s
    # per board and wrote no run)
    want = harness_task_spec(harness)
    # from task spec 10 on, such a method runs on the experiment's tasks (prep_harness)
    off = [(m["name"], m["id"], harness_task_spec(hc)) for m in ms
           for hc in [(m["code"].get("harness") or {}).get("commit")]
           if hc and harness_task_spec(hc) != want and prep_harness(hc, harness) != harness]
    if off:
        raise SystemExit(f"methods prepared with a harness of another task spec than {harness[:7]}'s ({want}): "
                         + "; ".join(f"{n} {i} (spec {s})" for n, i, s in off)
                         + ". Register them again with --harness at this experiment's harness.")
    todo = [(m["id"], k) for m in ms if m["recipe"]["runner"]["type"] != "reference" for k in range(a.attempts)]

    def have(b):  # with --reuse-runs, the stored runs (a stored control) are not made again
        return {(r["method_id"], r["attempt"]) for _, r in board_runs(b)} if a.reuse_runs and board_dir(b).exists() else ()
    # a sprint prices its boards from the stored control's own runs (cost_from) and may lift the per-board
    # limit for a stated reason (allow_over_cap); both are recorded, so exp submit applies the same guard
    cost_from, over_cap, arms = getattr(a, "cost_from", None), getattr(a, "allow_over_cap", None), getattr(a, "arms", None) or 1
    guard = tier_guard(a.tier, {b: len(set(todo) - set(have(b))) for b in boards}, f"experiment {a.name}",
                       costs=control_costs(cost_from, boards) if cost_from else None, over_cap=over_cap, arms=arms)
    # runs made at another time are not comparable: on this shared host the same code, seeds and time
    # budget left 13.9 % more open connections a few days later (zone-keepout-ab2 against zone-ab's base
    # runs, 47 boards, p < 0.001), more than the effects the A/Bs measure; so an experiment makes all of
    # its runs itself unless --reuse-runs says otherwise
    if not a.reuse_runs:
        old_runs = defaultdict(int)
        ids = {m["id"] for m in ms if m["recipe"]["runner"]["type"] != "reference"}
        for bid in boards:
            if board_dir(bid).exists():
                for _, r in board_runs(bid):
                    if r["method_id"] in ids and r.get("experiment") != a.name and not r.get("repro_of"):
                        old_runs[r["method_id"]] += 1
        if old_runs:
            raise SystemExit("methods with runs from other experiments on these boards: "
                             + "; ".join(f"{m['name']} {m['id']} ({old_runs[m['id']]} runs)" for m in ms if m["id"] in old_runs)
                             + ". Runs made at another time are not comparable (host load moves results by ~14 %): "
                             "register a replicate of each (method add ... --param replicate=<tag>, same recipe otherwise) "
                             "so every arm runs now, side by side; or pass --reuse-runs to compare with them anyway.")
    kicad = kicad_version()
    evs = evaluators_for(harness, haslam, kicad)
    e = dict(schema=SCHEMA, name=a.name, reuse_runs=bool(a.reuse_runs), description=a.description or "", created=now(),
             session=os.environ.get("HASLAMQ_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID"),  # who looks after it
             methods=[dict(id=m["id"], name=m["name"]) for m in ms], attempts=a.attempts, tier=a.tier,
             harness=dict(commit=harness, link=github_link("https://github.com/magnetic-trowel/HaslamPCB", harness)),
             haslam=dict(commit=haslam, link=github_link("https://github.com/magnetic-trowel/HaslamPCB", haslam)),
             kicad=kicad, evaluators=evs, corpus=str(CORPUS), corpus_manifest_sha256=sha256_file(CORPUS / "manifest.jsonl"),
             boards=len(boards), **({"env": exp_env(a)} if a.env else {}),
             **({"suite": a.suite} if getattr(a, "suite", None) else {}),
             **({"cost_from": cost_from} if cost_from else {}), **({"arms": arms} if arms > 1 else {}),
             **({"over_cap": dict(reason=over_cap, boards=(guard or {}).get("over", {}))} if over_cap else {}),
             **(getattr(a, "record", None) or {}))
    d.mkdir(parents=True, exist_ok=True)  # it may hold the experiment's PLAN.md already
    (d / "boards.txt").write_text("\n".join(boards) + "\n")
    write_json(d / "experiment.json", e)
    write_json(STORE / "config.json", dict(read_json(STORE / "config.json", {}), repo=repo))
    print(json.dumps(e, indent=1))


_TASK_SPECS, _BOARD_SHAS = {}, {}


def harness_task_spec(commit):
    """haslambench's TASK_SPEC at a frozen harness commit (None if its code is not here)."""
    if commit not in _TASK_SPECS:
        p = code_dir(commit) / "bench" / "src" / "haslambench" / "prepare.py"
        m = re.search(r"^TASK_SPEC = (\d+)", p.read_text(), re.M) if p.exists() else None
        _TASK_SPECS[commit] = int(m.group(1)) if m else None
    return _TASK_SPECS[commit]


def exp_task_id(e, bid, kind):
    """The id of the task an experiment's harness prepares for a board and task kind, as _job_group
    names it (the corpus board file's sha256, the harness's TASK_SPEC, the kind, KiCad); None when the
    harness code or the board is not here, and then any task matches (as before task ids were checked)."""
    spec = harness_task_spec(e["harness"]["commit"])
    if bid not in _BOARD_SHAS:
        row = corpus_rows().get(bid)
        p = CORPUS / row["path"] / "board.kicad_pcb" if row else None
        _BOARD_SHAS[bid] = sha256_file(p) if p and p.exists() else None
    if spec is None or _BOARD_SHAS[bid] is None:
        return None
    return ident(dict(board_sha256=_BOARD_SHAS[bid], task_spec=spec, kind=kind, kicad=e["kicad"]))


def missing(e, bid):
    """Methods of the experiment without a finished run on this board's task of the experiment (a run
    on an older board file, task spec or KiCad does not count: it is not comparable)."""
    out = []
    for a_ in range(e["attempts"]):
        for m in e["methods"]:
            d, r = find_run(bid, m["id"], a_, exp_task_id(e, bid, _run_kind(dict(method_id=m["id"]))))
            if d is None:
                out.append((m["id"], a_))
    return out


def prepare_failed(e, bid):
    return (board_dir(bid) / "prepare-failures" / f"{e['harness']['commit'][:12]}.json").exists()


def cmd_exp_submit(a):
    e = load_exp(a.name)
    rows = corpus_rows()
    boards = (exp_dir(a.name) / "boards.txt").read_text().split()
    if a.only:
        only = set(Path(a.only[1:]).read_text().split() if a.only.startswith("@") else a.only.split(","))
        boards = [b for b in boards if b in only]
    ms = {m["id"]: find_method(m["id"]) for m in e["methods"]}
    script = code_dir(e["harness"]["commit"]) / "tools" / "haslamres" / "haslamres.py"
    py = code_dir(e["harness"]["commit"]).with_name(code_dir(e["harness"]["commit"]).name + ".venv") / "bin" / "python"
    jobs, runs = [], {}
    boards.sort(key=lambda b: hashlib.sha1(b.encode()).hexdigest())  # sizes mixed over the run
    for bid in boards:
        if bid not in rows:
            continue
        need = missing(e, bid)
        if not need or (prepare_failed(e, bid) and not a.redo):
            continue
        runs[bid] = sum(ms[m]["recipe"]["runner"]["type"] != "reference" for m, _ in need)
        cost = {m: method_timeout(ms[m], rows[bid]) for m, _ in need}
        chunks = plan_chunks(need, cost, job_overhead_s(board_size_mb(rows[bid])))
        for i, ch in enumerate(chunks):
            est = estimate(rows[bid], [ms[m] for m, _ in ch])
            # each method with its attempt (ID@N): a job runs --attempt for bare ids, so a chunk
            # of later attempts would otherwise re-run attempt 0 (multi-attempt experiments ran
            # attempt 0 only)
            sel = "" if len(chunks) == 1 else "".join(f" --method {m}@{att}" for m, att in ch)
            jobs.append(dict(cmd=f"{py} {script} job --experiment {a.name} --board {bid}{sel}",
                             name=f"{a.name}:{bid}" + (f":{i}" if len(chunks) > 1 else ""),
                             cpus=max([2] + [method_cpus(ms[m]) for m, _ in ch]),
                             mem=est["mem"], disk=est["disk"], timeout=est["timeout"], size_mb=est["size_mb"],
                             **({} if getattr(a, "prio", None) is None else {"prio": a.prio})))
        if a.limit and len(jobs) >= a.limit:
            break
    tier = a.tier or e.get("tier") or "sprint"  # an experiment from before the tiers is a sprint until told otherwise
    tier_guard(tier, runs, f"submit {a.name}", costs=control_costs(e["cost_from"], runs) if e.get("cost_from") else None,
               over_cap=(e.get("over_cap") or {}).get("reason"), arms=e.get("arms", 1))
    if tier != e.get("tier") and not a.dry_run:
        e = dict(e, tier=tier)
        write_json(exp_dir(a.name) / "experiment.json", e)
    cap = cpu_cap_of(a, e, tier)
    if cap and not a.dry_run:
        import watchdog
        e = watchdog.record_cap(e, cap, "haslamres exp submit" + (" --cpu-cap" if getattr(a, "cpu_cap", None) else f" (tier {tier} limit)"))
        write_json(exp_dir(a.name) / "experiment.json", e)
    print(f"cost watchdog: cap {cap:g} CPU-h (haslamres exp report and haslamres exp watchdog {a.name} check it; over the cap, "
          "the campaign's queued jobs are cancelled)" if cap else
          "cost watchdog: no CPU cap (give --cpu-cap H to have the campaign's queued jobs cancelled past it)")
    jobs = spread_large(jobs, lambda j: j["size_mb"] > LARGE_MB)  # haslamq runs them in this order
    f = exp_dir(a.name) / f"jobs-{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    f.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    print(f"{len(jobs)} board jobs -> {f}")
    if jobs and not a.dry_run:
        # benchmark runs: methods' results depend on the time they get, so never paused (haslamq class timed)
        subprocess.run(["haslamq", "submit", "--jobs", str(f), "--owner", f"exp-{a.name}", "--tag", a.name, "--live",
                        "--class", "timed", "--cwd", str(code_dir(e["harness"]["commit"])), "--retries", "1"], check=True)


def cpu_cap_of(a, e, tier):
    """The campaign's CPU-h cap: --cpu-cap, else the one recorded before, else the tier's total limit per arm
    (sprint: 40 per treatment arm); None for a tier without a limit and no --cpu-cap."""
    if getattr(a, "cpu_cap", None):
        return float(a.cpu_cap)
    if (e.get("cpu_cap") or {}).get("cpu_h"):
        return float(e["cpu_cap"]["cpu_h"])
    lim = TIERS.get(tier)
    return lim["total_cpu_h"] * max(1, e.get("arms", 1)) if lim else None


def cmd_exp_watchdog(a):
    import watchdog
    watchdog.check(a.name, store=STORE, dry_run=a.dry_run)


# ------------------------------------------------------------------ sprint: one command for a sprint experiment
SPRINT_BASES = {"bridge": "route", "staged": "joint-fixed"}  # base -> the kind of the stored control's method
SPRINT_SUITES = ("sprint-frontier.txt", "sprint-quality.txt")
SUITES_DIR = HERE.parents[1] / "bench" / "suites"


def suite_file(name):
    """A suite by name: a file in bench/suites/ or bench/suites/mech/ ('sprint-quality', 'mech/bga', 'bga',
    with or without .txt)."""
    n = name if name.endswith(".txt") else f"{name}.txt"
    for p in (SUITES_DIR / n, SUITES_DIR / "mech" / n):
        if p.resolve().parent in (SUITES_DIR.resolve(), (SUITES_DIR / "mech").resolve()) and p.is_file():
            return p
    raise SystemExit(f"no suite {name!r}: a file in bench/suites/ or bench/suites/mech/ (ls {SUITES_DIR})")


def suite_boards(p):
    """Board ids of a suite file: the first word of each line, '#' comments left out, in file order."""
    out = []
    for ln in p.read_text().splitlines():
        w = ln.split("#", 1)[0].split()
        if w and w[0] not in out:
            out.append(w[0])
    return out


def parse_arm(spec):
    """'name:k=v,k=v' (or 'name:' for the commit alone) -> (name, ['k=v', ...])."""
    name, _, kvs = spec.partition(":")
    sets = [kv for kv in kvs.split(",") if kv]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not _ or any("=" not in kv for kv in sets):
        raise SystemExit(f"--arm {spec!r}: give NAME:KEY=VALUE[,KEY=VALUE...] (NAME: letters, digits, - _ .)")
    return name, sets


def sprint_control(c, base, method=None):
    """The stored control's method in control experiment `c`: `method` (an id or id prefix of one of its methods, e.g.
    the stored TraceMaker hybrid of hybrid-bga-w47, the BGA baseline), else its first method of the base's kind."""
    ms = [find_method(m["id"]) for m in c["methods"]]
    if method:
        hit = [m for m in ms if m["id"].startswith(method)]
        if len(hit) != 1:
            raise SystemExit(f"--control-method {method}: {len(hit)} of {c['name']}'s methods match "
                             f"({', '.join(m['id'] + ' ' + m['name'] for m in ms)})")
        if hit[0]["recipe"]["kind"] != SPRINT_BASES[base]:
            raise SystemExit(f"--control-method {method}: a {hit[0]['recipe']['kind']} method, not --base {base}'s {SPRINT_BASES[base]}")
        return hit[0]
    return next(m for m in ms if m["recipe"]["kind"] == SPRINT_BASES[base])


def cmd_sprint(a):
    """A sprint experiment in one command (bench/suites/README.md): each arm is the stored control's recipe
    of `--base` at `--commit` with its settings; they run on one suite (--suite; default the two sprint
    suites) with the control's seeds, against the control's stored runs (not run again), tier sprint, queue
    priority 5. Boards of the suite without a stored control run get the control run in the same campaign,
    stored like the control's own for later sprints. Cost and the per-board limit come from the control's
    own runs of the same base recipe."""
    d = exp_dir(a.name)
    if not (d / "PLAN.md").exists():
        raise SystemExit(f"refused: no {d / 'PLAN.md'} (the question, the one change, what will decide it).\n"
                         "Do this: write it, then run the same command again.")
    c = load_exp(a.control)
    ctl = sprint_control(c, a.base, getattr(a, "control_method", None))
    tag, repo = c["harness"]["commit"], main_repo()
    commit = git(repo, "rev-parse", f"{a.commit}^{{commit}}")
    common = list(a.set or [])
    arms = [parse_arm(s) for s in a.arm or []] or [(None, [])]
    if len({n for n, _ in arms}) < len(arms):
        raise SystemExit("--arm: two arms with one name")
    attempts = a.attempts or c["attempts"]
    if not 1 <= attempts <= c["attempts"]:
        raise SystemExit(f"--attempts {attempts}: the control {a.control} stores seeds 0-{c['attempts'] - 1}")
    extra = list(getattr(a, "param", None) or [])
    note = getattr(a, "note", None)
    if any("=" not in kv for kv in extra):
        raise SystemExit("--param: give K=V")
    # the arm's code goes under the name the control's template uses ({py:NAME}): a control stored before the
    # rename of PR #163 (control-w47) names it kae, a later one haslam
    cname = next((k for k in ctl.get("code") or {} if k != "harness"), "haslam")
    mids = []
    for arm, own in arms:
        sets = "".join(f" --set {kv}" for kv in common + own)
        if commit == tag and not sets:
            raise SystemExit(f"refused: at {tag[:7]} without --set the arm is the control itself.\n"
                             "Do this: give --commit (the tag plus one change, pushed) or --set KEY=VALUE.")
        label = f"{a.name}{'-' + arm if arm else ''}"
        # the control's recipe, with a numba cache of its own checkout (a cache serves only the code that made it)
        own = ((ctl.get("code") or {}).get("haslam") or {}).get("commit") or tag   # the control's haslam (a stored arm's: not the tag)
        template = ctl["recipe"]["runner"]["template"].replace(f"numba-default-{own[:7]}", f"numba-default-{commit[:7]}") + sets
        # --param: method parameters over the control's (e.g. parallel=8 for an arm whose router runs 8 threads,
        # so the queue reserves them); they are part of the arm's identity, not haslam settings
        params = dict(ctl["recipe"]["params"], **dict(kv.split("=", 1) for kv in extra))
        mids.append(cmd_method_add(argparse.Namespace(
            name=f"{label} {a.base} {commit[:7]}{sets}",
            description=f"sprint arm {arm or ''} of {a.name}: {ctl['name']!r} at {commit[:7]}{sets}"
                        + (f"; {note}" if note else ""),
            reference=False, adapter=None, binary=None, command=template, kind=ctl["recipe"]["kind"], code=[f"{cname}={repo}@{commit}"],
            harness=tag, param=[f"{k}={v}" for k, v in params.items()], timeout=900,
            kicad_threads=ctl["recipe"]["environment"]["kicad_threads"], build=None, allow_dirty=False)))
    if a.suite:
        files = [suite_file(a.suite)]
    else:
        files = [SUITES_DIR / f for f in SPRINT_SUITES]
    boards = list(dict.fromkeys(b for f in files for b in suite_boards(f)))
    suite = a.suite or "+".join(Path(f).stem for f in SPRINT_SUITES)
    cost = control_costs(ctl["id"], boards)
    record = dict(control=dict(experiment=a.control, method=ctl["id"], name=ctl["name"]))
    if a.skip_over_cap:
        cap = TIERS["sprint"]["board_cpu_h"]
        known = (board_prices(boards, cost) or ({},))[0]   # the guard's prices: the control's runs, else history
        skipped = {b: round(known[b], 2) for b in boards if known.get(b, 0) > cap}
        boards = [b for b in boards if b not in skipped]
        record["skipped_over_cap"] = skipped
        print(f"{a.name}: left out {len(skipped)} boards whose control runs (else history) cost over {cap:g} CPU-h: "
              + (", ".join(f"{b} {v}" for b, v in skipped.items()) or "none"))
    # boards of the suite the control has not run on, at the seeds used: the control runs there in this campaign
    stored = {b for b in boards if board_dir(b).exists()
              and {k for _, r in board_runs(b) if r["method_id"] == ctl["id"] and not r.get("repro_of")
                   for k in [r["attempt"]]} >= set(range(attempts))}
    fill = [b for b in boards if b not in stored]
    record["control_fill"] = fill
    if fill:
        print(f"{a.name}: {len(fill)} of {len(boards)} boards have no stored run of {ctl['name']!r} on seeds 0-{attempts - 1}: "
              "the control runs on them in this campaign, stored for reuse by later sprints")
    if a.allow_over_cap is not None and not a.allow_over_cap.strip():
        raise SystemExit("--allow-over-cap needs the reason (why the question needs the boards over the limit)")
    cmd_exp_create(argparse.Namespace(
        name=a.name, description=f"sprint on {suite}: {ctl['name']!r} against itself at {commit[:7]} ("
                                 + "; ".join(f"{n or 'arm'}:{','.join(common + s)}" for n, s in arms)
                                 + f"); control runs of {a.control} reused",
        method=[ctl["id"], *mids], boards=",".join(boards), attempts=attempts, harness=tag, haslam=tag, env=None,
        reuse_runs=True, tier="sprint", suite=suite, cost_from=ctl["id"], allow_over_cap=a.allow_over_cap,
        arms=len(mids), record=dict(record, arm_methods={(n or "arm"): mid for (n, _), mid in zip(arms, mids)})))
    if fill and not a.dry_run:
        f = exp_dir(a.control) / "control-fill.jsonl"   # who added runs to the stored control, where
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a") as fh:
            fh.write(json.dumps(dict(experiment=a.name, method=ctl["id"], attempts=attempts, boards=fill, when=now())) + "\n")
    only = None
    if a.smoke:
        # the cheapest boards first, one of them needing the control's run if any does, so both paths are tried
        rank = sorted(boards, key=lambda b: (cost.get(b, math.inf), b))
        pick = ([b for b in rank if b in fill][:1] if fill else []) + [b for b in rank if b not in fill]
        only = ",".join(pick[:a.smoke])
        print(f"smoke: {only}")
    cmd_exp_submit(argparse.Namespace(name=a.name, only=only, limit=None, redo=False, dry_run=a.dry_run, tier=None, prio=5,
                                      cpu_cap=getattr(a, "cpu_cap", None)))
    if a.smoke:
        print(f"after the smoke, the rest: haslamres exp submit {a.name} --prio 5")
    print(f"verdict, once the jobs are done:\n  haslamres exp report {a.name} && haslamres quality {a.name} --control '{ctl['name']}'")


# ------------------------------------------------------------------ the per-board job
class Step:
    """Wall and CPU time (children's rusage) of one subprocess step."""

    def __init__(self, name, steps):
        self.name, self.steps = name, steps

    def __enter__(self):
        self.t0, self.r0 = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
        self.c0 = cgroup_cpu_s()
        return self

    def __exit__(self, *exc):
        r = resource.getrusage(resource.RUSAGE_CHILDREN)
        c1 = cgroup_cpu_s()
        self.steps[self.name] = dict(wall_s=round(time.monotonic() - self.t0, 2),
                                     cpu_s=round(r.ru_utime + r.ru_stime - self.r0.ru_utime - self.r0.ru_stime, 2),
                                     **({"cgroup_cpu_s": round(c1 - self.c0, 2)} if None not in (c1, self.c0) else {}))


def cgroup_cpu_s():
    """CPU seconds used so far by this process's cgroup v2 (usage_usec of cpu.stat), None when it
    cannot be read. A haslamq job has a scope of its own and runs its steps one after another, so a
    step's difference is its CPU, including processes rusage never sees: bwrap exits without
    reaping its sandbox's pid 1, which made every sandboxed method read ~0 CPU before the
    haslambench launcher became a subreaper."""
    try:
        rel = Path("/proc/self/cgroup").read_text().strip().splitlines()[-1].split("::", 1)[1]
        for line in (Path("/sys/fs/cgroup") / rel.lstrip("/") / "cpu.stat").read_text().splitlines():
            k, v = line.split()
            if k == "usage_usec":
                return int(v) / 1e6
    except (OSError, IndexError, ValueError):
        pass
    return None


def method_cpu_s(r):
    """The method's CPU seconds of a run record: its own report (restart.py's work.cpu_s), else
    haslambench's rusage, which is None for a sandboxed method whose rusage was lost (bwrap; under
    1 % of a core over its wall time with a single process accounted), else the haslamq job
    step's cgroup difference when that was recorded (an upper bound: it includes the scoring
    that haslambench runs in the same step)."""
    w = (r.get("work") or {}).get("cpu_s")
    if w:
        return w
    mu = r.get("method_usage") or {}
    cpu, wall = mu.get("cpu_s"), r.get("runtime_s") or 0
    lost = (cpu is not None and (r.get("adapter_meta") or {}).get("sandboxed") and mu.get("processes", 1) <= 1
            and wall > 30 and cpu < 0.01 * wall)
    if cpu is not None and not lost:
        return cpu
    return ((r.get("job_steps") or {}).get("run") or {}).get("cgroup_cpu_s")


def _limit_as():
    try:
        resource.setrlimit(resource.RLIMIT_AS, (AS_LIMIT, AS_LIMIT))
    except (ValueError, OSError):
        pass


def deadline_env(env=None, timeout=None):
    """(env, timeout) under this job's HASLAM_DEADLINE (epoch s; haslamq sets it): the timeout no later than it,
    and the child's HASLAM_DEADLINE that timeout from now less 10 % (at most 30 s). The same contract as
    haslambench.deadline and haslam.proc: no inner layer outlives an outer one."""
    env = dict(os.environ if env is None else env)
    d = os.environ.get("HASLAM_DEADLINE")
    if d:
        left = max(1.0, float(d) - time.time())
        timeout = left if timeout is None else min(float(timeout), left)
    if timeout is not None:
        env["HASLAM_DEADLINE"] = f"{time.time() + timeout - min(30.0, 0.1 * timeout):.0f}"
    return env, timeout


# A job being killed (haslamq: --timeout, cancel, memory; SIGTERM, then SIGKILL after its kill_grace_s): STOP holds why
# and when. The running step gets the SIGTERM too (it runs in a session of its own) and CHILD_GRACE_S to save what it
# has; then every method's attempts so far go to the store as incomplete runs (_store_incomplete).
STOP = {}
CHILD = set()            # process groups of running steps (run_logged)
CHILD_GRACE_S = 75.0     # within haslamq's kill_grace_s (120 s), leaving time to store what was saved
INCOMPLETE_MB = 20       # what a killed job keeps per board in the store (restart.py's FR_RAW_LIMIT, the same size)
# lines of a step's output that also go to the job's own log as they come: haslambench's attempts, restart.py's progress
PROGRESS_RE = re.compile(rb"^(\[(start|\d+/\d+)\] |\[restart |haslambench: SIGTERM|stopped )")


def _stop_reason():
    try:
        return (Path(os.environ["HASLAMQ_SCRATCH"]) / ".haslamq-stop").read_text().strip() or "signal"
    except (KeyError, OSError):
        return "signal"


def _on_sigterm(*_):
    # no locks in here: the job gets SIGTERM more than once (haslamq signals every process, and the haslamq wrapper's group)
    if STOP:
        return
    STOP["at"] = time.monotonic()
    STOP.update(reason=_stop_reason(), when=now())
    os.write(1, f"haslamres: SIGTERM ({STOP['reason']}): stopping; each method's attempts so far are stored "
                f"as incomplete runs\n".encode())
    for g in list(CHILD):
        try:
            os.killpg(g, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def run_logged(cmd, log, env, timeout):
    """Run cmd with output appended to log, and its progress lines (PROGRESS_RE) also printed as they come, so the
    haslamq job's log says which method and attempt ran even after a SIGKILL; returns (rc, timed_out). In a job being
    stopped (STOP) the step is killed CHILD_GRACE_S after the SIGTERM. The timeout is no later than this job's
    HASLAM_DEADLINE, which the command inherits less a margin (deadline_env)."""
    env, timeout = deadline_env(env, timeout)
    with open(log, "ab") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n".encode())
        f.flush()
        p = subprocess.Popen([str(x) for x in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                             preexec_fn=_limit_as, start_new_session=True)
        CHILD.add(p.pid)

        def pump():
            for line in p.stdout:
                f.write(line)
                f.flush()
                if PROGRESS_RE.match(line):
                    sys.stdout.write(line.decode(errors="replace"))
                    sys.stdout.flush()
        t = threading.Thread(target=pump, daemon=True)
        t.start()
        end, rc, to = time.monotonic() + timeout, None, False
        try:
            while rc is None:
                try:
                    rc = p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if time.monotonic() > end or (STOP and time.monotonic() > STOP["at"] + CHILD_GRACE_S):
                        os.killpg(p.pid, signal.SIGKILL)
                        p.wait()
                        to = True
                        break
        finally:
            CHILD.discard(p.pid)
        t.join(timeout=10)
        return (None, True) if to else (rc, False)


class Bugs:
    def __init__(self, bid):
        self.bid, self.items = bid, []

    def add(self, who, category, detail, signature=None, evidence=(), **extra):
        self.items.append(dict(board=self.bid, method=who, category=category, signature=signature or f"{who}:{category}",
                               detail=str(detail)[:4000], evidence=list(evidence), **extra))


def _pintypes_args(physics_board, pt):
    """--pintypes only for a physics_board.py that takes it: an experiment's older harness
    exits 2 on the flag, and boards gained pintypes.json after their first evaluation."""
    if not pt.exists() or "--pintypes" not in Path(physics_board).read_text(errors="ignore"):
        return []
    return ["--pintypes", pt]


def cmd_job(a):
    """One board: prepare the task, run every missing method, evaluate, archive under the board."""
    e = load_exp(a.experiment) if a.experiment else None
    bid = a.board
    row = corpus_rows().get(bid)
    if row is None:
        raise SystemExit(f"{bid}: not in the corpus manifest")
    harness = a.harness or e["harness"]["commit"]
    haslam = a.haslam or e["haslam"]["commit"]
    if a.method:
        todo = []
        for m in a.method:   # ID or ID@ATTEMPT
            mid, _, att = m.partition("@")
            todo.append((find_method(mid)["id"], int(att) if att else a.attempt))
    else:
        todo = missing(e, bid)
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    signal.signal(signal.SIGTERM, _on_sigterm)
    print(f"{bid}: pid {os.getpid()} job {os.environ.get('HASLAMQ_JOB')} methods {[m for m, _ in todo]}", flush=True)
    ws = Path(os.environ.get("HASLAMQ_SCRATCH") or tempfile.mkdtemp(prefix="haslamres-", dir="/var/tmp"))
    src = ws / "src" / bid
    src.mkdir(parents=True, exist_ok=True)
    for p in (CORPUS / row["path"]).iterdir():
        if (p.name.startswith("board.") or p.name == "row.json") and not (src / p.name).exists():
            os.symlink(p, src / p.name)
    size = board_size_mb(row)
    env = dict(os.environ)
    env.update({k: v for k, v in env_sh().items() if k not in env})
    binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
    env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(CORPUS.resolve())]))
    kcfg = STORE / "kicad-config" / "threads-2"
    if not (kcfg / "10.0" / "kicad_advanced").exists():
        srcc = Path.home() / ".config" / "kicad" / "10.0"
        tmpc = kcfg.with_name(kcfg.name + f".tmp{os.getpid()}")
        shutil.copytree(srcc, tmpc / "10.0") if srcc.is_dir() else (tmpc / "10.0").mkdir(parents=True)
        (tmpc / "10.0" / "kicad_advanced").write_text("MaximumThreads=2\n")  # one thread per host CPU otherwise
        try:
            os.replace(tmpc, kcfg)
        except OSError:
            shutil.rmtree(tmpc, ignore_errors=True)
    env["KICAD_CONFIG_HOME"] = str(kcfg)
    env.update({k: v for k, v in ((e or {}).get("env") or {}).items() if k in RESULT_NEUTRAL_ENV})
    env["HASLAM_DRC_TIMEOUT"] = str(900 if size < 20 else 3600)
    env["JAVA_TOOL_OPTIONS"] = f"-Xmx{heap_gb(size)}g -XX:ActiveProcessorCount=2"
    env.pop("VIRTUAL_ENV", None)
    log = ws / "job.log"
    pre = subprocess.run([*env.get("HASLAM_KICAD_WRAP", "").split(), "python3", "-c", "import pcbnew"],
                         capture_output=True, text=True, env=env, timeout=600)
    if pre.returncode != 0:  # the environment, not the board: haslamq retries and reports it
        print(f"preflight failed: KiCad's Python cannot import pcbnew (rc {pre.returncode}):\n{pre.stderr[-2000:]}", flush=True)
        return 75
    kicad = kicad_version()
    t0 = time.monotonic()

    # group methods by the harness commit they run with; the human reference goes with the experiment's
    groups = defaultdict(list)
    ms = {}
    for mid, att in todo:
        m = ms[mid] = find_method(mid)
        groups[(m["code"].get("harness") or {}).get("commit") or harness].append((m, att))
    if human and not find_run(bid, human["id"], 0)[0] and (human["id"], 0) not in todo:
        groups[harness].append((human, 0))  # every board gets the human layout scored, once
    made = []
    for hc, items in groups.items():
        if STOP:
            break
        print(f"{bid}: harness {hc[:8]}: " + ", ".join(f"{m['name']}#{att}" for m, att in items), flush=True)
        made += _job_group(bid, row, hc, haslam, items, human, ws, env, log, kicad, a, size, prep_harness(hc, harness))
    print(f"{bid}: {len(made)} {'incomplete ' if STOP else ''}run(s) written in {time.monotonic() - t0:.0f}s: "
          f"{', '.join(made) or '-'}", flush=True)
    if STOP:
        return 143
    shutil.rmtree(ws / "w", ignore_errors=True)
    return 0


NUMBA_CACHE_RE = re.compile(r"\$HOME/\.cache/haslambench/(numba-[A-Za-z0-9._-]+)")


def publish_numba_cache(m, rdir, log=None):
    """Keep the numba kernels a command method compiled in its work dirs (rdir) in the warm cache its
    template names ($HOME/.cache/haslambench/numba-NAME, copied to $PWD/numba before haslam runs), adding
    only kernels the cache lacks. numba compiles a kernel on its first call unless the cache has it;
    a named cache that was never warmed (`cp -r` fails silently) made every haslam process of every job
    compile from scratch (about 110 CPU seconds per haslam.joint.cli run). Kernels
    are keyed by their source file's path and mtime, so one checkout's kernels never load for
    another's. A kernel is its index (.nbi) and the data files (.N.nbc) it names, and numba loads a
    data file by name without checking its signature, so a kernel's files must all come from one run:
    a publisher claims the kernel (an exclusive .claim file) and skips it when another holds the claim
    or the index is there. Data files go first and the index last, each written to a temporary name
    and renamed, so a job copying the cache meanwhile sees a kernel whole or not at all."""
    names = NUMBA_CACHE_RE.findall(m["recipe"]["runner"].get("template") or "")
    if not names or not rdir.is_dir():
        return 0
    added = 0
    for name in dict.fromkeys(names):
        dst = Path.home() / ".cache" / "haslambench" / name
        for nbi in sorted(rdir.rglob("*.nbi")):
            to = dst / nbi.parent.name
            if (to / nbi.name).exists():
                continue
            stem = nbi.name[:-len(".nbi")]
            claim = to / f"{stem}.claim"
            try:
                to.mkdir(parents=True, exist_ok=True)
                os.close(os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                continue
            except OSError as e:
                if log:
                    with open(log, "a") as fh:
                        fh.write(f"numba cache {name}: could not add {nbi.name}: {e}\n")
                break
            try:
                if (to / nbi.name).exists():   # published between the check above and the claim
                    continue
                for f in [*sorted(nbi.parent.glob(glob.escape(stem) + ".*.nbc")), nbi]:
                    tmp = to / f"{f.name}.tmp{os.getpid()}"
                    shutil.copyfile(f, tmp)
                    os.replace(tmp, to / f.name)
                added += 1
            except OSError as e:
                if log:
                    with open(log, "a") as fh:
                        fh.write(f"numba cache {name}: could not add {nbi.name}: {e}\n")
                break
            finally:
                claim.unlink(missing_ok=True)
    if added and log:
        with open(log, "a") as fh:
            fh.write(f"numba cache {', '.join(names)}: added {added} kernel(s) from {m['id']}\n")
    return added


def numba_keep_work(m):
    """haslambench run flags for a method whose template names a numba cache: keep the attempts' work dirs,
    where its haslam processes left the kernels they compiled ($PWD/numba), until finish_numba_cache has
    read them. haslambench deletes them after scoring otherwise, and until 2026-11-21 it did so before
    publish_numba_cache looked, so no named cache was ever filled."""
    return ["--keep-work"] if NUMBA_CACHE_RE.search(m["recipe"]["runner"].get("template") or "") else []


def finish_numba_cache(m, rdir, log=None):
    """After a command method's run: publish its compiled kernels to its named numba cache, then delete
    the attempts' work dirs that numba_keep_work kept (as haslambench would have). Returns kernels added."""
    added = publish_numba_cache(m, rdir, log)
    if numba_keep_work(m) and rdir.is_dir():
        for w in rdir.glob("*/*/*/attempt-*/work"):
            shutil.rmtree(w, ignore_errors=True)
    return added


def prep_harness(hc, exp_hc):
    """The harness that prepares the tasks a method of harness hc runs on in an experiment of harness
    exp_hc: its own, unless its task spec is older than the experiment's and the experiment's is 10 or
    later (deterministic preparation, content aliases). Then the method runs, with its own harness, on
    the experiment's tasks, so its runs on boards whose task content did not change are reused."""
    s, e = harness_task_spec(hc), harness_task_spec(exp_hc)
    return exp_hc if s is not None and e is not None and e >= 10 and s < e else hc


def _venv(hc):
    d, venv = code_dir(hc), code_dir(hc).with_name(code_dir(hc).name + ".venv")
    if not (venv / "bin" / "haslambench").exists():
        raise SystemExit(f"harness {hc[:7]} is not installed: haslamres exp create sets it up ({d})")
    return d, venv


DETERMINISTIC_SPEC = 10   # prepare gives byte-identical task files from this task spec on (Task aliases)
TASK_CACHE_GB = 20.0


def task_cache_dir(bid, phc, inputs, src):
    """Where a job keeps or finds the preparation of board bid by harness phc for these inputs:
    $HASLAMRES_TASK_CACHE (default /var/tmp/$USER/haslamres-task-cache; "off" turns it off), one folder
    per board files' content (src: the job's board folder), harness, inputs and KiCad. None when
    off or when phc prepares with a task spec before DETERMINISTIC_SPEC (a copy would then not
    be what the job prepares itself)."""
    root = os.environ.get("HASLAMRES_TASK_CACHE", str(Path("/var/tmp") / (os.environ.get("USER") or str(os.getuid()))
                                                    / "haslamres-task-cache"))
    spec = harness_task_spec(phc)
    if root in ("", "0", "off") or spec is None or spec < DETERMINISTIC_SPEC:
        return None
    h = hashlib.sha256(json.dumps([phc, sorted(inputs), kicad_version()]).encode())
    for f in sorted(Path(src).iterdir()):
        h.update(f"{f.name}\0{sha256_file(f)}\0".encode())
    return Path(root) / f"{bid}.{h.hexdigest()[:20]}"


def _cache_put(task, cache):
    """Copy a prepared task into the cache atomically, then trim the cache to $HASLAMRES_TASK_CACHE_GB
    (default TASK_CACHE_GB), least recently used first. A failure only costs a later prepare."""
    tmp = cache.with_name(f".{cache.name}.{os.getpid()}")
    try:
        shutil.copytree(task, tmp, ignore=shutil.ignore_patterns("roundtrip"))
        os.replace(tmp, cache)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        return
    try:
        cap = float(os.environ.get("HASLAMRES_TASK_CACHE_GB") or TASK_CACHE_GB) * 2 ** 30
        entries = []
        for d in cache.parent.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                entries.append((d.stat().st_atime, sum(f.stat().st_size for f in d.rglob("*") if f.is_file()), d))
        total = sum(s for _, s, _ in entries)
        for _, s, d in sorted(entries):
            if total <= cap:
                break
            if d != cache:
                shutil.rmtree(d, ignore_errors=True)
                total -= s
    except OSError:
        pass


def _prepare(bid, phc, inputs, ws, env, log, steps, step="prepare"):
    """haslambench prepare-dir of the board with harness phc (once per job): (task directory or None, rc, timed out).
    A preparation another job made of the same board files, harness, inputs and KiCad is copied from the
    task cache instead (task_cache_dir); the step then records `cached`."""
    _, venv = _venv(phc)
    work = ws / f"w-{phc[:8]}"
    task = work / "tasks" / bid
    have = (read_json(task / "task.json") or {}).get("tasks") or {}
    rc, to = 0, False
    if not all(k in have for k in inputs):
        cache = None if have else task_cache_dir(bid, phc, inputs, ws / "src" / bid)
        if cache is not None and (cache / "task.json").exists():
            try:
                with Step(step, steps):
                    shutil.rmtree(task, ignore_errors=True)
                    shutil.copytree(cache, task)
                    os.utime(cache)   # recently used
                steps[step]["cached"] = str(cache)
                print(f"{bid}: task prepared by {phc[:7]} copied from {cache}", flush=True)
                return task, 0, False
            except (OSError, shutil.Error):   # evicted by another job meanwhile: prepare it here
                shutil.rmtree(task, ignore_errors=True)
        with Step(step, steps):
            rc, to = run_logged([venv / "bin" / "haslambench", "--workdir", work, "prepare-dir", "--dir", ws / "src",
                        "--board-glob", "board.kicad_pcb", "--only", bid, "--kinds", ",".join(inputs), "-j", "1",
                        *(["--force"] if have else [])],
                       log, dict(env, PATH=f"{venv / 'bin'}:{env.get('PATH', '')}"), timeout=3 * 3600)
        if cache is not None and rc == 0 and not to and (task / "task.json").exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            _cache_put(task, cache)
    return (task if (task / "task.json").exists() else None), rc, to


def fill_old_contents(bid, tids, kicad, method_ids, ws, env, log, steps):
    """Record the content of the older tasks the given methods' runs on this board were made on, as each
    run's own harness prepares them (one prepare per harness commit not yet recorded), so on_task can
    tell which of those runs count on the new tasks tids ({kind: id}). Harnesses whose code is not here
    are skipped: their runs are not reused."""
    want = defaultdict(set)  # harness -> {(kind, old task id)}
    for _, r in board_runs(bid):
        if r.get("method_id") not in method_ids or r.get("repro_of"):
            continue
        old = task_meta(bid, r.get("task_id") or "")
        kind = ((old or {}).get("recipe") or {}).get("kind")
        new = task_meta(bid, tids.get(kind, "")) if kind in tids else None
        phc = run_prepared_by(r)
        if not old or not new or not phc or r["task_id"] == tids[kind] or phc in contents_of(bid, r["task_id"]):
            continue
        if any((old["recipe"].get(k) != new["recipe"].get(k)) for k in ("board_sha256", "kicad")):
            continue
        want[phc].add((kind, r["task_id"]))
    for phc, pairs in sorted(want.items()):
        if not (code_dir(phc).with_name(code_dir(phc).name + ".venv") / "bin" / "haslambench").exists():
            print(f"{bid}: harness {phc[:7]} is not here; its runs are not reused", flush=True)
            continue
        task, _, _ = _prepare(bid, phc, sorted({INPUT_KIND.get(k, k) for k, _ in pairs}), ws, env, log, steps, f"prepare-{phc[:8]}")
        rec = read_json(task / "task.json") if task else None
        for kind, tid in sorted(pairs):
            if rec and rec.get("task_spec") == task_meta(bid, tid)["recipe"].get("task_spec"):
                record_content(bid, tid, phc, task_content(task, kind))


def _job_group(bid, row, hc, haslam, items, human, ws, env, log, kicad, a, size, phc=None):
    phc = phc or hc  # the harness that prepares the tasks (prep_harness); hc runs and scores the methods
    d, venv = _venv(hc)
    work = ws / f"w-{phc[:8]}"
    kb = [venv / "bin" / "haslambench", "--workdir", work]
    genv = dict(env, PATH=f"{venv / 'bin'}:{env.get('PATH', '')}")
    steps = {}
    bugs = Bugs(bid)
    kinds = sorted({"route"} | {m["recipe"]["kind"] for m, _ in items})
    # prepare builds task inputs; joint kinds run on the matching place input (haslambench's
    # prepare.INPUT_KIND), which must be asked for even when no place method is in the group
    inputs = sorted({INPUT_KIND.get(k, k) for k in kinds})
    task, rc, to = _prepare(bid, phc, inputs, ws, env, log, steps)
    if STOP:
        return []   # killed while preparing: no method ran (haslamq keeps the job's logs)
    task = task or work / "tasks" / bid
    tj = task / "task.json"
    if not tj.exists():
        txt = tail(log, 200)
        infra = re.search(r"no Python with pcbnew|kicad-cli not found|FATAL: +container|apptainer.*FATAL", txt)
        if infra:
            print(f"prepare hit an environment error, not a board error: {infra.group(0)}\n{tail(log, 30)}", flush=True)
            raise SystemExit(75)
        bugs.add("harness", "prepare_timeout" if to else "prepare_error", _first_error(txt) or f"rc={rc}",
                 signature=f"harness:prepare:{_normalize(_first_error(txt))}", log_tail=tail(log, 60))
        write_json(board_dir(bid) / "prepare-failures" / f"{phc[:12]}.json",
                   dict(board=bid, harness=phc, at=now(), steps=steps, bugs=bugs.items, log_tail=tail(log, 200)))
        _board_json(bid, row)
        return []
    record = json.loads(tj.read_text())
    tids = {}  # one task per kind; the route task keeps the id it had before other kinds existed
    for kind in kinds:
        task_recipe = dict(board_sha256=record.get("pcb_sha256"), task_spec=record.get("task_spec"), kind=kind, kicad=kicad)
        if row.get("dru_fix"):  # rules file repaired in the corpus (dru_fixes.py): a different task
            task_recipe["dru_fix"] = row["dru_fix"]["sha256_after"] or "removed"
        tids[kind] = ident(task_recipe)
        tdir = board_dir(bid) / "tasks" / tids[kind]
        if not (tdir / "task.json").exists():
            tmp = tdir.with_name(tdir.name + f".tmp{os.getpid()}")
            tmp.mkdir(parents=True, exist_ok=True)
            write_json(tmp / "task.json", dict(schema=SCHEMA, id=tids[kind], recipe=task_recipe, prepared_by=phc, at=now(), record=record))
            if (task / "reference" / "drc.json").exists():
                gz(task / "reference" / "drc.json", tmp / "human-drc.json.gz")
            try:
                os.replace(tmp, tdir)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
        record_content(bid, tids[kind], phc, task_content(task, kind))
    # runs on older tasks of equal content count on these (on_task): record what those tasks held
    fill_old_contents(bid, tids, kicad, {m["id"] for m, _ in items}, ws, env, log, steps)
    task_id = tids["route"]
    tid = lambda m: tids[m["recipe"]["kind"]]
    _board_json(bid, row)
    if getattr(a, "content_only", False):
        return []
    evs = evaluators_for(hc, haslam, kicad)
    # skip methods that already have a run on this task (another experiment may have made it meanwhile)
    todo = [(m, att) for m, att in items if a.method or find_run(bid, m["id"], att, tid(m))[0] is None]
    if not todo:
        return []
    arms, cmds = [], []
    for m, att in todo:
        r = m["recipe"]["runner"]
        arm = f"m{m['id']}"
        if r["type"] == "reference":
            arms += ["--arm", f"name={arm},adapter=reference"]
        elif r["type"] == "haslambench-adapter":
            arms += ["--arm", f"name={arm},adapter={r['adapter']},freerouting={m['binary']}"]
        else:
            cmds.append(m)
    timeout = max([method_timeout(m, row) for m, _ in todo] + [900])
    k = max(att for _, att in todo) + 1
    with Step("run", steps):
        if arms:
            print(f"{bid}: run {', '.join(m['name'] for m, _ in todo if m['recipe']['runner']['type'] != 'command')} "
                  f"x{k}", flush=True)
            rc, to = run_logged(kb + ["run", *arms, "--kinds", "route", "-k", str(k), "--timeout", str(timeout), "--all",
                                      "--only", bid, "--name", f"base-{hc[:8]}", "-j", "1"], log, genv,
                                timeout=len(todo) * k * (timeout + 1800) + 3600)
            if rc != 0:
                bugs.add("harness", "run_timeout" if to else "run_error", _first_error(tail(log, 200)) or f"rc={rc}",
                         log_tail=tail(log, 60))
        for m in cmds:
            if STOP:
                break
            print(f"{bid}: run {m['name']} ({m['id'][:8]}) x{k}", flush=True)
            p = m["recipe"]["params"]
            tpl, ro = command_template(m)
            if p.get("probe_command"):  # a placement's probe: a command router, with the method's code
                ptpl, pro = command_template(m, p["probe_command"])
                probe, ro = ["--probe", p.get("probe", "cmd-probe"), "--probe-command", ptpl], list(dict.fromkeys(ro + pro))
            else:
                probe = ["--probe", p["probe"]] if p.get("probe") else []
            extra = [x for r_ in ro for x in ("--sandbox-ro", r_)] + probe + numba_keep_work(m)
            # the sandbox hides the corpus, and Apptainer refuses to start when a bind source is missing;
            # the method's code must be bound too (KiCad's Python runs its scripts)
            cenv = dict(genv, APPTAINER_BIND=",".join([str(ws), *map(str, ro)]))
            rc, to = run_logged(kb + ["run", "--adapter", f"m{m['id']}", "--command", tpl, *extra, "--kinds", m["recipe"]["kind"],
                                      "-k", str(k), "--timeout", str(method_timeout(m, row)), "--all", "--only", bid,
                                      "--name", f"cmd-{m['id']}", "-j", "1"], log, cenv,
                                timeout=k * (method_timeout(m, row) + 1800) + 3600)
            finish_numba_cache(m, work / "results" / f"cmd-{m['id']}", log)
    adirs = {}
    for m, att in todo:
        rn = f"base-{hc[:8]}" if m["recipe"]["runner"]["type"] != "command" else f"cmd-{m['id']}"
        adirs[(m["id"], att)] = work / "results" / rn / f"m{m['id']}" / m["recipe"]["kind"] / bid / f"attempt-{att}"
    if STOP:
        return _store_incomplete(bid, todo, adirs, hc, tid, steps, a, log, phc)
    human_adir = adirs.get((human["id"], 0)) if human else None
    fresh = (read_json(human_adir / "attempt.json") or {}) if human_adir else {}
    fresh_types = (fresh.get("score") or {}).get("errors_by_type")
    human_base = (dict(types=fresh_types, source="exact", evaluator=evs["drc"]) if fresh_types is not None
                  else human_drc_baseline(bid, human, task_id, evs["drc"]))

    # routed physics of every new run's scored board (and the human board), one brief from the task input
    boards = {}
    kind_of = {m["id"]: m["recipe"]["kind"] for m, _ in todo}
    for (mid, att), adir in adirs.items():
        aj = read_json(adir / "attempt.json") or {}
        sb = routed_board(kind_of.get(mid), aj, adir)
        if sb is not None:
            boards[f"{mid}.{att}"] = sb
    phys = {}
    if boards:
        kd, kv = code_dir(haslam), code_dir(haslam).with_name(code_dir(haslam).name + ".venv-haslam")
        pout = ws / f"physics-{hc[:8]}.json"
        with Step("physics", steps):
            pt = board_dir(bid) / "pintypes.json"  # the schematic's pin types, as re-evaluation passes them
            pb = d / "tools" / "haslamres" / "physics_board.py"
            rc, to = run_logged([kv / "bin" / "python", pb,
                                 "--input", task / "route" / "input" / "board.kicad_pcb",
                                 *[x for n, p in boards.items() for x in ("--board", f"{n}={p}")], "--out", pout,
                                 *_pintypes_args(pb, pt)],
                                log, genv, timeout=int(1800 + 120 * size))
        phys = read_json(pout) or dict(error=f"physics step {'timed out' if to else f'failed rc={rc}'}")
        if STOP:
            return _store_incomplete(bid, todo, adirs, hc, tid, steps, a, log, phc)
        if phys.get("error"):
            bugs.add("physics", "physics_error", phys["error"], signature=f"physics:board:{_normalize(phys['error'])}",
                     traceback=phys.get("traceback"))

    made = []
    for (mid, att), adir in adirs.items():
        m = find_method(mid)
        rb = Bugs(bid)
        aj = read_json(adir / "attempt.json")
        if aj is None:
            bugs.add("harness", "attempt_missing", f"haslambench wrote no attempt.json for {m['name']}", log_tail=tail(log, 60))
            continue
        if m["recipe"]["runner"]["type"] != "reference":
            _run_bugs(rb, m, aj, adir, human_base)
        if aj.get("status") == "score_error":
            rb.add("harness", "score_error", aj.get("error"), signature=f"harness:score_error:{_normalize(aj.get('error'))}",
                   evidence=["score_error.log"])
        ph = (phys.get("boards") or {}).get(f"{mid}.{att}")
        if ph and ph.get("error"):
            rb.add("physics", "physics_error", ph["error"], signature=f"physics:{_normalize(ph['error'])}",
                   evidence=[f"evals/{evs['physics']}.json"], traceback=ph.get("traceback"))
        name = _write_run(bid, m, att, tid(m), hc, aj, adir, ph, evs, rb.items + bugs.items, steps, a, phc)
        bugs.items = []  # board-level bugs go with the first run written
        if name:
            made.append(name)
    return made


def _store_incomplete(bid, todo, adirs, hc, tid, steps, a, log, phc):
    """A killed job's attempts, as far as they got, under boards/<id>/incomplete/<run>.j<haslamq job>/ (not runs/, so
    nothing that reads runs counts them, and the job's retry runs every method again): run.json with status
    `killed_<reason>` (timeout, cancelled, oom, disk, preempted; an attempt that had finished keeps its own status)
    and `incomplete`, the adapter log or the method's live log, restart.py's summary and attempt logs (with the budget
    report and gap lines haslam prints), the board so far, and the job's log, within INCOMPLETE_MB for the whole job:
    logs first (a big one only its tail), newest first, then boards. Returns the names written."""
    reason, job = STOP.get("reason", "signal"), os.environ.get("HASLAMQ_JOB") or str(os.getpid())
    left, made = INCOMPLETE_MB * MB, []

    def put(src, dst, text=True):
        nonlocal left
        size = src.stat().st_size
        take = min(size, left, INCOMPLETE_MB * MB // 4) if text else size
        if take <= 0 or take > left:
            return dict(file=dst, bytes=size, kept=False)
        dst_p = tmp / dst
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as f, gzip.open(dst_p, "wb") as g:
            f.seek(size - take)
            shutil.copyfileobj(f, g)
        left -= take
        return dict(file=dst, bytes=size, kept=True, **({"tail_bytes": take} if take < size else {}))

    for m, att in todo:
        if m["recipe"]["runner"]["type"] == "reference":
            continue
        adir = adirs[(m["id"], att)]
        aj = read_json(adir / "attempt.json") or {}
        finished = aj.get("status") not in (None, "killed", "not_started")
        dest = board_dir(bid) / "incomplete" / f"{run_name(m, att)}.j{job}"
        tmp = dest.with_name(f".tmp-{dest.name}-{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        work = adir / "work"
        logs = [(adir / "adapter.log", "adapter.log.gz")] if (adir / "adapter.log").exists() else []
        if not logs and (work / "method.log").exists():
            logs.append((work / "method.log", "method.log.gz"))
        rs = work / "restarts"
        if (rs / "summary.json").exists():
            logs.append((rs / "summary.json", "restarts.json.gz"))
        if rs.is_dir():
            logs += [(p, f"restarts/{p.relative_to(rs).as_posix().replace('/', '.')}.gz")
                     for p in sorted((q for q in rs.rglob("*") if q.is_file() and (q.name == "log" or q.suffix in
                                                                                   (".log", ".jsonl"))),
                                     key=lambda q: -q.stat().st_mtime)]
        if (adir / "score" / "drc.json").exists():
            logs.append((adir / "score" / "drc.json", "drc.json.gz"))
        if not made and log.exists():   # the job's own log once, with the first run
            logs.append((log, "job.log.gz"))
        files = [put(src, dst) for src, dst in logs]
        board = next((b for b in (adir / "output" / "board.kicad_pcb", work / "output" / "board.kicad_pcb") if b.exists()), None)
        if board is not None:
            files.append(dict(put(board, "output.kicad_pcb.gz", text=False), source=str(board.relative_to(adir))))
        run = dict(schema=SCHEMA, run=dest.name, board=bid, method_id=m["id"], method_name=m["name"], attempt=att,
                   task_id=tid(m), harness_commit=hc, task_prepared_by=phc or hc, experiment=a.experiment, haslamq_job=job,
                   finished=now(), status=aj.get("status") if finished else f"killed_{reason}",
                   incomplete=dict(reason=reason, stopped_at=STOP.get("when"), attempt_status=aj.get("status"),
                                   adapter_status=aj.get("stopped_status"), attempt_finished=finished,
                                   note="killed job: kept for diagnosis, not a result"),
                   error=aj.get("error"), runtime_s=aj.get("runtime_s"), method_usage=aj.get("method_usage"),
                   adapter_meta=aj.get("adapter_meta"), job_steps=steps, work=_work(adir), files=files)
        write_json(tmp / "run.json", run)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tmp, dest)
        made.append(dest.name)
        print(f"{bid}: incomplete {dest.name}: {run['status']}, {sum(f['kept'] for f in files)} file(s), "
              f"board {'kept' if board is not None else 'none'}", flush=True)
    return made


def _work(adir):
    """The work a method reports with a last `HASLAM_WORK {json}` line (restart.py): attempts, CPU
    seconds over all its processes (the harness cannot see inside the sandbox), peak RSS."""
    log = adir / "adapter.log"
    if not log.exists():
        return None
    for line in reversed(log.read_text(errors="replace").splitlines()):
        # KAE_WORK: what restart.py printed before the rename of PR #163; pinned pre-rename methods still do
        tag, _, rest = line.partition(" ")
        if tag in ("HASLAM_WORK", "KAE_WORK"):
            try:
                return json.loads(rest)
            except ValueError:
                return None
    return None


def _board_json(bid, row):
    p = board_dir(bid) / "board.json"
    if not p.exists():
        write_json(p, row)


RESTART_FILES = {"summary.json": "restarts.json", "report.json": "restart-report.json",
                 "report-windows.json": "restart-report-windows.json",
                 "report-origin.json": "restart-report-origin.json", "fr-telemetry.tar": "fr-telemetry.tar"}


def _keep_restart_files(art, tmp):
    """restart.py's per-attempt log and the kept attempt's report (haslambench keeps them as artifacts):
    a joint loop's iterations, windows and stop reason are in restart-report.json, or, when the kept
    board was resumed or had a final pass, in restart-report-origin.json."""
    for src, dst in RESTART_FILES.items():
        if (art / src).is_file():
            shutil.copy2(art / src, tmp / dst)


def _write_run(bid, m, att, task_id, hc, aj, adir, ph, evs, bugs, steps, a, phc=None):
    """Archive one run (output, logs, evaluations, bugs) atomically under the board."""
    suffix = f".repro-{datetime.now().strftime('%Y%m%dT%H%M%S')}" if a.repro else ""
    dest = board_dir(bid) / "runs" / run_name(m, att, suffix)
    if dest.exists() and not suffix:
        d0, r0 = find_run(bid, m["id"], att, task_id)
        if d0 is not None:
            return None  # made by another experiment's job meanwhile
        dest = dest.with_name(dest.name + f".t{task_id[:8]}")  # same method, a different task (board or task spec changed)
    tmp = dest.with_name(f".tmp-{dest.name}-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "evals").mkdir(parents=True)
    out = adir / "output" / "board.kicad_pcb"
    if out.exists():
        gz(out, tmp / "output.kicad_pcb.gz")
    if (adir / "adapter.log").exists():
        gz(adir / "adapter.log", tmp / "adapter.log.gz")
    art = adir / "artifacts"
    if (art / "result.json").exists():
        shutil.copy2(art / "result.json", tmp / "router-report.json")
    if (art / "board.ses").exists():
        gz(art / "board.ses", tmp / "board.ses.gz")
    if any(b["category"] not in ("drc",) for b in bugs) and art.exists():  # the router's exact input, to reproduce
        (tmp / "artifacts").mkdir()
        for p in art.iterdir():
            if p.is_file() and p.name not in ("result.json", "board.ses", *RESTART_FILES):
                gz(p, tmp / "artifacts" / (p.name + ".gz"))
    if (adir / "score_error.log").exists():
        shutil.copy2(adir / "score_error.log", tmp / "score_error.log")
    run = dict(schema=SCHEMA, run=dest.name, board=bid, method_id=m["id"], method_name=m["name"], attempt=att,
               task_id=task_id, harness_commit=hc, task_prepared_by=phc or hc, experiment=a.experiment, haslamq_job=os.environ.get("HASLAMQ_JOB"),
               finished=now(), java_tool_options=os.environ.get("JAVA_TOOL_OPTIONS") if m["recipe"]["runner"]["type"] != "reference" else None,
               status=aj.get("status"), error=aj.get("error"), runtime_s=aj.get("runtime_s"), over_time=aj.get("over_time"),
               method_usage=aj.get("method_usage"), adapter_meta=aj.get("adapter_meta"), load_avg=[aj.get("load_avg_start"), aj.get("load_avg_end")],
               job_steps=steps, work=_work(adir), **({"repro_of": run_name(m, att)} if suffix else {}))
    write_json(tmp / "run.json", run)
    _keep_restart_files(art, tmp)
    if not (tmp / "restarts.json").exists():
        for sj in adir.rglob("restarts/summary.json"):  # a place method's probe: restart.py's per-attempt log
            shutil.copy2(sj, tmp / "restarts.json")
            break
    if aj.get("score") is not None:
        ev = dict(schema=SCHEMA, evaluator=evs["drc"], run=dest.name, at=now(), score=aj["score"], probe=aj.get("probe"),
                  scoring_s=aj.get("scoring_s"), scoring_usage=aj.get("scoring_usage"))
        write_json(tmp / "evals" / f"{evs['drc']}.json", ev)
        keep_drc_reports(adir / "score", tmp / "evals", evs["drc"])
    if ph is not None:
        write_json(tmp / "evals" / f"{evs['physics']}.json", dict(schema=SCHEMA, evaluator=evs["physics"], run=dest.name,
                                                                   at=now(), physics={k: v for k, v in ph.items() if k != "traceback"}))
    write_json(tmp / "bugs.json", bugs)
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    return dest.name


_EXC = re.compile(r"\b((?:[a-z_][\w$]*\.)+[A-Z]\w*(?:Exception|Error))\b(:?[^\n]{0,200})")


def _first_error(text):
    for line in (text or "").splitlines():
        if re.search(r"Traceback|Error|Exception|error:|FAILED|Killed|Timeout|timed out", line):
            return line.strip()[:500]
    return ""


def _normalize(msg):
    """A grouping key: message with paths, numbers and ids removed."""
    msg = re.sub(r"/[^\s:'\"]+", "<path>", msg or "")
    msg = re.sub(r"0x[0-9a-f]+|\d+(\.\d+)?", "N", msg)
    return re.sub(r"\s+", " ", msg).strip()[:160]


def _java_exceptions(log):
    """Distinct Java exception classes in a router log, with the first message and frame of each."""
    out = {}
    lines = log.splitlines()
    for i, line in enumerate(lines):
        for m in _EXC.finditer(line):
            cls = m.group(1)
            if cls in out:
                out[cls]["count"] += 1
                continue
            frame = next((l.strip() for l in lines[i + 1:i + 6] if l.strip().startswith("at ")), "")
            out[cls] = dict(count=1, message=(m.group(2) or "").strip(": ")[:300], frame=frame[:300], line=line.strip()[:400])
    return out


def human_drc_baseline(bid, human, task_id, evaluator):
    """What the human layout's DRC errors are, for comparing a method on this board. source "exact": the
    human run on task_id scored by evaluator. "fallback": the human's newest evaluation otherwise (another
    evaluator, or a run on another task of the board; a task spec bump leaves many boards with only that).
    "none": no scored human run, so types is None: not the same thing as a human layout with no errors."""
    d, _ = find_run(bid, human["id"], 0, task_id) if human else (None, None)
    on_task = d is not None
    if human and d is None:
        d, _ = find_run(bid, human["id"], 0)
    scored = {k: v for k, v in evals_of(d).items() if ((v or {}).get("score") or {}).get("errors_by_type") is not None} if d else {}
    if not scored:
        return dict(types=None, source="none", evaluator=None)
    key = evaluator if evaluator in scored else max(scored, key=lambda k: scored[k].get("at") or "")
    return dict(types=scored[key]["score"]["errors_by_type"], source="exact" if on_task and key == evaluator else "fallback",
                evaluator=key, on_task=on_task)


def _drc_bugs(bugs, who, errors_by_type, base):
    """DRC bug records of one run: per type, the errors beyond what the human layout has on the same board.
    Comparisons not against the experiment's own human score get their own signature, to stay apart."""
    ev = ["evals/", "output.kicad_pcb.gz"]
    meta = dict(source=base["source"], evaluator=base["evaluator"])
    for typ, n in sorted((errors_by_type or {}).items()):
        if base["source"] == "none":
            bugs.add(who, "drc", f"{n} {typ} error(s); no human baseline", signature=f"{who}:drc:{typ}:no-human-baseline",
                     drc_type=typ, count=n, evidence=ev, human_baseline=meta)
            continue
        h = base["types"].get(typ, 0)
        if n - h <= 0:
            continue
        if base["source"] == "exact":
            bugs.add(who, "drc", f"{n - h} {typ} error(s) beyond the human layout's {h}", signature=f"{who}:drc:{typ}",
                     drc_type=typ, count=n - h, evidence=ev, human_baseline=meta)
        else:
            where = "" if base.get("on_task") else ", on another task of this board"
            bugs.add(who, "drc", f"{n - h} {typ} error(s) beyond the human layout's {h} "
                     f"(fallback: human scored by evaluator {base['evaluator']}{where}, not the experiment's)",
                     signature=f"{who}:drc:{typ}:human-fallback", drc_type=typ, count=n - h, evidence=ev, human_baseline=meta)


def _run_bugs(bugs, m, row, adir, human_base):
    """Bug records for one method's attempt. Signatures start with the method name."""
    who = m["name"]
    st = row.get("status")
    meta = row.get("adapter_meta") or {}
    s = row.get("score") or {}
    log = (adir / "adapter.log").read_text(errors="replace") if (adir / "adapter.log").exists() else ""
    ev = ["run.json", "adapter.log.gz"]
    rep = meta.get("router_report") or {}
    if st == "adapter_error":
        err = row.get("error") or ""
        cat = "ses_import_error" if "import" in err.lower() else "adapter_error"
        bugs.add(who, cat, err, signature=f"{who}:{cat}:{_normalize(err)}", evidence=ev + ["artifacts/"])
    elif st == "no_output":
        if meta.get("ses_empty") or meta.get("ses_cut"):
            cat = "ses_incomplete"
        elif meta.get("timed_out"):
            cat = "no_output_at_deadline"  # the router ignored its own job timeout and wrote nothing
        elif meta.get("rc") not in (0, None):
            cat = "router_crash"
        else:
            cat = "no_output"
        bugs.add(who, cat, f"rc={meta.get('rc')} timed_out={meta.get('timed_out')} final_state={rep.get('final_state')}\n"
                 + "\n".join(log.splitlines()[-30:]), evidence=ev + ["artifacts/"])
    for cls, x in _java_exceptions(log).items():
        cat = "java_oom" if "OutOfMemoryError" in cls else "java_exception"
        bugs.add(who, cat, x["line"], signature=f"{who}:{cat}:{cls}:{x['frame']}", exception=cls, count=x["count"],
                 frame=x["frame"], evidence=ev + ["artifacts/"])
    # the router's own count of open connections vs KiCad's on the imported board: more open in KiCad
    # means connections were lost in translation (DSN export, SES import) or routed copper is illegal there
    own_open = ((rep.get("board_statistics") or {}).get("connections") or {}).get("incomplete_count")
    if st == "ok" and own_open is not None and s.get("unconnected") is not None and s["unconnected"] > own_open:
        bugs.add(who, "unconnected_mismatch", f"KiCad finds {s['unconnected']} unconnected, the router reported {own_open} incomplete",
                 count=s["unconnected"] - own_open, evidence=ev + ["router-report.json", "board.ses.gz"])
    if row.get("over_time"):
        bugs.add(who, "over_time", f"runtime {row.get('runtime_s')}s exceeded the attempt timeout", evidence=ev)
    if s and s.get("valid") is False:
        bad = [k for k, v in (s.get("integrity") or {}).items() if not v]
        bugs.add(who, "integrity", f"invalid output: {bad} foreign={(s.get('foreign') or {}).get('by_kind')}",
                 signature=f"{who}:integrity:{','.join(sorted(bad))}", evidence=ev + ["evals/"])
    # DRC errors the method created
    _drc_bugs(bugs, who, s.get("errors_by_type"), human_base)


# ------------------------------------------------------------------ reading results back
PHYSICS_U_CAP = 5.0   # haslam.joint.scorecard.U_CAP (a test keeps them equal): the cap of physics_total


def physics_valued(ph):
    """(valued-only total, number of modules with a value) of a physics evaluation: physics_total without the flat 3
    counted for modules that have no value. A board where nothing could be measured has no valued total (None)."""
    us = [v.get("u") for v in (ph.get("modules") or {}).values() if v.get("u") is not None]
    if not us:
        return None, 0
    return round(sum(min(PHYSICS_U_CAP, max(0.0, float(u))) for u in us), 4), len(us)


MFG_COLUMNS = ("ca_short_per_m_pours", "width_at_class_min", "copper_pair_diff_pp", "copper_flag", "vip_small_signal",
               "fab_class_jlcpcb", "phantom_share", "exp_breakout_40um", "acute_per_m")


def mfg_of(ed):
    """The manufacturability columns of a run from its evaluations (the newest `mfg` evaluation; refilled ones first), or {}."""
    evs = [(k, v) for k, v in ed.items() if (v or {}).get("mfg") is not None]
    if not evs:
        return {}
    k, v = max(evs, key=lambda kv: (bool((kv[1]["mfg"] or {}).get("refilled")), kv[1].get("at") or "", kv[0]))
    return dict(v["mfg"], evaluator=k)


def run_view(bid, d, r, evs, human_phys=None):
    """One flat row: a run with the given evaluators' results."""
    ed = evals_of(d)
    s = (ed.get(evs.get("drc")) or {}).get("score") or {}
    pr = ((ed.get(evs.get("drc")) or {}).get("probe") or {}).get("score")
    if pr and "clean" not in s:  # a place task: the routing numbers are the probe's route of the placement
        # clean also needs a legal placement: parts left off the outline are no DRC error, so a probe can
        # route an illegal placement clean (haslambench's joint clean is legal and routed clean, too)
        s = dict(pr, valid=bool(s.get("valid") and pr.get("valid")), legal=s.get("legal"),
                 clean=bool(pr.get("clean") and s.get("legal")))
    ph = ((ed.get(evs.get("physics")) or {}).get("physics")) or {}
    mfg = mfg_of(ed)
    meta = r.get("adapter_meta") or {}
    rep = meta.get("router_report") or {}
    mu = r.get("method_usage") or {}
    row = dict(board=bid, method=r["method_name"], method_id=r["method_id"], run=r["run"], attempt=r["attempt"],
               task_id=r["task_id"], status=r["status"], valid=s.get("valid"), legal=s.get("legal"), clean=s.get("clean"),
               completion=s.get("completion"), start_unconnected=s.get("start_unconnected"), unconnected=s.get("unconnected"),
               errors=s.get("errors"), warnings=s.get("warnings"), errors_by_type=json.dumps(s.get("errors_by_type") or {}, sort_keys=True),
               track_length_mm=s.get("track_length_mm"), vias=s.get("vias"), wl_ratio=s.get("wl_ratio"), via_delta=s.get("via_delta"),
               runtime_s=r.get("runtime_s"), cpu_s=method_cpu_s(r),
               max_rss_mb=(r.get("work") or {}).get("peak_rss_mb") or mu.get("max_rss_mb"),
               attempts=(r.get("work") or {}).get("attempts"), wall_to_best_s=(r.get("work") or {}).get("wall_to_best_s"),
               timed_out=meta.get("timed_out"), partial=meta.get("partial"), final_state=rep.get("final_state"),
               router_incomplete=((rep.get("board_statistics") or {}).get("connections") or {}).get("incomplete_count"),
               router_introduced_violations=((rep.get("board_statistics") or {}).get("clearance_violations") or {}).get("router_introduced_count"),
               physics_total=ph.get("physics_total"), physics_modules=ph.get("n_modules"), physics_missing=ph.get("n_missing"),
               physics_open=ph.get("n_open"), worst_rail_mohm=ph.get("worst_rail_mohm"), physics_error=ph.get("error"),
               physics_vs_human=None, module_ratio_median=None, scored=bool(s), physics_scored=bool(ph),
               physics_valued_total=None, physics_observations=None, physics_valued_vs_human=None,
               mfg_refilled=mfg.get("refilled"), **{f"mfg_{c}": mfg.get(c) for c in MFG_COLUMNS})
    if ph and not ph.get("error"):
        row["physics_valued_total"], row["physics_observations"] = physics_valued(ph)
    if human_phys and ph and not ph.get("error") and not human_phys.get("error"):
        if human_phys.get("physics_total"):
            row["physics_vs_human"] = round(ph["physics_total"] / human_phys["physics_total"], 4)
        ratios = [x["value"] / hm["value"] for k, x in (ph.get("modules") or {}).items()
                  if x.get("value") and not x.get("open_hops")
                  and (hm := (human_phys.get("modules") or {}).get(k) or {}).get("value") and not hm.get("open_hops")]
        row["module_ratio_median"] = round(statistics.median(ratios), 4) if ratios else None
        hv = physics_valued(human_phys)[0]
        if hv and row["physics_valued_total"] is not None:
            row["physics_valued_vs_human"] = round(row["physics_valued_total"] / hv, 4)
    return row


def human_physics(bid, task_id, evs):
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    if not human:
        return None
    d, _ = find_run(bid, human["id"], 0, task_id)
    if d is None:  # place and joint tasks: the human layout is scored on the board's route task
        d, _ = find_run(bid, human["id"], 0)
    if d is None:
        return None
    return ((evals_of(d).get(evs.get("physics")) or {}).get("physics")) or None


def cmd_board(a):
    bid = a.id
    b = read_json(board_dir(bid) / "board.json")
    if b is None:
        raise SystemExit(f"no results for board {bid}")
    print(f"{bid}: {b.get('layers')} layers, {b.get('footprints')} footprints, {b.get('nets')} nets, {b.get('collection')}, {b.get('license_tier')}")
    for p in sorted((board_dir(bid) / "tasks").glob("*/task.json")):
        t = read_json(p)
        rd = t["record"]["reference"]["drc"]
        print(f"task {t['id']}: split {t['record']['split']}, pads {t['record']['reference']['stats'].get('pads')}, "
              f"human unconnected {rd['unconnected']} errors {rd['errors']}, spec {t['recipe']['task_spec']}")
    for p in sorted((board_dir(bid) / "prepare-failures").glob("*.json")):
        f = read_json(p)
        print(f"prepare FAILED with harness {f['harness'][:7]}: {f['bugs'][0]['detail'][:120] if f['bugs'] else ''}")
    for p in sorted((board_dir(bid) / "incomplete").glob("*/run.json")):
        r = read_json(p) or {}
        print(f"incomplete (killed job {r.get('haslamq_job')}, not a result): {p.parent.name}: {r.get('status')}")
    hdr = ("run", "method", "status", "clean", "compl", "unconn", "errors", "wl_ratio", "vias±", "cpu_s", "physΣu", "Σu/human")
    rows = []
    for d, r in board_runs(bid):
        ed = evals_of(d)
        drc = [k for k, v in ed.items() if (v or {}).get("score") is not None]
        phy = [k for k, v in ed.items() if (v or {}).get("physics") is not None]
        evs = dict(drc=drc[-1] if drc else None, physics=phy[-1] if phy else None)
        v = run_view(bid, d, r, evs, human_physics(bid, r["task_id"], evs))
        f = lambda x, nd=3: "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))
        rows.append((r["run"], r["method_name"][:24], v["status"], f(v["clean"]), f(v["completion"]), f(v["unconnected"]),
                     f(v["errors"]), f(v["wl_ratio"]), f(v["via_delta"]), f(v["cpu_s"], 1), f(v["physics_total"], 2),
                     f(v["physics_vs_human"])))
        if len(drc) > 1 or len(phy) > 1:
            rows.append(("", f"  ({len(drc)} DRC and {len(phy)} physics evaluations; latest shown)", *[""] * 10))
    w = [max(len(str(x[i])) for x in rows + [hdr]) for i in range(len(hdr))]
    for x in [hdr] + rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(x)))
    print(f"\nfiles: {board_dir(bid)}/runs/<run>/ (run.json, output.kicad_pcb.gz, evals/, bugs.json)")


def cmd_rerun(a):
    d = Path(a.run).resolve()
    r = read_json(d / "run.json")
    if r is None:
        raise SystemExit(f"{d}: no run.json")
    m = find_method(r["method_id"])
    print(f"run {r['run']} of method {m['name']} ({m['id']}) on board {r['board']}, attempt {r['attempt']}, task {r['task_id']}")
    print("code:")
    for k, c in m["code"].items():
        extra = " (local snapshot; patch in methods/)" if c.get("dirty") else ""
        print(f"  {k}: {c['repo']} @ {c['commit']}{extra}  {c.get('link') or ''}")
    print(f"  harness that ran it: {r['harness_commit']}")
    if m.get("binary"):
        print(f"binary: {m['binary']} (sha256 {m['recipe']['runner']['binary_sha256'][:16]}..., copied from {m.get('binary_source')})")
    if m.get("build"):
        print(f"build: {m['build']}")
    print(f"recipe: {json.dumps(m['recipe'])}")
    exp = r.get("experiment")
    cmd = (f"haslamres job --board {r['board']} --method {m['id']} --attempt {r['attempt']} --harness {r['harness_commit']} "
           f"--haslam {load_exp(exp)['haslam']['commit'] if exp else '<haslam commit>'} --repro")
    print(f"reproduce (writes runs/{r['run']}.repro-<time>/): {cmd}")
    if a.submit:
        py = code_dir(r["harness_commit"]).with_name(code_dir(r["harness_commit"]).name + ".venv") / "bin" / "python"
        script = code_dir(r["harness_commit"]) / "tools" / "haslamres" / "haslamres.py"
        subprocess.run(["haslamq", "submit", "--owner", "haslamres-rerun", "--live", "--class", "timed",
                        "--cwd", str(code_dir(r["harness_commit"])),
                        "--mem", "8G", "--disk", "4G", "--timeout", "6h", "--cpus", "2", "--name", f"rerun:{r['run']}", "--",
                        str(py), str(script), *cmd.split()[1:]], check=True)


# ------------------------------------------------------------------ experiment reports
def clean_net_of_input(row, input_drc):
    """xc, "clean net of the input": valid, nothing unconnected, and no DRC error type above its count in
    the route task's input (input_drc: the human placement with its copper stripped). The same test
    restart.py stops on. Report-only; `clean` is unchanged. None when the input's DRC is not known.
    Fair for route-only methods: a method that moves parts no longer has the input's errors to inherit,
    so for placing methods (`kind` not route) reports mark it instead of comparing it."""
    if input_drc is None or input_drc.get("errors_by_type") is None:
        return None
    if not row.get("valid") or row.get("unconnected") != 0:
        return False
    base = input_drc["errors_by_type"]
    return all(n <= base.get(t, 0) for t, n in json.loads(row.get("errors_by_type") or "{}").items())


# bench/src/haslambench/score.py PLACEMENT_ERROR_TYPES (a test keeps them equal): the DRC types that make a placement illegal
PLACEMENT_ERROR_TYPES = ("courtyards_overlap", "copper_edge_clearance", "clearance", "hole_clearance",
                         "hole_to_hole", "holes_co_located", "items_not_allowed", "malformed_courtyard",
                         "npth_inside_courtyard", "pth_inside_courtyard", "shorting_items")


def legal_vs_human(row, input_drc):
    """legal_h, "not worse than the human" (user decision 2026-11-22): for every placement-type DRC error kind
    (PLACEMENT_ERROR_TYPES), the run has no more errors than the board's human layout has. The human counts are the
    route task's input DRC (the human placement with its copper stripped), computed once per board when the task is
    prepared and stored in its task record. On boards whose own human layout breaks the board's rules (courtyards
    overlapping, header pads within the copper-to-edge clearance), `legal` asks more than the human met; this asks
    for no more than that. Report-only: `legal` and `clean` are unchanged. None when the human layout's DRC is not
    known or the run has no score."""
    if input_drc is None or input_drc.get("errors_by_type") is None or row.get("errors_by_type") is None:
        return None
    if not row.get("valid"):
        return False
    base = input_drc["errors_by_type"]
    errs = json.loads(row.get("errors_by_type") or "{}")
    return all(errs.get(t, 0) <= base.get(t, 0) for t in PLACEMENT_ERROR_TYPES)


def fixed_input_placement_errors(e, bid):
    """Placement-type DRC errors of a board's fixed input ({type: count}; `record.tasks["place-fixed"].input_drc` of the
    experiment's joint-fixed task, else its place-fixed task): the placed parts a task can never move. Non-empty means
    the board cannot be `clean` (clean requires legal) for any method. Empty means winnable as far as this check
    knows, and None that the experiment's task spec has no such task for this board. Report-only."""
    for kind in ("joint-fixed", "place-fixed"):
        tid = exp_task_id(e, bid, kind)
        t = task_meta(bid, tid) if tid else None
        drc = (((t or {}).get("record") or {}).get("tasks") or {}).get("place-fixed", {}).get("input_drc")
        if drc is not None and drc.get("errors_by_type") is not None:
            return {k: n for k, n in drc["errors_by_type"].items() if k in PLACEMENT_ERROR_TYPES}
    return None


def route_input_drc(e, bid, r=None):
    """The route task's input DRC a run's xc is measured against: the experiment's route task of the board, else
    (given run r, when the experiment's task is not in the store) the run's own task if it is a route task.
    Unknown, None, otherwise, rather than guessed."""
    t = task_meta(bid, exp_task_id(e, bid, "route") or "") or (task_meta(bid, r["task_id"]) if r and _run_kind(r) == "route" else None)
    return ((((t or {}).get("record") or {}).get("tasks") or {}).get("route") or {}).get("input_drc")


def exp_rows(e):
    """(rows, bugs, prepare failures) of an experiment: each method's runs (every attempt) on each board's task of the
    experiment (exp_task_id; a run on another task is not comparable and is left out), viewed through
    the experiment's evaluators (falling back to the run's newest evaluation of the same type)."""
    boards = (exp_dir(e["name"]) / "boards.txt").read_text().split()
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    want = ([dict(id=human["id"], name=human["name"])] if human else []) + [m for m in e["methods"] if not human or m["id"] != human["id"]]
    rows, bugs, fails, stale = [], [], [], 0
    apart = []                      # boards whose methods' runs were made more than APART_H hours apart
    evs = e["evaluators"]
    for bid in boards:
        made = []
        bd = board_dir(bid)
        if not bd.exists():
            continue
        for p in (bd / "prepare-failures").glob(f"{e['harness']['commit'][:12]}.json"):
            fails.append(read_json(p))
        task_meta = None
        route_drc = route_input_drc(e, bid)
        fixed_errors = fixed_input_placement_errors(e, bid)
        human_base = human_drc_baseline(bid, human, exp_task_id(e, bid, "route"), evs["drc"]) if human else dict(types=None, source="none", evaluator=None)
        for m, att in ((m, att) for m in want for att in range(1 if m is want[0] and human else e.get("attempts") or 1)):
            d, r = find_run(bid, m["id"], att, exp_task_id(e, bid, _run_kind(dict(method_id=m["id"]))))
            if d is None:
                stale += find_run(bid, m["id"], att)[0] is not None
                continue
            if task_meta is None:
                task_meta = (read_json(bd / "tasks" / r["task_id"] / "task.json") or {}).get("record") or {}
            ed = evals_of(d)
            use = dict(evs, drc=evs.get("drc_current") or evs["drc"], physics=evs.get("physics_current") or evs["physics"])
            for key, field in (("drc", "score"), ("physics", "physics")):
                if use[key] not in ed:
                    other = [k for k, v in ed.items() if (v or {}).get(field) is not None]
                    use[key] = other[-1] if other else None
            v = run_view(bid, d, r, use, human_physics(bid, r["task_id"], use))
            v["evaluator_drc"], v["evaluator_physics"] = use["drc"], use["physics"]
            v["foreign_evaluator"] = use["drc"] is not None and use["drc"] != evs["drc"]  # scored, but by another scorer
            v["kind"] = _run_kind(r)
            v["xc"] = clean_net_of_input(v, route_drc if route_drc is not None else route_input_drc(e, bid, r))
            v["legal_h"] = legal_vs_human(v, route_drc if route_drc is not None else route_input_drc(e, bid, r))
            v["winnable"] = None if fixed_errors is None else not fixed_errors
            b = read_json(bd / "board.json") or {}
            v.update(repo=task_meta.get("repo"), split=task_meta.get("split"), pads=(task_meta.get("reference") or {}).get("stats", {}).get("pads"),
                     human_clean=task_meta.get("human_clean"), qualified=task_meta.get("qualified"),
                     layers=b.get("layers"), footprints=b.get("footprints"), collection=b.get("collection"), license_tier=b.get("license_tier"))
            rows.append(v)
            # a run's bugs.json keeps what its job knew; its DRC records are re-based on today's human baseline
            recs = read_json(d / "bugs.json", [])
            if use["drc"] is not None and (human is None or m["id"] != human["id"]):
                rb = Bugs(bid)
                _drc_bugs(rb, m["name"], (ed[use["drc"]].get("score") or {}).get("errors_by_type"), human_base)
                recs = [x for x in recs if x.get("category") != "drc"] + rb.items
            bugs += recs
            if human is None or m["id"] != human["id"]:
                made.append(r.get("finished"))
        ts = [datetime.fromisoformat(t) for t in made if t]
        if len(ts) >= 2 and (max(ts) - min(ts)).total_seconds() > APART_H * 3600:
            apart.append(bid)
    if apart:
        print(f"warning: on {len(apart)} boards the methods' runs were made more than {APART_H} h apart "
              f"(e.g. {apart[0]}): host load moves results by ~14 %, so those comparisons are not reliable",
              file=sys.stderr)
    e["_apart"] = apart
    if stale:
        print(f"{stale} runs left out: made on another task (board file, task spec or KiCad) than this experiment's",
              file=sys.stderr)
    return rows, bugs, fails


APART_H = 12      # hours between the runs of one board's methods past which the report warns


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def _f(x, nd=3):
    if x is None:
        return "—"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def _common(rows, names, key):
    """Boards on which every method of `names` that has rows here has a value of `key` on an ok run."""
    sets = [{r["board"] for r in rows if r["method"] == n and r["status"] == "ok" and r[key] is not None}
            for n in names if any(r["method"] == n for r in rows)]
    return set.intersection(*sets) if sets else set()


def _cpk(rows, boards):
    """(k, any-clean share over `boards`) of one method's rows of every attempt: k is the most
    attempts a board has; a board counts clean when any of its attempts is."""
    by = defaultdict(list)
    for r in rows:
        by[r["board"]].append(r)
    k = max([len(v) for v in by.values()] or [1])
    return k, _mean([1.0 if any(r["clean"] for r in by.get(b, [])) else 0.0 for b in boards])


def paired_table(rows, base, names, repos):
    """Paired A/B of each method against `base` on the boards both ran (haslambench.stats): cp1 and
    cpk by exact McNemar, completion by sign-flip, 95 % CIs by bootstrap over repositories, the
    secondaries Holm-corrected, and the boards that flipped."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "src"))
    from haslambench import stats
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["method"]][r["board"]].append(r)
    out = [f"### Paired against {base}", "",
           "Boards both methods ran (a failed run counts as not clean; boards one has not run yet are left out and counted). "
           "p: exact McNemar for cp1/cpk, sign-flip for completion and cp1_mean; Holm over cp1, cpk, completion; "
           "CI: 95 % bootstrap of B − A resampling repositories. Significant at p < 0.05.", "",
           "| B | boards | not run by one | k | cp1_mean A → B (p) | cp1 A → B | cp1 +/− boards | p cp1 (Holm) | cpk A → B | p cpk (Holm) | "
           "completion A → B | p (Holm) | B − A cp1, 95 % CI | verdict (cp1_mean) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    flips = []
    for n in names:
        if n == base or n not in by:
            continue
        A, B = by[base], by[n]
        boards = sorted(b for b in set(A) & set(B) if not any(r["status"] == "score_error" for r in A[b] + B[b]))
        k = max(len(v) for v in list(A.values()) + list(B.values()))

        def m(arm, f):
            return {b: f(sorted(arm[b], key=lambda r: r["attempt"])) for b in boards}
        c1 = lambda rs: 1.0 if rs[0]["attempt"] == 0 and rs[0]["clean"] else 0.0
        ck = lambda rs: 1.0 if any(r["clean"] for r in rs) else 0.0
        cm = lambda rs: sum(1.0 for r in rs if r["clean"]) / k
        co = lambda rs: (rs[0]["completion"] or 0.0) if rs[0]["attempt"] == 0 else 0.0
        cl = {b: repos.get(b) or b for b in boards}
        t = {"cp1": stats.paired(m(A, c1), m(B, c1), boards, clusters=cl, binary=True),
             "cpk": stats.paired(m(A, ck), m(B, ck), boards, clusters=cl, binary=True),
             "completion": stats.paired(m(A, co), m(B, co), boards, clusters=cl)}
        prim = stats.paired(m(A, cm), m(B, cm), boards, clusters=cl)
        h = dict(zip(t, stats.holm([v["p"] for v in t.values()])))
        lost = len(set(A) ^ set(B))
        out.append(f"| {n} | {len(boards)} | {lost} | {k} | {_f(prim['mean_a'])} → {_f(prim['mean_b'])} ({_f(prim['p'], 4)}) | "
                   f"{_f(t['cp1']['mean_a'])} → {_f(t['cp1']['mean_b'])} | +{len(t['cp1']['gained'])} / −{len(t['cp1']['lost'])} | "
                   f"{_f(t['cp1']['p'], 4)} ({_f(h['cp1'], 4)}) | {_f(t['cpk']['mean_a'])} → {_f(t['cpk']['mean_b'])} | "
                   f"{_f(t['cpk']['p'], 4)} ({_f(h['cpk'], 4)}) | {_f(t['completion']['mean_a'])} → {_f(t['completion']['mean_b'])} | "
                   f"{_f(t['completion']['p'], 4)} ({_f(h['completion'], 4)}) | {_f(t['cp1']['diff'])} [{_f(t['cp1']['ci'][0])}, {_f(t['cp1']['ci'][1])}] | "
                   f"{stats.verdict(prim)} |")
        for key, who in (("gained", n), ("lost", base)):
            for b in t["cp1"][key][:20]:
                loser = (A if key == "gained" else B)[b][0]
                flips.append(f"| {n} | {b} | {who} | {loser['unconnected']} | {loser['errors_by_type']} |")
    if flips:
        out += ["", "cp1 flips (first 20 each way per method): the board, the method clean on it, and what the other's attempt 0 still had.", "",
                "| B | board | clean only in | other's unconnected | other's errors by type |", "|---|---|---|---|---|"] + flips
    return out + [""]


def _xc_cell(rs):
    """xc share of a method's attempt-0 rows (not counted where the input's DRC is unknown), † for a placing method."""
    known = [r.get("xc") for r in rs if r.get("xc") is not None]
    if not known:
        return "—"
    return _f(_mean([1.0 if x else 0.0 for x in known])) + ("" if all(r.get("kind", "route") == "route" for r in rs) else "†")


def method_table(rows, names, title):
    """Per-method table. DRC errors and physics are averaged over the ok runs that have a value, which
    differ by method (a board with no output drops out instead of counting as worst, which favours
    methods that fail on hard boards): each is shown with its board count, and again over the boards
    on which every method has a value, the comparable number."""
    every = rows
    rows = [r for r in rows if r["attempt"] == 0]
    ce, cp = _common(rows, names, "errors"), _common(rows, names, "physics_total")
    out = [f"### {title}", "", "| method | boards | ok | cp1 (clean) | xc (clean net of input; † placing method, not comparable) | k | cpk (any clean) | completion | not closed | DRC errors / board (boards) | "
           f"DRC errors / board, {len(ce)} common boards | "
           "timeouts | no output | errors | CPU s median / p90 / total h | restarts median / p90 | wall s median | "
           f"physics Σu (boards) | physics Σu, {len(cp)} common boards | Σu vs human (median) | module ratio (median) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["method"] == n]
        if not rs:
            continue
        k, cpk = _cpk([r for r in every if r["method"] == n], {r["board"] for r in rs})
        ok = [r for r in rs if r["status"] == "ok"]
        cpu = [r["cpu_s"] for r in rs]
        errs = [r["errors"] for r in ok if r["errors"] is not None]
        phys = [r["physics_total"] for r in rs if r["physics_total"] is not None]
        out.append("| " + " | ".join([
            n, str(len(rs)), str(len(ok)), _f(_mean([1.0 if r["clean"] else 0.0 for r in rs])), _xc_cell(rs), str(k), _f(cpk),
            _f(_mean([r["completion"] if r["completion"] is not None else 0.0 for r in rs])),
            str(sum(1 for r in ok if (r["unconnected"] or 0) > 0)), f"{_f(_mean(errs), 2)} ({len(errs)})",
            _f(_mean([r["errors"] for r in ok if r["board"] in ce]), 2),
            str(sum(1 for r in rs if r["timed_out"] or r["partial"])), str(sum(1 for r in rs if r["status"] == "no_output")),
            str(sum(1 for r in rs if r["status"] in ("adapter_error", "score_error"))),
            f"{_f(_med(cpu), 1)} / {_f(_q(cpu, 0.9), 1)} / {_f(sum(x or 0 for x in cpu) / 3600, 1)}",
            f"{_f(_med([r.get('attempts') for r in rs]), 0)} / {_f(_q([r.get('attempts') for r in rs], 0.9), 0)}",
            _f(_med([r["runtime_s"] for r in rs]), 0),
            f"{_f(_mean(phys), 3)} ({len(phys)})",
            _f(_mean([r["physics_total"] for r in ok if r["board"] in cp]), 3),
            _f(_med([r["physics_vs_human"] for r in rs]), 3),
            _f(_med([r["module_ratio_median"] for r in rs]), 3)]) + " |")
    return out + [""]


def _bus_section(rows, name):
    """Report-only bus scorecard tables when the experiment's runs have them (tools/haslamres/busreport.py)."""
    try:
        import busreport
        return busreport.section_for_experiment(rows, name)
    except ImportError:
        return []


def winnable_table(rows, names, spec=None):
    """cp1 on all boards and on the winnable boards (no placement-type DRC error in the fixed input), side by side, with
    the size of each set. Empty list when no board's fixed input is known. `spec` is only named in the text."""
    rows = [r for r in rows if r["attempt"] == 0]
    flag = {}
    for r in rows:
        flag.setdefault(r["board"], r.get("winnable"))
    if not any(v is not None for v in flag.values()):
        return []
    win, lost, unk = [sorted(b for b, v in flag.items() if v is w) for w in (True, False, None)]
    out = ["### Winnable boards", "",
           f"Winnable: {len(win)} of {len(flag)} boards. {len(lost)} have a placement-type DRC error in the fixed input of their "
           f"task (`place-fixed.input_drc`), so no method can be `clean` on them (`clean` needs a legal placement); "
           f"{len(unk)} have no such task at this experiment's task spec{f' ({spec})' if spec else ''}, so are left out of the winnable set. "
           "The set depends on the task spec (95 boards at spec 8, 100 at specs 9-10, of the 213 merit boards). "
           "Report-only, not a score or a task change.", "",
           "| method | boards | cp1 (all) | winnable boards | cp1 (winnable) | clean on non-winnable |", "|---|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["method"] == n]
        if not rs:
            continue
        ws = [r for r in rs if r.get("winnable") is True]
        ls = [r for r in rs if r.get("winnable") is False]
        out.append(f"| {n} | {len(rs)} | {_f(_mean([1.0 if r['clean'] else 0.0 for r in rs]))} | {len(ws)} | "
                   f"{_f(_mean([1.0 if r['clean'] else 0.0 for r in ws])) if ws else '—'} | {sum(1 for r in ls if r['clean'])} of {len(ls)} |")
    return out + [""]


def legal_h_table(rows, names):
    """Legal placements by the score's `legal` and by legal_h, "not worse than the human" (legal_vs_human), side by
    side. Empty when no run has legal_h."""
    rows = [r for r in rows if r["attempt"] == 0]
    if not any(r.get("legal_h") is not None for r in rows):
        return []
    out = ["### Legal, and not worse than the human layout", "",
           "legal_h (user decision 2026-11-22): for every placement-type DRC error kind, no more errors than the board's "
           "human layout has (the route task's input DRC). On boards whose human layout breaks the board's own rules, "
           "`legal` asks more than the human met. Report-only: `legal` and `clean` are unchanged, and the column is new, "
           "so baselines show it once their reports are regenerated.", "",
           "| method | boards | legal | legal_h | boards without a human DRC |", "|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["method"] == n]
        if not rs:
            continue
        known = [r for r in rs if r.get("legal_h") is not None]
        out.append(f"| {n} | {len(rs)} | {_f(_mean([1.0 if r.get('legal') else 0.0 for r in rs]))} | "
                   f"{_f(_mean([1.0 if r['legal_h'] else 0.0 for r in known])) if known else '—'} | {len(rs) - len(known)} |")
    return out + [""]


def physics_table(rows, names):
    """physics_total beside the valued-only total and how many boards measured anything: a module with no value counts a
    flat 3 in physics_total, and a board with no observation counts only that (E6, E28), so per-board means here use only
    the boards with at least one observation."""
    rows = [r for r in rows if r["attempt"] == 0]
    out = ["### Physics: valued only, and where anything was measured", "",
           "Σu = `physics_total` (modules without a value count 3, 36-56 % of the sum on these boards). Σu valued = the same "
           "sum over the modules that have a value. Boards with no measured module (`observations` 0) are left out of both means; "
           "no module kind in this evaluator is layout-independent, so Σu valued is also the layout-dependent total here "
           "(see Intent physics for intent evaluations). Report-only.", "",
           "| method | boards with physics | observations 0 (left out) | observations / board | Σu mean | Σu valued mean | Σu vs human (median) | Σu valued vs human (median) |",
           "|---|---|---|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["method"] == n and r.get("physics_total") is not None]
        if not rs:
            continue
        seen = [r for r in rs if r.get("physics_observations")]
        out.append(f"| {n} | {len(rs)} | {len(rs) - len(seen)} | {_f(_mean([r['physics_observations'] for r in seen]), 1)} | "
                   f"{_f(_mean([r['physics_total'] for r in seen]), 3)} | {_f(_mean([r['physics_valued_total'] for r in seen]), 3)} | "
                   f"{_f(_med([r.get('physics_vs_human') for r in seen]), 3)} | {_f(_med([r.get('physics_valued_vs_human') for r in seen]), 3)} |")
    return out + [""]


LAYOUT_INDEPENDENT_OBS = ("loss.part",)   # intent observations whose value a layout cannot change (E25: ratio 1.00, sd 0)


def intent_totals(status, ev):
    """(cost total, layout-dependent cost, observations) of one haslam.excite intent evaluation (its status and ev json).
    The cost total is `tiers.cost` (mW_eq); the layout-dependent total leaves out terms of LAYOUT_INDEPENDENT_OBS. None
    where the status has no cost."""
    cost = (status.get("tiers") or {}).get("cost")
    n_obs = len(ev.get("observations") or [])
    if cost is None:
        return None, None, n_obs
    excl = sum(t.get("contribution") or 0.0 for t in status.get("terms") or []
               if t.get("tier") == "cost" and t.get("obs") in LAYOUT_INDEPENDENT_OBS)
    return float(cost), round(float(cost) - excl, 3), n_obs


def intent_table(rows, names, root):
    """Costs of external intent evaluations (`root/<board>/<run or method id or human>.{status,ev}.json`, from
    tools/research/physics/eval_intent.sh), with and without layout-independent terms, per board means only where
    something was measured. Read only with --intent: haslamres does not store these."""
    root = Path(root)
    rows = [r for r in rows if r["attempt"] == 0]
    got = defaultdict(dict)
    for r in rows:
        keys = [r["run"], r["method_id"], r["method_id"][:8]] + (["human"] if r.get("method") == "human" else [])
        d = root / r["board"]
        key = next((k for k in keys if (d / f"{k}.status.json").exists()), None)
        if key:
            got[r["method"]][r["board"]] = intent_totals(read_json(d / f"{key}.status.json") or {}, read_json(d / f"{key}.ev.json") or {})
    out = ["### Intent physics (external evaluations)", "",
           f"From `{root}`. Cost = `tiers.cost` (mW_eq). Layout cost leaves out `{'`, `'.join(LAYOUT_INDEPENDENT_OBS)}`, which a layout cannot "
           "change. Boards with no observation (nothing measured) are left out of the means. Report-only.", "",
           "| method | boards | no observations (left out) | cost mean | layout cost mean | layout cost / human (median, boards measured in both) |",
           "|---|---|---|---|---|---|"]
    hum = got.get("human", {})
    for n in names:
        d = got.get(n)
        if not d:
            continue
        seen = {b: v for b, v in d.items() if v[2] and v[0] is not None}
        ratios = [v[1] / hum[b][1] for b, v in seen.items() if v[1] and b in hum and hum[b][2] and hum[b][1]]
        out.append(f"| {n} | {len(d)} | {len(d) - len(seen)} | {_f(_mean([v[0] for v in seen.values()]), 1)} | "
                   f"{_f(_mean([v[1] for v in seen.values()]), 1)} | {_f(_med(ratios), 3)} |")
    return out + [""]


def mfg_table(rows, names):
    """Manufacturability columns of the runs measured so far (`haslamres mfg submit`; nothing is computed here). Empty when
    no run has them: pour-dependent columns need a zone refill, so this stays out of the normal report."""
    rows = [r for r in rows if r["attempt"] == 0]
    if not any(r.get("mfg_fab_class_jlcpcb") is not None or r.get("mfg_acute_per_m") is not None for r in rows):
        return []
    out = ["### Manufacturability (report-only, not targets)", "",
           "Medians over the measured runs (lower is usually easier to build; copper flags and fab classes are counts). Definitions, "
           "thresholds and limits: `tools/haslamres/README.md`, Manufacturability columns. These are not scoring targets: optimizing "
           "any of them alone makes boards worse. Pour-dependent columns need a refilled measurement (`haslamres mfg submit --refill`), "
           "and all-board medians are confounded by unrouted copper.", "",
           "| method | boards | CA short / m (pours, mm²/m) | width at class min | copper Δ between mirror layers (pp) | copper flags (≥ 20 pp) | "
           "vias in small signal pads (total) | JLCPCB class std / adv / hdi / none | phantom-layer length share (mean over boards measured) | "
           "E[via breakouts, 40 µm] | acute junctions / m |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        rs = [r for r in rows if r["method"] == n and (r.get("mfg_fab_class_jlcpcb") is not None or r.get("mfg_acute_per_m") is not None)]
        if not rs:
            continue
        fc = Counter(r.get("mfg_fab_class_jlcpcb") or "none" for r in rs)
        col = lambda c: [r.get(f"mfg_{c}") for r in rs]
        out.append(f"| {n} | {len(rs)} | {_f(_med(col('ca_short_per_m_pours')), 3)} | {_f(_med(col('width_at_class_min')), 3)} | "
                   f"{_f(_med(col('copper_pair_diff_pp')), 1)} | {sum(1 for x in col('copper_flag') if x)} | {sum(x or 0 for x in col('vip_small_signal'))} | "
                   f"{fc['standard']} / {fc['advanced']} / {fc['hdi']} / {fc['none']} | {_f(_mean(col('phantom_share')), 3)} | "
                   f"{_f(_mean(col('exp_breakout_40um')), 4)} | {_f(_med(col('acute_per_m')), 2)} |")
    return out + [""]


def cmd_exp_report(a):
    e = load_exp(a.name)
    if not getattr(a, "no_watchdog", False):   # the cost watchdog first (a report that fails must not skip it)
        import watchdog
        watchdog.check(a.name, store=STORE)
    d = exp_dir(a.name)
    rows, bugs, fails = exp_rows(e)
    for f in fails:
        bugs += f.get("bugs") or []
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    names = ([human["name"]] if human else []) + [m["name"] for m in e["methods"] if not human or m["id"] != human["id"]]
    fields = list(rows[0].keys()) if rows else ["board"]
    with open(d / "results.csv.tmp", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(d / "results.csv.tmp", d / "results.csv")
    (d / "bugs").mkdir(exist_ok=True)
    with open(d / "bugs" / "index.jsonl.tmp", "w") as f:
        for b in bugs:
            f.write(json.dumps({k: v for k, v in b.items() if k not in ("traceback", "log_tail")}) + "\n")
    os.replace(d / "bugs" / "index.jsonl.tmp", d / "bugs" / "index.jsonl")
    groups = defaultdict(list)
    for b in bugs:
        # older jobs put the board id in prepare signatures; group those by message alone
        sig = b["signature"]
        if sig.startswith("harness:prepare:"):
            sig = re.sub(r"^harness:prepare:\[N<path> [^:]+: ", "harness:prepare: ", sig)
        groups[sig].append(b)
    bl = [f"# Bugs by signature: {a.name}", "",
          f"{len(bugs)} records in {len(groups)} signatures over {len({b['board'] for b in bugs})} boards. Each record is in "
          "`~/haslam-baselines/boards/<board>/runs/<run>/bugs.json` (with tracebacks and log tails; evidence paths are relative "
          "to the run folder), prepare failures in `boards/<board>/prepare-failures/`. All records: `bugs/index.jsonl`.", "",
          "| signature | boards | records | count | example boards | example detail |", "|---|---|---|---|---|---|"]
    for sig, bs in sorted(groups.items(), key=lambda kv: (-len({b["board"] for b in kv[1]}), kv[0])):
        boards = sorted({b["board"] for b in bs})
        bl.append(f"| `{sig[:120]}` | {len(boards)} | {len(bs)} | {sum(b.get('count', 1) for b in bs)} | "
                  f"{', '.join(boards[:3])} | {bs[0]['detail'].splitlines()[0][:160] if bs[0]['detail'] else ''} |")
    (d / "bugs" / "BY-SIGNATURE.md").write_text("\n".join(bl) + "\n")
    total = e["boards"]
    done = len({r["board"] for r in rows})
    ms = {m["id"]: find_method(m["id"]) for m in e["methods"]}
    rep = [f"# Experiment {a.name}", "", e.get("description") or "", "",
           f"Generated {now()}. Boards with results: {done} / {total}; prepare failed: {len(fails)}. "
           f"Harness {e['harness']['commit'][:7]} (prepare, human scoring), haslam {e['haslam']['commit'][:7]} (physics), KiCad {e['kicad']}. "
           f"Evaluators: DRC `{e['evaluators']['drc']}`, physics `{e['evaluators']['physics']}`.", "", "Methods:", ""]
    for m in ms.values():
        code = "; ".join(f"{k} [{c['commit'][:7]}]({c['link']})" if c.get("link") else f"{k} {c['commit'][:7]} (local)"
                         for k, c in m["code"].items())
        rep.append(f"- **{m['name']}** `{m['id']}` {m.get('version') or ''}: {m['recipe']['runner'].get('adapter') or m['recipe']['runner']['type']}, "
                   f"{json.dumps(m['recipe']['params'])}; {code}")
    foreign = sum(1 for r in rows if r["foreign_evaluator"])
    if foreign:
        rep += ["", f"**Note:** {foreign} runs were scored by a different DRC evaluator than this experiment's (reused runs from "
                "an older scorer). Rescore them before comparing numbers."]
    if e.get("_apart"):
        rep += ["", f"**Warning:** on {len(e['_apart'])} boards the methods' runs were made more than {APART_H} h apart "
                "(runs reused from other experiments). Host load moves results by ~14 % on this host (zone-keepout-ab2), "
                "so differences on those boards are not reliable; register replicates and run the arms side by side."]
    rep += ["", "Columns: cp1 = share of boards routed clean (valid, 0 unconnected, 0 DRC errors) on attempt 0; k = the most "
            "attempts a board has; cpk = share of boards with any clean attempt among k (equal to cp1 when k = 1). "
            "xc (clean net of the input) = valid, 0 unconnected, and no DRC error type above its count in the route task's "
            "input DRC (the human placement, copper stripped): the same test restart.py stops on, report-only, `clean` "
            "unchanged. It is meant for route-only methods; a placing method (marked †) moves parts, so the input's errors are "
            "not its to inherit and its xc is not comparable. A method "
            "named *restarts* is wrapped by restart.py, so one of its runs is already the best of its internal restarts "
            "(restarts column): its cp1 is a best-of-N over seeds within one wall budget; completion = "
            "share of initially unconnected items routed (0 for no output); not closed = boards with unconnected items left; "
            "timeouts = stopped at the deadline (partial); CPU s = the method's own processes (router, DSN export, SES import), "
            "not scoring; physics Σu = haslam module physics total (lower is better; modules without a value count 3); Σu vs "
            "human = per-board ratio to the human board's; module ratio = per-board median of method / human module value "
            "over modules routed in both (lower is better). The human method is the original copper scored the same way.", ""]
    rep += method_table(rows, names, "All boards")
    rep += winnable_table(rows, names, harness_task_spec(e["harness"]["commit"]))
    rep += legal_h_table(rows, names)
    nonhuman = [n for n in names if not human or n != human["name"]]
    base = getattr(a, "baseline", None) or (nonhuman[0] if nonhuman else None)
    if base in names and len(nonhuman) > 1:
        rep += paired_table([r for r in rows if r["method"] in nonhuman], base, nonhuman,
                            {r["board"]: r.get("repo") for r in rows})
    rep += method_table([r for r in rows if r["human_clean"]], names, "Boards whose human layout is DRC-clean")
    for sp in ("A", "B", "C"):
        rep += method_table([r for r in rows if r["split"] == sp], names,
                            f"Split {sp} ({'≤ 31' if sp == 'A' else '≤ 100' if sp == 'B' else '> 100'} pads)")
    for lab, test in (("2 layers", lambda n: n == 2), ("4 layers", lambda n: n == 4), ("6+ layers", lambda n: (n or 0) >= 6)):
        rep += method_table([r for r in rows if test(r["layers"])], names, lab)
    rep += physics_table(rows, names)
    if getattr(a, "intent", None):
        rep += intent_table(rows, names, a.intent)
    rep += mfg_table(rows, names)
    rep += ["### DRC error types (errors on ok attempts)", "", "| type | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    per = {n: Counter() for n in names}
    for r in rows:
        if r["status"] == "ok" and r["method"] in per and r["attempt"] == 0:
            per[r["method"]].update(json.loads(r["errors_by_type"]))
    for typ in sorted(set().union(*per.values()), key=lambda t: -sum(per[n][t] for n in names))[:25]:
        rep.append(f"| {typ} | " + " | ".join(str(per[n][typ]) for n in names) + " |")
    rep += _bus_section(rows, a.name)
    rep += ["", "### Router final states", "", "| method | COMPLETED | TIMED_OUT | other | none |", "|---|---|---|---|---|"]
    for m in ms.values():
        fs = Counter((r["final_state"] or "none") for r in rows if r["method_id"] == m["id"] and r["attempt"] == 0)
        other = sum(v for k, v in fs.items() if k not in ("COMPLETED", "TIMED_OUT", "none"))
        rep.append(f"| {m['name']} | {fs['COMPLETED']} | {fs['TIMED_OUT']} | {other} | {fs['none']} |")
    rep += ["", "### Bugs", "", f"{len(bugs)} records, {len(groups)} signatures; top 15 (all: `bugs/BY-SIGNATURE.md`):", ""]
    head = bl.index("| signature | boards | records | count | example boards | example detail |")
    rep += bl[head:head + 2 + 15]
    nondrc = [ln for ln in bl[head + 2:] if ":drc:" not in ln.split("|")[1]]
    rep += ["", f"Not DRC findings (crashes, exceptions, translation and harness bugs), {len(nondrc)} signatures:", "",
            bl[head], bl[head + 1]] + nondrc[:30]
    (d / "REPORT.md").write_text("\n".join(rep) + "\n")
    print(f"wrote {d / 'REPORT.md'}, results.csv ({len(rows)} rows), bugs/ ({len(bugs)} records)")


def cmd_exp_status(a):
    e = load_exp(a.name)
    boards = (exp_dir(a.name) / "boards.txt").read_text().split()
    done = sum(1 for b in boards if not missing(e, b))
    failed = sum(1 for b in boards if prepare_failed(e, b))
    print(f"{a.name}: {done}/{len(boards)} boards complete, {failed} prepare failures")
    subprocess.run(["haslamq", "status", "--owner", f"exp-{a.name}", "--limit", "5"])


def cmd_exp_timer(a):
    e = load_exp(a.name)
    d = Path.home() / ".config" / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    unit = f"haslamres-{a.name}"
    # Reports and the index come from a frozen copy of the commit that installs the timer, not the
    # experiment's own (older) code: report fixes reach running experiments, and no result changes.
    # Not a shared installed copy: another checkout installing its timers would swap it under ours.
    # this checkout's commit (the one whose code runs `install-timer`), not the main repo's: from a worktree
    # the main repo's HEAD is another branch, and its older report had no cost watchdog
    head = git(HERE, "rev-parse", "HEAD")
    if not on_remote(main_repo(), head):
        raise SystemExit(f"HEAD {head[:7]} is on no remote branch: push it first")
    tool = ensure_harness(head, venv=False)[0] / "tools" / "haslamres" / "haslamres.py"
    (d / f"{unit}.service").write_text(
        f"[Unit]\nDescription=haslamres report {a.name}\n\n[Service]\nType=oneshot\nNice=19\n"
        f"ExecStart=/usr/bin/python3 {tool} exp report {a.name}\n"
        f"ExecStartPost=/usr/bin/python3 {tool} index\n")
    (d / f"{unit}.timer").write_text(f"[Unit]\nDescription=haslamres report {a.name} hourly\n\n[Timer]\nOnBootSec=10min\n"
                                     "OnUnitActiveSec=1h\n\n[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{unit}.timer"], check=True)
    print(f"enabled {unit}.timer (stop: systemctl --user disable --now {unit}.timer)")


# ------------------------------------------------------------------ re-evaluation (physics)
def _rephysics_todo(bid, method_ids, pid):
    """Runs of these methods on a board that have an output but no evaluation by physics evaluator pid.
    Place tasks are left out: their routed board is the probe's, which is not stored."""
    return [(d, r) for d, r in board_runs(bid) if r["method_id"] in method_ids and r.get("status") == "ok"
            and (d / "output.kicad_pcb.gz").exists() and not (d / "evals" / f"{pid}.json").exists()
            and _run_kind(r) not in PLACE_KINDS]


_KINDS = {}


def _run_kind(r):
    """The task kind of a run's method (route for the human reference)."""
    if r["method_id"] not in _KINDS:
        _KINDS.update({k: (m.get("recipe") or {}).get("kind") or "route" for k, m in methods().items()})
    return _KINDS.get(r["method_id"], "route")


def _haslamq_active(owner):
    """Names of an owner's queued or running haslamq jobs (read-only look at the queue database)."""
    cfg = read_json(Path.home() / ".haslamq" / "config.json", {})
    dbp = cfg.get("db")
    if not dbp or not os.path.exists(dbp):
        return set()
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True, timeout=30)
    try:
        return {r[0] for r in c.execute("SELECT name FROM jobs WHERE owner=? AND state IN ('queued','running')", (owner,))}
    finally:
        c.close()


def cmd_rephysics_timer(a):
    """Submit an experiment's physics re-evaluation hourly (new boards as the experiment finishes them)."""
    repo = main_repo()
    harness, haslam = git(repo, "rev-parse", a.harness), git(repo, "rev-parse", a.haslam)
    tool = ensure_harness(harness, venv=False)[0] / "tools" / "haslamres" / "haslamres.py"  # frozen: nothing can swap it
    d = Path.home() / ".config" / "systemd" / "user"
    unit = f"haslamres-rephysics-{a.name}"
    (d / f"{unit}.service").write_text(
        f"[Unit]\nDescription=haslamres physics re-evaluation of {a.name}\n\n[Service]\nType=oneshot\nNice=19\n"
        f"Environment=PATH={Path.home() / '.local' / 'bin'}:/usr/local/bin:/usr/bin:/bin\n"
        f"ExecStart=/usr/bin/python3 {tool} rephysics submit {a.name} --harness {harness} --haslam {haslam}"
        + (f" --after {a.after}" if a.after else "") + f" --prio {a.prio}\n")
    (d / f"{unit}.timer").write_text(f"[Unit]\nDescription=haslamres physics re-evaluation of {a.name}, hourly\n\n[Timer]\n"
                                     "OnBootSec=15min\nOnUnitActiveSec=1h\n\n[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{unit}.timer"], check=True)
    print(f"enabled {unit}.timer: harness {harness[:7]}, haslam {haslam[:7]} (stop: systemctl --user disable --now {unit}.timer)")


def cmd_rephysics_submit(a):
    """Queue physics re-evaluation of an experiment's finished boards with a newer physics evaluator
    (new haslam and/or physics_board.py), at low priority. Runs are never re-run: each stored output is
    rebuilt as its scorer did and measured again; the result is a new evaluation beside the old."""
    e = load_exp(a.name)
    repo = main_repo()
    harness, haslam = git(repo, "rev-parse", a.harness), git(repo, "rev-parse", a.haslam)
    for c in (harness, haslam):
        if not on_remote(repo, c):
            raise SystemExit(f"{c[:7]} is on no remote branch: push it first")
    ensure_harness(harness)
    ensure_harness(haslam, haslam=True)
    pid = evaluators_for(harness, haslam, e["kicad"])["physics"]
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    mids = {m["id"] for m in e["methods"]} | ({human["id"]} if human else set())
    rows = corpus_rows()
    boards = (exp_dir(a.name) / "boards.txt").read_text().split()
    if a.only:
        only = set(Path(a.only[1:]).read_text().split() if a.only.startswith("@") else a.only.split(","))
        boards = [b for b in boards if b in only]
    if a.after and not Path(os.path.expanduser(a.after)).exists():
        print(f"waiting for {a.after}; nothing submitted")
        return
    cd = code_dir(harness)
    py = cd.with_name(cd.name + ".venv") / "bin" / "python"
    pending = _haslamq_active(f"rephysics-{a.name}")
    jobs = []
    for bid in boards:
        if f"rephysics-{a.name}:{bid}" in pending:
            continue  # already queued or running
        if bid not in rows or missing(e, bid) or not _rephysics_todo(bid, mids, pid):
            continue  # not finished by the experiment yet, or nothing left to measure
        sz = board_size_mb(rows[bid])
        jobs.append(dict(cmd=f"{py} {cd / 'tools' / 'haslamres' / 'haslamres.py'} rephysics-job --board {bid} --harness {harness} "
                             f"--haslam {haslam} --methods {','.join(sorted(mids))}",
                         name=f"rephysics-{a.name}:{bid}", cpus=2, mem=f"{1.5 + 0.15 * sz:.1f}G", disk=f"{int(100 + 8 * sz)}M",
                         timeout=f"{int(min(12 * 3600, 1800 + 300 * sz))}s", prio=a.prio))
        if a.limit and len(jobs) >= a.limit:
            break
    ev = dict(e["evaluators"])
    if ev.get("physics_current") != pid and not a.dry_run:
        ev.setdefault("physics_history", [ev["physics"]])
        if pid not in ev["physics_history"]:
            ev["physics_history"].append(pid)
        ev["physics_current"] = pid  # reports use it; runs without it yet fall back to their older evaluation
        e["evaluators"] = ev
        write_json(exp_dir(a.name) / "experiment.json", e)
    f = exp_dir(a.name) / f"rephysics-{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    f.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    print(f"physics evaluator {pid} (harness {harness[:7]}, haslam {haslam[:7]}): {len(jobs)} board jobs -> {f}")
    if jobs and not a.dry_run:
        subprocess.run(["haslamq", "submit", "--jobs", str(f), "--owner", f"rephysics-{a.name}", "--tag", f"rephysics-{a.name}",
                        "--live", "--class", "batch", "--cwd", str(cd), "--retries", "1"], check=True)


def cmd_rephysics_job(a):
    bid = a.board
    row = corpus_rows()[bid]
    pid = evaluators_for(a.harness, a.haslam, kicad_version())["physics"]
    todo = _rephysics_todo(bid, set(a.methods.split(",")), pid)
    if not todo:
        print(f"{bid}: nothing to measure")
        return 0
    ws = Path(os.environ.get("HASLAMQ_SCRATCH") or tempfile.mkdtemp(prefix="haslamres-", dir="/var/tmp"))
    size = board_size_mb(row)
    env = dict(os.environ)
    env.update({k: v for k, v in env_sh().items() if k not in env})
    binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
    env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(CORPUS.resolve())]))
    env["KICAD_CONFIG_HOME"] = str(STORE / "kicad-config" / "threads-2")
    env.pop("VIRTUAL_ENV", None)
    log = ws / "job.log"
    cd = code_dir(a.harness)
    kv = code_dir(a.haslam).with_name(code_dir(a.haslam).name + ".venv-haslam")
    pt = board_dir(bid) / "pintypes.json"
    written = 0
    rebuild_errors = []
    groups = defaultdict(list)
    for d, r in todo:
        groups[r["harness_commit"]].append((d, r))
    for hc, items in groups.items():  # rebuild with the harness that scored the runs
        hv = code_dir(hc).with_name(code_dir(hc).name + ".venv")
        man_p = ws / f"rebuild-{hc[:8]}.json"
        rb_py = cd / "tools" / "haslamres" / "rebuild_boards.py"
        if not rb_py.exists():  # harness older than rebuild_boards.py: this haslamres' copy rebuilds the same way
            rb_py = Path(__file__).resolve().with_name("rebuild_boards.py")
        rc, to = run_logged([hv / "bin" / "python", rb_py,
                             "--board-dir", CORPUS / row["path"], "--work", ws / f"rb-{hc[:8]}",
                             *[x for d, r in items for x in ("--run", f"{r['run']}={d / 'output.kicad_pcb.gz'}")],
                             *[x for d, r in items if _run_kind(r) in ("joint", "joint-fixed") for x in ("--joint", r["run"])],
                             "--out", man_p], log, dict(env, PATH=f"{hv / 'bin'}:{env.get('PATH', '')}"), timeout=int(1800 + 120 * size))
        man = read_json(man_p)
        if not man:
            print(f"{bid}: rebuild with harness {hc[:7]} failed (rc {rc}, timed out {to}):\n{tail(log, 30)}", flush=True)
            return 1
        boards = {}
        for d, r in items:
            t = read_json(board_dir(bid) / "tasks" / r["task_id"] / "task.json") or {}
            if (t.get("recipe") or {}).get("board_sha256") not in (None, man["board_sha256"]):
                print(f"{bid}: {r['run']} was made on another board file; skipped", flush=True)
                continue
            got = man["runs"].get(r["run"]) or {}
            if got.get("board"):
                boards[r["run"]] = got["board"]
            elif got.get("error"):
                rebuild_errors.append(f"{r['run']}: {got['error']}")
        if not boards:
            continue
        pout = ws / f"physics-{hc[:8]}.json"
        pb = cd / "tools" / "haslamres" / "physics_board.py"
        run_logged([kv / "bin" / "python", pb, "--input", man["input"],
                    *[x for n, p in boards.items() for x in ("--board", f"{n}={p}")], "--out", pout,
                    *_pintypes_args(pb, pt)], log, env, timeout=int(1800 + 120 * size))
        phys = read_json(pout) or dict(error="physics step failed", log=tail(log, 30))
        for d, r in items:
            if r["run"] not in boards:
                continue
            ph = (phys.get("boards") or {}).get(r["run"]) or dict(error=phys.get("error") or "no result")
            write_json(d / "evals" / f"{pid}.json", dict(
                schema=SCHEMA, evaluator=pid, run=r["run"], at=now(), rescored=True, rebuilt_with=hc,
                pintypes=phys.get("pintypes"), physics={k: v for k, v in ph.items() if k != "traceback"},
                **({"traceback": ph["traceback"]} if ph.get("traceback") else {})))
            written += 1
    print(f"{bid}: {written} physics evaluation(s) by {pid}", flush=True)
    for x in rebuild_errors:
        print(f"{bid}: rebuild failed: {x}", flush=True)
    shutil.rmtree(ws / "w", ignore_errors=True)
    if not written and rebuild_errors:     # exit 0 here reads as "done" to the queue, with nothing measured
        print(f"{bid}: no run could be rebuilt; no physics evaluation written", flush=True)
        return 1
    return 0


# ------------------------------------------------------------------ re-scoring (DRC scorer)
def _rescore_todo(bid, method_ids, eid):
    """Runs of these methods on a board with a stored output and no evaluation by DRC scorer eid."""
    return [(d, r) for d, r in board_runs(bid) if r["method_id"] in method_ids and r.get("status") in ("ok", "score_error")
            and (d / "output.kicad_pcb.gz").exists() and not (d / "evals" / f"{eid}.json").exists()]


def cmd_rescore_submit(a):
    """Queue re-scoring of an experiment's stored runs with the DRC scorer of a harness commit (after a scoring
    change). No method is run: each stored output is scored again on the task its run was made on, and the result
    is a new evaluation beside the old one, never in its place. The experiment's reports then read the new scorer
    (`drc_current`), falling back to the older evaluation for runs not yet re-scored."""
    e = load_exp(a.name)
    repo = main_repo()
    harness = git(repo, "rev-parse", a.harness)
    if not on_remote(repo, harness):
        raise SystemExit(f"{harness[:7]} is on no remote branch: push it first")
    cd, _ = ensure_harness(harness)
    eid = evaluators_for(harness, harness, e["kicad"])["drc"]
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    mids = {m["id"] for m in e["methods"]} | ({human["id"]} if human and a.human else set())
    rows = corpus_rows()
    boards = (exp_dir(a.name) / "boards.txt").read_text().split()
    if a.only:
        only = set(Path(a.only[1:]).read_text().split() if a.only.startswith("@") else a.only.split(","))
        boards = [b for b in boards if b in only]
    py = cd.with_name(cd.name + ".venv") / "bin" / "python"
    owner = f"rescore-{a.name}"
    pending = _haslamq_active(owner)
    jobs = []
    for bid in boards:
        if f"{owner}:{bid}" in pending or bid not in rows:
            continue
        todo = _rescore_todo(bid, mids, eid)
        if not todo:
            continue
        sz = board_size_mb(rows[bid])
        jobs.append(dict(cmd=f"{py} {cd / 'tools' / 'haslamres' / 'haslamres.py'} rescore-job --board {bid} --harness {harness} "
                             f"--methods {','.join(sorted(mids))}",
                         name=f"{owner}:{bid}", cpus=2, mem=f"{1.5 + 0.12 * sz + 0.3 * heap_gb(sz):.1f}G",
                         disk=f"{int(200 + 20 * sz)}M", timeout=f"{int(min(24 * 3600, 1800 + len(todo) * (600 + 240 * sz)))}s",
                         prio=a.prio))
        if a.limit and len(jobs) >= a.limit:
            break
    ev = dict(e["evaluators"])
    if ev.get("drc_current") != eid and not a.dry_run:
        ev.setdefault("drc_history", [ev["drc"]])
        if eid not in ev["drc_history"]:
            ev["drc_history"].append(eid)
        ev["drc_current"] = eid
        e["evaluators"] = ev
        write_json(exp_dir(a.name) / "experiment.json", e)
    f = exp_dir(a.name) / f"rescore-{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    f.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    print(f"DRC scorer {eid} (harness {harness[:7]}): {len(jobs)} board jobs -> {f}")
    if jobs and not a.dry_run:
        subprocess.run(["haslamq", "submit", "--jobs", str(f), "--owner", owner, "--tag", owner, "--live", "--class", "batch",
                        "--cwd", str(cd), "--retries", "1"], check=True)


def cmd_rescore_job(a):
    """One board: score its runs' stored outputs again with harness a.harness's scorer, on the task each run was
    made on (prepared again by the harness that prepared it, from the task cache when it can)."""
    bid = a.board
    row = corpus_rows()[bid]
    eid = evaluators_for(a.harness, a.harness, kicad_version())["drc"]
    todo = _rescore_todo(bid, set(a.methods.split(",")), eid)
    if not todo:
        print(f"{bid}: nothing to re-score")
        return 0
    ws = Path(os.environ.get("HASLAMQ_SCRATCH") or tempfile.mkdtemp(prefix="haslamres-", dir="/var/tmp"))
    src = ws / "src" / bid
    src.mkdir(parents=True, exist_ok=True)
    for p in (CORPUS / row["path"]).iterdir():
        if (p.name.startswith("board.") or p.name == "row.json") and not (src / p.name).exists():
            os.symlink(p, src / p.name)
    size = board_size_mb(row)
    env = dict(os.environ)
    env.update({k: v for k, v in env_sh().items() if k not in env})
    binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
    env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(CORPUS.resolve())]))
    env["KICAD_CONFIG_HOME"] = str(STORE / "kicad-config" / "threads-2")
    env["HASLAM_DRC_TIMEOUT"] = str(900 if size < 20 else 3600)
    env.pop("VIRTUAL_ENV", None)
    log = ws / "job.log"
    cd = code_dir(a.harness)
    py = cd.with_name(cd.name + ".venv") / "bin" / "python"
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    groups = defaultdict(list)
    for d, r in todo:
        kind = _run_kind(r)
        groups[(run_prepared_by(r), r["task_id"], kind)].append((d, r))
    written, failed = 0, []
    for (phc, tid, kind), items in groups.items():
        steps = {}
        task, rc, to = _prepare(bid, phc, sorted({INPUT_KIND.get(kind, kind)}), ws, env, log, steps, f"prepare-{phc[:8]}")
        if task is None:
            failed += [f"{r['run']}: task not prepared (harness {phc[:7]}, rc {rc}, timed out {to})" for _, r in items]
            continue
        man_p = ws / f"rescore-{phc[:8]}-{kind}.json"
        runs = [f"{r['run']}={d / 'output.kicad_pcb.gz'}:{kind}:{1 if human and r['method_id'] == human['id'] else 0}"
                for d, r in items]
        rc, to = run_logged([py, cd / "tools" / "haslamres" / "rescore_runs.py", "--task", task, "--work", ws / "rs",
                             *[x for spec in runs for x in ("--run", spec)], "--out", man_p],
                            log, dict(env, PATH=f"{py.parent}:{env.get('PATH', '')}"), timeout=int(1800 + len(items) * (600 + 240 * size)))
        man = read_json(man_p)
        if not man:
            failed += [f"{r['run']}: scorer failed (rc {rc}, timed out {to}): {tail(log, 5)}" for _, r in items]
            continue
        for d, r in items:
            got = (man.get("runs") or {}).get(r["run"]) or {}
            olds = [j for j in (read_json(p) or {} for p in (d / "evals").glob("*.json"))
                    if j.get("score") is not None and j.get("evaluator") != eid]
            old = max(olds, key=lambda j: j.get("at") or "") if olds else None
            dst = d / "evals" / f"{eid}.json"
            if dst.exists():
                continue   # never overwrite (another job got there first)
            ev = dict(schema=SCHEMA, evaluator=eid, run=r["run"], at=now(), rescored=True, rescored_with=a.harness,
                      task_prepared_by=phc, score_version=man.get("score_version"), status=got.get("status"),
                      error=got.get("error"), score=got.get("score"), scoring_usage=got.get("scoring_usage"),
                      probe=(old or {}).get("probe"), probe_from=(old or {}).get("evaluator") if (old or {}).get("probe") else None)
            for tag, path in (got.get("drc") or {}).items():
                name = {"drc": "drc", "placement": "placement-drc", "routing": "routing-drc"}[tag]
                gz(Path(path), d / "evals" / f"{eid}.{name}.json.gz")
            write_json(dst, ev)
            written += 1
    print(f"{bid}: {written} run(s) re-scored by {eid}", flush=True)
    for x in failed:
        print(f"{bid}: {x}", flush=True)
    shutil.rmtree(ws / "rs", ignore_errors=True)
    return 1 if failed and not written else 0


# ------------------------------------------------------------------ manufacturability measurements (report-only)
def mfg_evaluator(commit, kicad, refill):
    """The evaluator id of tools/haslamres/mfg_board.py at commit (its code, what it reads and the refill, registered)."""
    recipe = dict(type="haslamres-mfg", kicad=kicad, refill=bool(refill),
                  code=tree_ids(commit, ["tools/haslamres/mfg_board.py", "haslam/src/haslam/board", "haslam/src/haslam/route/fab.py"]))
    eid = "mfg-" + ident(recipe)
    p = STORE / "evaluators" / f"{eid}.json"
    if not p.exists():
        write_json(p, dict(schema=SCHEMA, id=eid, name="mfg", recipe=recipe, created=now(),
                           commits=dict(harness=dict(commit=commit, link=github_link("https://github.com/magnetic-trowel/HaslamPCB", commit)))))
    return eid


def _mfg_todo(bid, method_ids, eid):
    """Attempt-0 runs of these methods on a board with an output and no evaluation by evaluator eid (the human layout included)."""
    return [(d, r) for d, r in board_runs(bid) if r["method_id"] in method_ids and r["attempt"] == 0 and r.get("status") == "ok"
            and (d / "output.kicad_pcb.gz").exists() and not (d / "evals" / f"{eid}.json").exists()]


def cmd_mfg_submit(a):
    """Queue manufacturability measurement of an experiment's runs (attempt 0). --refill first fills zones with pcbnew,
    which the pour-dependent columns need; it is optional and kept out of `exp report` because it is the expensive step."""
    e = load_exp(a.name)
    repo = main_repo()
    harness = git(repo, "rev-parse", a.harness)
    if not on_remote(repo, harness):
        raise SystemExit(f"{harness[:7]} is on no remote branch: push it first")
    cd, kv = ensure_harness(harness, haslam=True)
    eid = mfg_evaluator(harness, e["kicad"], a.refill)
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    mids = {m["id"] for m in e["methods"]} | ({human["id"]} if human else set())
    rows = corpus_rows()
    boards = (exp_dir(a.name) / "boards.txt").read_text().split()
    if a.only:
        only = set(Path(a.only[1:]).read_text().split() if a.only.startswith("@") else a.only.split(","))
        boards = [b for b in boards if b in only]
    pending = _haslamq_active(f"mfg-{a.name}")
    jobs = []
    for bid in boards:
        if f"mfg-{a.name}:{bid}" in pending or bid not in rows or not _mfg_todo(bid, mids, eid):
            continue
        sz = board_size_mb(rows[bid])
        jobs.append(dict(cmd=f"{kv / 'bin' / 'python'} {cd / 'tools' / 'haslamres' / 'haslamres.py'} mfg-job --board {bid} --harness {harness} "
                             f"--methods {','.join(sorted(mids))}" + (" --refill" if a.refill else ""),
                         name=f"mfg-{a.name}:{bid}", cpus=2, mem=f"{3 + 0.3 * sz:.1f}G", disk=f"{int(300 + 8 * sz)}M",
                         timeout=f"{int(min(4 * 3600, 1800 + 300 * sz))}s", prio=a.prio))
        if a.limit and len(jobs) >= a.limit:
            break
    f = exp_dir(a.name) / f"mfg-{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    f.write_text("".join(json.dumps(j) + "\n" for j in jobs))
    print(f"mfg evaluator {eid} (harness {harness[:7]}, refill {a.refill}): {len(jobs)} board jobs -> {f}")
    if jobs and not a.dry_run:
        subprocess.run(["haslamq", "submit", "--jobs", str(f), "--owner", f"mfg-{a.name}", "--tag", f"mfg-{a.name}",
                        "--live", "--class", "batch", "--cwd", str(cd), "--retries", "1"], check=True)


def cmd_mfg_job(a):
    """Measure one board's runs and store each as a `mfg` evaluation (a new file beside the run's others; nothing else changes)."""
    bid = a.board
    row = corpus_rows()[bid]
    eid = mfg_evaluator(a.harness, kicad_version(), a.refill)
    todo = _mfg_todo(bid, set(a.methods.split(",")), eid)
    if not todo:
        print(f"{bid}: nothing to measure")
        return 0
    human = next((m for m in methods().values() if m["recipe"]["runner"]["type"] == "reference"), None)
    hd = find_run(bid, human["id"], 0)[0] if human else None
    ws = Path(os.environ.get("HASLAMQ_SCRATCH") or tempfile.mkdtemp(prefix="haslamres-", dir="/var/tmp"))
    env = dict(os.environ)
    env.update({k: v for k, v in env_sh().items() if k not in env})
    binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
    env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(CORPUS.resolve())]))
    env["KICAD_CONFIG_HOME"] = str(STORE / "kicad-config" / "threads-2")
    cd, kv = code_dir(a.harness), code_dir(a.harness).with_name(code_dir(a.harness).name + ".venv-haslam")
    corpus = CORPUS / row["path"]
    written, failed = 0, []
    for d, r in todo:
        w = ws / "m" / r["run"]
        w.mkdir(parents=True)
        with gzip.open(d / "output.kicad_pcb.gz", "rb") as fi, open(w / "board.kicad_pcb", "wb") as fo:
            shutil.copyfileobj(fi, fo)
        for ext in ("kicad_pro", "kicad_dru"):
            if (corpus / f"board.{ext}").exists():
                shutil.copy2(corpus / f"board.{ext}", w / f"board.{ext}")
        out = w / "mfg.json"
        cmd = [kv / "bin" / "python", cd / "tools" / "haslamres" / "mfg_board.py", "--board", w / "board.kicad_pcb", "--out", out]
        if hd is not None and d != hd and (hd / "output.kicad_pcb.gz").exists():
            cmd += ["--human", hd / "output.kicad_pcb.gz"]
        if a.refill:
            cmd.append("--refill")
        rc, to = run_logged(cmd, ws / "job.log", env, timeout=int(1800 + 300 * board_size_mb(row)))
        res = read_json(out)
        if rc != 0 or not res:
            failed.append(f"{r['run']}: rc {rc}, timed out {to}")
            continue
        write_json(d / "evals" / f"{eid}.json", dict(schema=SCHEMA, evaluator=eid, run=r["run"], at=now(), mfg=res))
        written += 1
    shutil.rmtree(ws / "m", ignore_errors=True)
    print(f"{bid}: {written} mfg evaluation(s) by {eid}; {len(failed)} failed", flush=True)
    for x in failed:
        print(f"{bid}: {x}\n{tail(ws / 'job.log', 20)}", flush=True)
    return 1 if failed and not written else 0


# ------------------------------------------------------------------ index
def cmd_index(a):
    """Rebuild index.sqlite: methods, evaluators, tasks, runs and evaluations (a cache; files are the truth)."""
    tmp = STORE / f"index.sqlite.tmp{os.getpid()}"
    c = sqlite3.connect(tmp)
    c.executescript("""
    CREATE TABLE methods(id TEXT PRIMARY KEY, name TEXT, kind TEXT, runner TEXT, version TEXT, json TEXT);
    CREATE TABLE evaluators(id TEXT PRIMARY KEY, name TEXT, json TEXT);
    CREATE TABLE boards(id TEXT PRIMARY KEY, layers INT, footprints INT, nets INT, collection TEXT, license_tier TEXT);
    CREATE TABLE runs(board TEXT, run TEXT, method_id TEXT, method_name TEXT, attempt INT, task_id TEXT, status TEXT,
      runtime_s REAL, cpu_s REAL, max_rss_mb REAL, final_state TEXT, timed_out INT, experiment TEXT, path TEXT,
      PRIMARY KEY(board, run));
    CREATE TABLE evals(board TEXT, run TEXT, evaluator TEXT, clean INT, valid INT, completion REAL, unconnected INT,
      errors INT, errors_by_type TEXT, wl_ratio REAL, via_delta INT, physics_total REAL, physics_modules INT, json TEXT,
      PRIMARY KEY(board, run, evaluator));
    """)
    for m in methods().values():
        c.execute("INSERT INTO methods VALUES(?,?,?,?,?,?)", (m["id"], m["name"], m["recipe"]["kind"], m["recipe"]["runner"]["type"],
                                                               m.get("version"), json.dumps(m)))
    for p in (STORE / "evaluators").glob("*.json"):
        v = read_json(p)
        c.execute("INSERT INTO evaluators VALUES(?,?,?)", (v["id"], v["name"], json.dumps(v)))
    n = 0
    for bd in sorted((STORE / "boards").iterdir()) if (STORE / "boards").exists() else []:
        b = read_json(bd / "board.json") or {}
        c.execute("INSERT OR REPLACE INTO boards VALUES(?,?,?,?,?,?)", (bd.name, b.get("layers"), b.get("footprints"),
                                                                         b.get("nets"), b.get("collection"), b.get("license_tier")))
        for d, r in board_runs(bd.name):
            mu = r.get("method_usage") or {}
            meta = r.get("adapter_meta") or {}
            c.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (bd.name, r["run"], r["method_id"], r["method_name"], r["attempt"], r["task_id"], r["status"],
                       r.get("runtime_s"), method_cpu_s(r), mu.get("max_rss_mb"), (meta.get("router_report") or {}).get("final_state"),
                       int(bool(meta.get("timed_out") or meta.get("partial"))), r.get("experiment"), str(d)))
            for eid, ev in evals_of(d).items():
                s = (ev or {}).get("score") or {}
                ph = (ev or {}).get("physics") or {}
                c.execute("INSERT OR REPLACE INTO evals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (bd.name, r["run"], eid, s.get("clean"), s.get("valid"), s.get("completion"), s.get("unconnected"),
                           s.get("errors"), json.dumps(s.get("errors_by_type") or {}), s.get("wl_ratio"), s.get("via_delta"),
                           ph.get("physics_total"), ph.get("n_modules"), json.dumps(ev)))
            n += 1
    c.commit()
    c.close()
    os.replace(tmp, STORE / "index.sqlite")
    print(f"indexed {n} runs -> {STORE / 'index.sqlite'}")


# ------------------------------------------------------------------ cli
def main():
    ap = argparse.ArgumentParser(prog="haslamres", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    mp = sub.add_parser("method").add_subparsers(dest="sub", required=True)
    s = mp.add_parser("add", help="register a method (its id is the hash of its recipe)")
    s.add_argument("name", help="human-readable name, e.g. 'freerouting 2.5.0'")
    s.add_argument("--description")
    s.add_argument("--reference", action="store_true", help="the human layout (original copper)")
    s.add_argument("--adapter", default="freerouting", help="haslambench built-in adapter")
    s.add_argument("--binary", help="router binary (its install dir is copied into the store)")
    s.add_argument("--command", help="haslambench --command template; {code:NAME} is a frozen checkout of code NAME, "
                   "{venv:NAME} / {py:NAME} its haslam venv / python (made at exp create, readable in the sandbox)")
    s.add_argument("--kind", default="route", help="route | place | joint")
    s.add_argument("--code", action="append", metavar="NAME=PATH[@REF] | NAME=URL@REF",
                   help="a code component; the harness (this repo, HEAD) is added unless given")
    s.add_argument("--harness", help="harness revision this method runs with (default HEAD)")
    s.add_argument("--param", action="append", metavar="K=V")
    s.add_argument("--timeout", type=int, default=900, help="seconds per attempt (adapter methods)")
    s.add_argument("--kicad-threads", type=int, default=2)
    s.add_argument("--build", help="how the binary was built, e.g. a script and ref")
    s.add_argument("--allow-dirty", action="store_true", help="allow uncommitted or unpushed code (snapshot + patch)")
    # cmd_method_add returns the id for `sprint`; the command line exits 0 (sys.exit of a str would exit 1)
    s.set_defaults(f=lambda a: cmd_method_add(a) and None)
    s = mp.add_parser("list")
    s.set_defaults(f=cmd_method_list)
    s = mp.add_parser("show")
    s.add_argument("id")
    s.set_defaults(f=cmd_method_show)
    ep = sub.add_parser("exp").add_subparsers(dest="sub", required=True)
    s = ep.add_parser("create")
    s.add_argument("name"), s.add_argument("--description")
    s.add_argument("--method", action="append", required=True)
    s.add_argument("--boards", help="ids or @FILE (default: the whole corpus)")
    s.add_argument("--attempts", type=int, default=1)
    s.add_argument("--tier", choices=sorted(TIERS), default="sprint",
                   help="sprint: at most 40 CPU-h, no board over 0.5 CPU-h per method-run (estimated from the index); "
                        "ladder and canary lift the limits")
    s.add_argument("--harness", default="HEAD", help="revision for prepare, the human reference and physics briefs")
    s.add_argument("--haslam", default="origin/claude/vigilant-mayer-i91rrr", help="revision with the haslam package (physics)")
    s.add_argument("--env", action="append", metavar="KEY=VALUE",
                   help="job environment that changes no result, e.g. HASLAM_STEP_CACHE=/var/tmp/$USER/step-cache "
                        "(not part of any method's identity)")
    s.add_argument("--reuse-runs", action="store_true",
                   help="allow methods that already have runs from other experiments (made at another time: the report warns)")
    s.set_defaults(f=cmd_exp_create)
    s = ep.add_parser("submit")
    s.add_argument("name"), s.add_argument("--only"), s.add_argument("--limit", type=int)
    s.add_argument("--redo", action="store_true", help="also retry boards whose prepare failed")
    s.add_argument("--tier", choices=sorted(TIERS), help="change the experiment's tier (default: the one it was created with)")
    s.add_argument("--prio", type=int, help="haslamq priority of the jobs (higher runs first; sprint campaigns: 5)")
    s.add_argument("--cpu-cap", type=float, metavar="CPU_H",
                   help="the campaign's CPU-h cap, recorded for the cost watchdog (default: the one recorded before, else "
                        "the tier's limit, 40 per treatment arm for sprint)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_exp_submit)
    s = ep.add_parser("watchdog", help="cost watchdog: project the campaign's CPU from its finished jobs; past its cap, "
                                       "cancel its queued jobs and write why to WATCHDOG.md (tools/haslamres/watchdog.py)")
    s.add_argument("name"), s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_exp_watchdog)
    for n, f in (("status", cmd_exp_status), ("report", cmd_exp_report), ("install-timer", cmd_exp_timer)):
        s = ep.add_parser(n)
        s.add_argument("name")
        if n == "report":
            s.add_argument("--baseline", help="method name the others are paired against (default: the experiment's first)")
            s.add_argument("--no-watchdog", action="store_true", help="do not run the cost watchdog after the report")
            s.add_argument("--intent", metavar="DIR", help="also report external intent evaluations from DIR/<board>/<run>.status.json (tools/research/physics/eval_intent.sh)")
        s.set_defaults(f=f)
    s = sub.add_parser("sprint", help="a sprint experiment in one command: arms against the tag's stored control")
    s.add_argument("name", help="experiment name; its folder must hold a PLAN.md")
    s.add_argument("--base", choices=sorted(SPRINT_BASES), required=True, help="which control recipe the arm is: bridge | staged")
    s.add_argument("--commit", required=True, help="pushed commit with the change (the baseline tag plus one change)")
    s.add_argument("--set", action="append", metavar="KEY=VALUE", help="haslam setting of every arm (repeatable)")
    s.add_argument("--arm", action="append", metavar="NAME:K=V[,K=V]",
                   help="a named treatment arm with its own settings (repeatable: several arms in one campaign; "
                        "the total limit is per arm); without it, one arm of --set")
    s.add_argument("--suite", help="one suite: a file in bench/suites/ or bench/suites/mech/ (default: sprint-frontier + "
                                   "sprint-quality, when they fit the limits)")
    s.add_argument("--attempts", type=int, help="seeds 0..N-1 (default: all the control stores)")
    s.add_argument("--skip-over-cap", action="store_true",
                   help="leave out the suite's boards whose control runs cost over the per-board limit (recorded)")
    s.add_argument("--allow-over-cap", metavar="REASON",
                   help="keep boards over the per-board limit because the question needs them; the reason is recorded")
    s.add_argument("--smoke", type=int, metavar="N", help="submit only N cheap boards now; the rest with exp submit later")
    s.add_argument("--param", action="append", metavar="K=V",
                   help="method parameter of every arm over the control's (repeatable; e.g. parallel=8: the queue "
                        "reserves 8 CPUs for an arm whose router runs 8 threads)")
    s.add_argument("--cpu-cap", type=float, metavar="CPU_H", help="the campaign's CPU-h cap for the cost watchdog "
                   "(default: 40 per treatment arm, the sprint limit)")
    s.add_argument("--note", help="appended to every arm's method description (e.g. a stage that runs on wall clock)")
    s.add_argument("--control", default="control-w48", help="the tag's stored control experiment")
    s.add_argument("--control-method", metavar="ID", help="which of the control experiment's methods is the control (default: "
                   "its first of the base's kind); the BGA baseline: --control hybrid-bga-w47 --control-method <hybrid id> "
                   "(bench/suites/README.md)")
    s.add_argument("--dry-run", action="store_true", help="register and create, write the job file, submit nothing")
    s.set_defaults(f=cmd_sprint)
    s = sub.add_parser("job", help="one board (what each queued job runs)")
    s.add_argument("--experiment"), s.add_argument("--board", required=True)
    s.add_argument("--method", action="append", help="run these methods (default: the experiment's missing ones)")
    s.add_argument("--attempt", type=int, default=0)
    s.add_argument("--harness"), s.add_argument("--haslam")
    s.add_argument("--repro", action="store_true", help="write a reproduction next to the original run")
    s.add_argument("--content-only", action="store_true",
                   help="only prepare the tasks and record their content and that of the methods' older tasks")
    s.set_defaults(f=cmd_job)
    s = sub.add_parser("bus", help="report-only bus scorecard over stored runs: bus submit | report (tools/haslamres/busreport.py)")
    s.set_defaults(f=lambda a: subprocess.call([sys.executable, str(HERE / "busreport.py"), *a.rest]))
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s = sub.add_parser("board", help="every run and score of one board")
    s.add_argument("id")
    s.set_defaults(f=cmd_board)
    s = sub.add_parser("rerun", help="how to reproduce a run; --submit queues the reproduction")
    s.add_argument("run"), s.add_argument("--submit", action="store_true")
    s.set_defaults(f=cmd_rerun)
    rp = sub.add_parser("rephysics", help="re-evaluate physics of an experiment's runs with a newer evaluator").add_subparsers(dest="sub", required=True)
    s = rp.add_parser("submit")
    s.add_argument("name"), s.add_argument("--only"), s.add_argument("--limit", type=int)
    s.add_argument("--harness", default="HEAD", help="revision whose physics_board.py and rebuild_boards.py run")
    s.add_argument("--haslam", required=True, help="revision with the haslam package to measure with")
    s.add_argument("--prio", type=int, default=-1)
    s.add_argument("--after", help="submit nothing until this file exists (e.g. the pin types' pass marker)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_rephysics_submit)
    s = rp.add_parser("install-timer", help="submit hourly as the experiment finishes boards")
    s.add_argument("name"), s.add_argument("--harness", required=True), s.add_argument("--haslam", required=True)
    s.add_argument("--after"), s.add_argument("--prio", type=int, default=-1)
    s.set_defaults(f=cmd_rephysics_timer)
    rs = sub.add_parser("rescore", help="score an experiment's stored runs again with a newer DRC scorer (no method re-run)").add_subparsers(dest="sub", required=True)
    s = rs.add_parser("submit")
    s.add_argument("name"), s.add_argument("--only"), s.add_argument("--limit", type=int)
    s.add_argument("--harness", default="HEAD", help="revision whose scorer runs (bench/src/haslambench)")
    s.add_argument("--human", action="store_true", help="also re-score the human layout's runs")
    s.add_argument("--prio", type=int, default=-1)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_rescore_submit)
    s = sub.add_parser("rescore-job", help="one board's re-scoring (what each queued job runs)")
    s.add_argument("--board", required=True), s.add_argument("--harness", required=True)
    s.add_argument("--methods", required=True)
    s.set_defaults(f=cmd_rescore_job)
    s = sub.add_parser("rephysics-job", help="one board's physics re-evaluation (what each queued job runs)")
    s.add_argument("--board", required=True), s.add_argument("--harness", required=True), s.add_argument("--haslam", required=True)
    s.add_argument("--methods", required=True)
    s.set_defaults(f=cmd_rephysics_job)
    mp = sub.add_parser("mfg", help="manufacturability measurements of an experiment's runs (report-only)").add_subparsers(dest="sub", required=True)
    s = mp.add_parser("submit", help="queue them, one haslamq job per board with runs still unmeasured")
    s.add_argument("name"), s.add_argument("--harness", default="HEAD", help="commit of mfg_board.py (default: this checkout's HEAD)")
    s.add_argument("--refill", action="store_true", help="fill zones first (pcbnew); needed by the pour-dependent columns")
    s.add_argument("--only", help="comma-separated board ids or @file"), s.add_argument("--limit", type=int), s.add_argument("--prio", type=int, default=0)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(f=cmd_mfg_submit)
    s = sub.add_parser("mfg-job", help="one board's manufacturability measurements (what each queued job runs)")
    s.add_argument("--board", required=True), s.add_argument("--harness", required=True), s.add_argument("--methods", required=True)
    s.add_argument("--refill", action="store_true")
    s.set_defaults(f=cmd_mfg_job)
    s = sub.add_parser("index", help="rebuild index.sqlite")
    s.set_defaults(f=cmd_index)
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
