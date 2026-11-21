#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# TraceMaker as a route-only `kaebench run --command` method (or a kaeres --command method):
#   tm_route.sh {input} {output} {workdir} SECONDS [extra `tracemaker route` options]
# {input} is the task's stripped board with its .kicad_pro/.kicad_dru beside it; TraceMaker reads the board and
# both rules files itself (no DSN). SECONDS is TraceMaker's --time: each portfolio variant's wall-clock limit
# (its published protocol is 120 s with --threads 8: 8 variants at once, the best kept). The judge is the
# harness's kicad-cli DRC on the rebuilt board, never TraceMaker's own summary.
#
# Environment: KAE_TRACEMAKER (binary; default the newest $KAE_HOME/tracemaker-*/bin/tracemaker),
# KAE_TM_THREADS (default 8; without --work it is also the portfolio size, so keep it fixed across boards). Its summary (tm.json) and designer report (tm-report.md: what is
# open and why, the rules read and not read) are written to {workdir}.
set -uo pipefail
in=$1 out=$2 dir=$3 secs=$4; shift 4
TM=${KAE_TRACEMAKER:-$(ls -d "${KAE_HOME:-$HOME/.cache/kaebench}"/tracemaker-*/bin/tracemaker 2>/dev/null | tail -1)}
[ -x "$TM" ] || { echo "tm_route: no TraceMaker binary (set KAE_TRACEMAKER)" >&2; exit 2; }
threads=${KAE_TM_THREADS:-8}
cat "$(dirname "$TM")/../SOURCE" 2>/dev/null | sed 's/^/tracemaker source: /'
set -x
"$TM" route "$in" -o "$out" --time "$secs" --threads "$threads" --no-gpu --no-kb \
  --json "$dir/tm.json" --report "$dir/tm-report.md" "$@"
rc=$?
set +x
# the summary lines the trial reads from the adapter log (the work directory is not kept): what was routed by which
# variant, the rules TraceMaker could not read, and its stuck reasons
[ -f "$dir/tm.json" ] && python3 -I - "$dir/tm.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
keep = ("connections", "routed", "open", "vias", "variant", "variant_name", "seconds", "time_limited", "work", "work_all_variants",
        "copper_layers", "pitch_mm")
print("tm-summary " + json.dumps({k: d.get(k) for k in keep}))
r = d.get("rules") or {}
print("tm-rules " + json.dumps(dict(files=r.get("files"), custom_rule_count=r.get("custom_rule_count"), not_read=r.get("not_read"))))
print("tm-variants " + json.dumps(d.get("variants"))[:4000])
print("tm-stuck " + json.dumps(d.get("stuck"))[:4000])
for f in (d.get("failures") or [])[:200]:
    print("tm-open " + f)
EOF
# 3 = connections left open: the board is still a result for the judge
[ "$rc" -eq 3 ] && rc=0
[ -f "$out" ] || { echo "tm_route: no output (rc $rc)" >&2; exit "${rc/#0/1}"; }
exit "$rc"
