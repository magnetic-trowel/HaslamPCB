# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `rules` commander as an external chooser (protocol kae.commander-ask/1, tools/commander/commander.py).

Reads one JSON object on stdin, writes one on stdout: the first menu item whose knob kind is "set" or
"flag", effect "full", scorer allowed and not tried yet, with its --set pieces for the run's kind.
"""
import json
import sys


def choose(ask):
    kind = ask.get("kind") or "route"
    tried = set(ask.get("tried") or [])
    for it in ask.get("menu") or []:
        knob = it.get("knob") or {}
        if (knob.get("kind") not in ("set", "flag") or knob.get("effect") != "full"
                or (it.get("price") or {}).get("scorer", "allowed") != "allowed" or it.get("id") in tried):
            continue
        piece = knob.get(kind) or []
        sets = [piece[i + 1] for i in range(len(piece) - 1) if piece[i] == "--set"]
        if sets:
            return {"choose": it["id"], "set": sets, "reason": f"first eligible item (rank {it.get('rank')})"}
    return {"choose": None, "set": [], "reason": "no eligible item"}


if __name__ == "__main__":
    print(json.dumps(choose(json.loads(sys.stdin.read()))))
