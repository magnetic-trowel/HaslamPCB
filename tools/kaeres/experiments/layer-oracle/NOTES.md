# layer-oracle: state of the branch (2026-11-20)

Done
- `kae/src/kae/route/layer_assign.py`: setting `net_layers` (table file or directory) and `net_layers_max_sets`;
  hook in `constraints.plan()` (the table's layers join the net's `off` layers, so classes split and
  `translate` writes `use_layer`). Unset: `assign()` returns `({}, None)` and the plan is unchanged.
- `tools/research/routing/net_layers.py`: `extract` (net or `--roles` tables) and `reach`.
- `kae/tests/test_route_layer_assign.py` (5 tests, no KiCad needed); `kae/tests/test_route_plan_rules.py` still passes.

Not done
- End-to-end smoke through the bridge and the fork: queued as one kaeq job (owner `d1-layer-oracle-smoke`), three
  arms on one 4-layer board; its output folder is named in the design dossier. Check there that the DSN holds
  `use_layer`, that `reach` reports 0 length on disallowed layers in both oracle arms, and that the plan note says
  `found: true` (the lookup by net-name fingerprint has only been unit-tested against synthetic boards).
- No test asserts the DSN text for a class with layers (the writer is existing code, `translate.py`).
- What an attempt with strict planes does to a net whose allowed inner layer is typed `power`: such a net keeps its
  outer pad layers; nets allowed on plane layers only are left unrestricted. Not measured.
- `boards.txt` is a ranked candidate list from stored fork-alone runs; the reach check in PLAN.md picks the boards.
