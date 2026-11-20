# Conflict-set closure: state and what is missing

Module: `kae/src/kae/route/closure.py` (docstring has the design). Setting `closure` (default 0) and its knobs
`closure_whole_net_items`, `closure_orders`, `closure_max_nets`, `closure_depth`, `closure_max_opens` live in
`constraints.DEFAULTS`; set them with a `KAE_CLOSURE` project text variable, env `KAE_CLOSURE=1`, or
`--set closure=1` on `python -m kae.route.cli lastmile` / the bridge (the opts reach `lastmile.close` through
`repair._last_mile`). With it off, `close` never imports or calls the module.

## Where it runs

At the end of every rip-up `lastmile.close` (not the free-joins round), on the nets that close was given, when
they hold 1..`closure_max_opens` missing connections, within close's own `deadline` (the `kae.budget` clock).
That covers the in-attempt last mile and `bridge.last_mile_only` (the `--final` pass). Its report is
`close(...)["closure"]` = {records, added, open_before, open_after, skipped}; `repair._last_mile` copies it into
the round's record as `closure`.

## Known gaps (v1)

- If close's join loop uses its whole deadline, closure gets no time (records `time`). A reserved share of the
  deadline for closure is not implemented.
- Junction runs: `_run` stops at a pad or where more than two items meet at an end; vias in the middle of a run
  are followed, track-to-track T-joins in a segment's middle are not seen as junctions.
- The legality check is the Space's (`_legal`); KiCad's DRC in `repair._last_mile` remains the judge of the round.
- Extension (depth) adds the most-failing connection's conflict nets outside S once per level; it does not
  re-shrink them.
- Test (i) is the last-mile fixture's +3V3 wall (ripping it opens +3V3 connections that are re-routed in the same
  joint solve), not a purpose-built puzzle where the sequential rip-up provably fails.
- `journal.py` is not used: `close` does not journal through it; the transaction uses `sp.remove` / `_restore`.

## Micro test (checkpoint replay on the stored BR near-miss boards)

Driver: `tools/kaeres/experiments/d4-closure/closure_micro.py BOARD ARM [TIME]`, one board and arm per call
(control = `kae.route.cli lastmile`, closure = the same with `--set closure=1`, both 120 s, counted-work
budget), DRC by kicad-cli before and after; writes `$D4/micro/<board>/<arm>/result.json`. `$D4` is the
design-4 folder of the gap audit (it holds `cs_near.json` and `work/<board>/in-BR/`, built by `cs_run.py`).
Boards: the BR entries of `cs_near.json` with a congestion cause and a rebuilt input (11 boards, 22 jobs).

```bash
source ~/.cache/kaebench/env.sh
for b in $(python3 -c "import json,os; D=os.environ['D4']; print(' '.join(x['board'] for x in json.load(open(D+'/cs_near.json'))['BR'] if 'congestion' in x['causes'] and os.path.exists(f\"{D}/work/{x['board']}/in-BR/board.kicad_pcb\")))"); do
  for arm in control closure; do
    echo "bash -c 'ulimit -v 40000000; \$PY $PWD/tools/kaeres/experiments/d4-closure/closure_micro.py $b $arm 120'"
  done
done > cmds.txt
kaeq submit --batch cmds.txt --cpus 1 --mem 4G --timeout 20m --prio 5 --class timed --owner d4-closure-micro \
  --live --cwd "$D4" --env D4="$D4" --env PY="$(command -v python)" --env KAE_KICAD_WRAP="$KAE_KICAD_WRAP" \
  --env APPTAINER_BIND="$APPTAINER_BIND" --env KAE_SRC="$PWD/kae/src" --env KAE_BUDGET=work \
  --env PYTHONHASHSEED=0 --env KAE_WORKERS=1 --env OMP_NUM_THREADS=1
```

Then tabulate `micro/*/*/result.json` (opens before/after, errors, clean, seconds, closure records) into
`$D4/closure_micro.md`. A first submission of these 22 jobs went into the queue at the end of the build session;
check `$D4/micro/` for results before resubmitting.
