<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Connection ledger (`ledger.py`)

Scope: a report-only ledger of every open connection of every run of a kaeres experiment, with its
diagnosed cause. Not here: the store itself -> [README.md](README.md); the diagnosis ->
`kae/src/kae/route/blocked.py`.
Keys: connection ledger, open connections, unconnected items, cause taxonomy, blocked, congestion, own copper,
walled in, rule-blocked, inherited opens, reach, persistence, coverage

It reads the store (`$KAE_RESULTS`, else `~/kae-baselines`) read-only, changes no score and writes
nothing into run folders.

```bash
python3 tools/kaeres/ledger.py build --experiment s2-merit213 --methods 90a34137,f596297c \
    --tags <board-tags dir> --out ledger-s2      # ledger.jsonl, runs.jsonl, ledger.json
python3 tools/kaeres/ledger.py report ledger-s2 --pair 90a34137,f596297c   # ledger-s2/LEDGER.md
python3 tools/kaeres/ledger.py reach ledger-s2 --a 90a34137 --b f596297c   # markdown on stdout
```

Methods are ids, id prefixes or names. `--evaluator` picks a DRC evaluator other than the experiment's.
`--tags` points at a board-tags directory with `bus/buses.jsonl` (bus kind, swap class); without it the
bus columns are empty. One build of 5 methods x 211 boards takes about 20 s on one core.

## Rows

`ledger.jsonl`, one row per open connection (`unconnected` of the stored evaluation):

| field | meaning |
|---|---|
| `board`, `method_id`, `method`, `run`, `attempt` | the run |
| `net`, `a`, `b` | net and the two DRC end items (`ref`, `pad`, `kind` pad/track/via/zone/other, `pos`) |
| `source` | `drc` (item list of the stored evaluation), `blocked` (a diagnosis record; no DRC list stored; far end unknown), `count` (neither names it) |
| `status` | `diagnosed`, `undiagnosed` (the run has a `blocked` block but the connection cap or deadline stopped it), `not_attempted` |
| `cause`, `cause_detail` | `kae.route.blocked` cause and its binding constraint, walls, fixed nets or own-copper shape |
| `cause_class` | disjoint class: `inherited`, `geometry`, `rule`, `kae_default`, `fixed_copper`, `pour_island`, `congestion`, `undiagnosed_cap`, `no_diagnosis_stored` |
| `cause_origin` | cause from `restart-report-origin.json` when the kept board has none (an earlier board state) |
| `role`, `zone_net`, `bus`, `swap_class` | ground/power/signal by name (a non-ground net with a zone is power); tag census |
| `island_pads`, `island_kinds`, `island_part_pads` | the stranded island of the diagnosis and its largest part |
| `a_part_pads`, `a_size`, `b_part_pads`, `b_size` | pads of the end parts; size class `>=16`, `3-15`, `2` |
| `board_pads`, `board_layers`, `board_size`, `run_opens` | board size class `<=200`, `201-1000`, `>1000` |
| `inherited` | `pad` (an end pad is open in the task's human DRC), `net` (only the net is), `false`, `null` (no human DRC) |
| `zone_involved` | a zone end item, or a pour fill in the stranded island |

`runs.jsonl` has one row per run, also with zero opens: opens, `drc_list`, `drc_items`, `blocked_source`,
`has_blocked`, `records`, `undiagnosed`, `origin_blocked`, `human_opens`, `diagnosed`, `capped`,
`not_attempted`, board size. Coverage and reach are queries over it.

## Report

`LEDGER.md`: coverage per method; disjoint taxonomy over all opens, boards up to 1,000 pads and near-miss runs
(1-5 opens); share of diagnosed opens by raw cause; cause x net role and x island part size; end sizes of
pad-to-pad opens; persistence for `--pair` (boards where both runs name every open); concentration (boards
holding 50 % and 80 % of each class); the unclassified share against the 30 % line.

## Limits

- The DRC item list is stored only for route-kind runs, and cut at 499 items; staged and joint opens are
  known only through `blocked` records, which name the smaller island only.
- `blocked` is missing from "last mile only" kept boards and from critical+bridge reports, and stops at 60
  connections or its deadline. Matching a DRC item to a record is by net and a shared pad, else by order.
- Net role is a name regex; part sizes count `(pad` entries per footprint of the output board.
- `fill-drc` (re-running the DRC of staged/joint output boards into a separate cache) is not built; see
  [NOTES.md](NOTES.md).
