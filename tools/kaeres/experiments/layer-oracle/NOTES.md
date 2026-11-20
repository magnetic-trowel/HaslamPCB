# layer-oracle: state of the branch (2026-11-20)

Done
- `kae/src/kae/route/layer_assign.py`: setting `net_layers` (table file or directory) and `net_layers_max_sets`;
  hook in `constraints.plan()` (the table's layers join the net's `off` layers, so classes split and
  `translate` writes `use_layer`). Unset: `assign()` returns `({}, None)` and the plan is unchanged.
- `tools/research/routing/net_layers.py`: `extract` (net or `--roles` tables) and `reach`.
- `kae/tests/test_route_layer_assign.py` (5 tests, no KiCad needed); `kae/tests/test_route_plan_rules.py` still passes.

Checked on a real board (4 layers, 244 pads, 50 nets; export, plan and DSN only, no routing)
- The table is found by net-name fingerprint from a directory (the bare board's file name differs from the human's).
- Role table: all 50 nets restricted to the three layers the human routed on (the fourth is a plane), 2 classes, 2 `use_layer`.
- Net table: 4 layer sets, 6 classes (2 without the table), 6 `use_layer`; the DSN grows from 117 to 127 kB.
- The plan note `layer_assign` reaches the bridge report through `plan_summary`.

Smoke through the bridge and the fork (kaeq, same board, bare copy without its project file, so its rules are
KiCad's defaults and the open counts mean nothing; 150 s per arm)
- control 79, role table 77, net table 78 unconnected; the DSN carries 0, 2 and 6 `use_layer`.
- The fork obeys: with the role table no track lies on the plane layer the control used; with the net table the one
  signal net the control had put on a layer outside its set is back inside it.
- Leak: kae's own last mile does not read the table. With the net table it laid 9 mm of a plane net (3.3V) on an
  inner layer outside that net's set: 4 % of track length, 1 of 24 routed nets.

Not done
- `lastmile` (and repair's own copper) should honour `RoutingClass.layers`; until then the experiment reports the
  leaked share per run (PLAN, endpoint 4). Nets that own a zone could also be left out of extracted tables: their
  human tracks are stubs to the plane.
- No test asserts the DSN text for a class with layers (the writer is existing code, `translate.py`).
- What an attempt with strict planes does to a net whose allowed inner layer is typed `power`: such a net keeps its
  outer pad layers; nets allowed on plane layers only are left unrestricted. Not measured.
- `boards.txt` is a ranked candidate list from stored fork-alone runs; the reach check in PLAN.md picks the boards.
