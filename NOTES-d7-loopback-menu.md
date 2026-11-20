# NOTES: d7-loopback-menu (priced loop-back menu)

Status: built and tested; not hooked into the bridge or the joint loop (by design for this task).

## What is here
- `kae/src/kae/commander/menu.py`: `build_menu(reports, board=None, opts=None, drc=None)` (pure) and the CLI
  `python -m kae.commander.menu REPORT [REPORT ...] [--board PCB] [--drc JSON] [--task route] [--top N] [--out FILE]`.
  Catalogue items 1-12 of the design plus `thermal_corridor` (added after the tally: kae-default bindings by
  kae's thermal-spoke corridors carry no override; `thermal_repair=false` is the knob, a trade-off).
- `board_summary(path)`: the repo's s-expression reader (no pcbnew); pad counts, sides, pad positions, copper
  layer count; feeds `rotation_hpwl` (rotate_part evidence) and `flip_part`.
- `kae/tests/test_commander_menu.py` (11 tests): each cause, persistence over 3 reports, deterministic bytes,
  every open accounted for, knob keys present in `bridge.DEFAULT_OPTS` / `constraints.DEFAULTS` / escape.py,
  route + joint + standalone diagnosis, board rotation/flip, DRC-only input, CLI.
- `docs/topics/workflow/loopback-menu.md` (linked from docs/INDEX.md).

## TODO (not done)
- One-line hook (not added: bridge.py is being edited by another agent). In `kae/src/kae/route/bridge.py`
  `route()`, in the `finally:` block after `report["opts"] = ...`:
  `report["loopback_menu"] = __import__("kae.commander.menu", fromlist=["x"]).build_menu([report])` (wrap in
  try/except like the diagnosis; joint: the same on `rep` in kae/src/kae/joint/loop.py after `_final_blocked`).
- `more_effort` gain constants (0.3 after a time stop, 0.1 otherwise) are priors; replace with the measured share
  of opens a resume/restart closed (results store: attempts of one restart portfolio).
- Gain is "opens the item could act on", not "opens it closes": no item is A/B tested. Ready for a sprint per
  item, e.g. arm `--set neckdown=true` on boards where the menu ranks neckdown first.
- Without `--board`, a part's pad count is a proxy (largest numeric pin, or ball names like A12 count as big).
- `--task route` marks placement items forbidden by the scorer; the default assumes a joint/place-capable task.
- flip_part only for the big target part on single-sided boards (small parts between opens: too geometric for v0).
- The tally's multi-run section mixes methods (all stored runs of a board), so its persistence is across
  methods, not seeds of one method.

## Tally over stored reports (results store, 200 boards, sha1 order of board id, first run per board)
```
boards sampled (sha1 order of board id, first report per board): 200; reports read 2423
reports with a non-null blocked dict: 593/2423; boards whose first report has one: 62/200
boards with open connections: 84; diagnosed connections 832; DRC opens (sum) 5032
connections by cause: {'congestion': 579, 'geometry': 155, 'rule': 91, 'kae default': 5, 'fixed copper': 2}
boards with opens but no diagnosis in the report (blocked null): 22
diagnosed connections no specific item addresses (unactionable): 195/832 = 0.234; by cause {'geometry': 126, 'congestion': 69}
connections the diagnosis skipped (undiagnosed, its max_conns/deadline): 1182
share of all DRC opens with a specific item: 0.127 (637/5032); the rest have only more_effort
top-ranked menu item: {'more_effort': 46, 'neckdown': 23, 'placement_room': 12, 'move_part': 2, 'planes_allow': 1}
top-ranked menu item other than more_effort: {'(only more_effort)': 46, 'neckdown': 23, 'placement_room': 12, 'move_part': 2, 'planes_allow': 1}
top-ranked ask item: {'pin_swap': 63, 'rule_relax': 18, 'grow_outline': 2, 'release_fixed_copper': 1}
boards with >= 2 stored runs (menu over ALL stored runs of the board, any method, N = runs): 84
  top item: {'neckdown': 26, 'placement_room': 23, 'more_effort': 21, 'move_part': 13, 'planes_allow': 1}
  connections open in every run: 188 of 2669 distinct; boards with a part open in every run: 26
seconds 13.1
```
Headline: only 31 % of stored reports carry a diagnosis (593/2423) and the diagnosis stops at 60 connections per
board, so 87 % of DRC opens get no specific item (only more_effort). Among diagnosed connections, 77 % map to an
item; the 23 % left are mostly `geometry` (walled in by no-net copper or pads, where only an input edit helps).
When a specific item tops, it is neckdown (congestion at big parts) or placement_room (congestion spread out).
