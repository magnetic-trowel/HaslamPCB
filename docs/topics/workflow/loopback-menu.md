# Loop-back menu

Scope: `kae.commander.menu`, which turns kae's failure reports into a ranked list of earlier decisions to revisit, each with its knob. Not here: why a connection is open -> `kae/src/kae/route/blocked.py`; the expert steps -> [expert-state-machine.md](expert-state-machine.md).
Keys: loop-back menu, kae.commander, build_menu, kae.loopback-menu/1, persistence, gain, price, knob, ask, unactionable, more_effort

## What it is

When routing leaves opens, kae can only repair or re-seed. The menu lists the earlier decisions an expert would revisit. The outside commander picks one; kae never does.

- Input: reports of one board. Accepted forms: route report, joint report (`final.blocked`), results store `restart-report.json`, `python -m kae.route.blocked --out`. Optional: the board file (`--board`, read with `kae.board.kicad_file`) and a kicad-cli DRC JSON (`--drc`).
- Pure and deterministic: no router, no pcbnew; same input, same bytes.
- CLI: `python -m kae.commander.menu REPORT... [--board PCB] [--drc JSON] [--task route] [--top N] [--out FILE]`.

## Schema

`{schema: "kae.loopback-menu/1", board, n_reports, opens, persistence{connections, parts, n_reports}, menu, ask, unactionable}`

- `persistence`: the share of reports in which the connection key `(net, pads)` is open. Part persistence: the share of reports with an open on the part, plus the mean count.
- Item fields: `id, decision, expert_state, target, evidence, gain, price{fab_class, fab_cost, assembly_usd, plane_loss, scorer}, knob{kind, route, joint, place, effect}, score, rank`.
- `gain`: the persistence-weighted count of opens the item could act on.
- `score = gain / factor`, with factors advanced 2.0, hdi 4.0, plane loss 1.5, first bottom-side part 1.5. Score is 0 when the benchmark scorer forbids the change (`bench/src/kaebench/score.py`).
- `menu`: items with a knob the scorer allows, ranked by score; ties follow catalogue order. `ask`: all other items.
- `unactionable`: opens that no specific item addresses, by cause.

## Catalogue

| id | trigger | knob today |
|---|---|---|
| kae_default | kae binding with an override | `--set <override>` |
| thermal_corridor | kae spoke corridor binds | `thermal_repair=false` |
| neckdown | width or clearance at a pad; congestion at a 20+ pad part | `neckdown=true` |
| pad_shape | `pad_shape` binds | `pad_shapes=outside` |
| planes_allow | certificate plane relaxation; congestion with costed planes | `planes=allow` |
| via_in_pad | certificate via-in-pad relaxation | `escape_via_in_pad=true`, plan only |
| rule_relax | cause `rule`; certificate rule relaxations | none (ask, with the KiCad edit) |
| release_fixed_copper | cause `fixed copper` | none (joint: `--no-modules`) |
| rotate_part, move_part | 3+ weighted opens on a big part; persistence 0.8+ | edit input, then `kae place --fix` |
| flip_part | same part, single-sided board | none; 34 USD assembly |
| placement_room | congestion spread over parts | joint `place_margin=-1`, `escape_band=1` |
| add_layers, grow_outline | layer relaxation; geometry at the edge | none (scorer forbids) |
| pin_swap | static entry | none; gain null |
| more_effort | always | `rounds=auto`, resume, restart |

- `more_effort` gain: opens × 0.3 after a time stop, else × 0.1 (priors, not measured).
- Route takes `--set k=v`. Joint takes the bare key for placement keys, else `bridge.k`.

## No knob today

- Per-part rotate, move or flip.
- Laying the via-in-pad escape plan.
- Releasing the input's pre-routes.
- Pin swap.
- Rule, layer and outline changes (by design).

## Stored-report tally (2026-11-20, 200 boards)

- 62 of 200 reports carry a diagnosis.
- On the 84 boards with opens, 832 diagnosed connections stand against 5,032 DRC opens: the diagnosis stops at 60 per board.
- 23 % of diagnosed connections have no specific item, mostly cause `geometry`.
- Top item: `more_effort` 47, `neckdown` 23, `placement_room` 11. No item is A/B tested yet.
