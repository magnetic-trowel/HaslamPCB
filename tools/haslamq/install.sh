#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Put `haslamq` on PATH (~/.local/bin) and report which isolation features work here.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p ~/.local/bin
# a stable copy: the daemon must not change (or vanish) when this checkout switches branches
mkdir -p ~/.local/share/haslamq
install -m 755 "$here/haslamq.py" ~/.local/share/haslamq/haslamq.py
rm -rf ~/.local/share/haslamq/haslamqlib && mkdir -p ~/.local/share/haslamq/haslamqlib
install -m 644 "$here"/haslamqlib/*.py ~/.local/share/haslamq/haslamqlib/
install -m 755 "$here/haslamqtop.py" ~/.local/share/haslamq/haslamqtop.py
install -m 644 "$here/relay.md" ~/.local/share/haslamq/relay.md   # the relay session's instructions (haslamq dispatch)
# what is deployed: commit, branch, local changes, whether main has it (haslamq doctor, haslamqtop, the daemon's health check)
python3 - "$here" <<'PY'
import json, subprocess, sys, time, os
here = sys.argv[1]
g = lambda *a: subprocess.run(["git", "-C", here, *a], capture_output=True, text=True)
sha = g("rev-parse", "HEAD").stdout.strip()
rec = dict(sha=sha, branch=g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
           dirty=bool(g("status", "--porcelain", "--", ".").stdout.strip()),
           in_main=g("merge-base", "--is-ancestor", sha, "origin/main").returncode == 0 if sha else None,
           installed_at=time.time())
with open(os.path.expanduser("~/.local/share/haslamq/DEPLOYED.json"), "w") as f:
    json.dump(rec, f)
print(f"deployed {sha[:7]} ({rec['branch']}{', local changes' if rec['dirty'] else ''}"
      f"{', in main' if rec['in_main'] else ', NOT in main'})")
PY
ln -sf ~/.local/share/haslamq/haslamq.py ~/.local/bin/haslamq
ln -sf ~/.local/share/haslamq/haslamqtop.py ~/.local/bin/haslamqtop
# user-level skill: sessions in any repo/branch get the usage text
mkdir -p ~/.claude/skills/haslamq
cp "$here/../../.claude/skills/haslamq/SKILL.md" ~/.claude/skills/haslamq/SKILL.md
~/.local/bin/haslamq doctor
echo "Optional, survives reboots/logouts: haslamq install-service. After updating haslamq.py, re-run this and: systemctl --user restart haslamq"
