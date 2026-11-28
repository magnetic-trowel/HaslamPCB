# haslamsynth: from a product brief to a checked KiCad schematic and placement intent

`haslamsynth` is the front of the pipeline. A person describes a product, an LLM writes
`designs/<slug>/design.py`, and `haslamsynth build` turns it into:

| Output (`designs/<slug>/out/`) | What it is |
|---|---|
| `<slug>.kicad_pro`, `<slug>.kicad_sch`, `<block>.kicad_sch` | KiCad 10 project: a root sheet plus one hierarchical sheet per block, net classes, lib tables |
| `haslamsynth.kicad_sym` | Project symbols: generated IC symbols and renumbered transistor symbols |
| `<slug>.kicad_dru` | Custom DRC rules: clearance and creepage between isolation domains |
| `<slug>.haslam_intent.json` | haslam.intent/1: operating facts, priced terms and placement relations haslam reads beside the board (`intent.yaml` is retired) |
| `netlist.json` | The IR netlist, every pin with its net |
| `bom.csv` | BOM grouped by MPN, with lifecycle and second source |
| `report.md` | Requirements, questions, hazards, calculations, findings, ERC, parity |
| `findings.json`, `erc.json` | Machine-readable check results |

Research behind the design: [schematic-generation-landscape](../../../../docs/topics/synthesis/schematic-generation-landscape.md),
[part-selection-and-verification](../../../../docs/topics/synthesis/part-selection-and-verification.md),
[constraint IR](../../../../docs/topics/architecture/constraint-ir.md),
[relations, not coordinates](../../../../docs/topics/llm/interfaces-relations-vs-coordinates.md).

## Setup and use

```bash
bench/scripts/setup.sh --all            # from the repo root: KiCad 10 and its libraries, this venv, haslam's, env.sh
. ~/.cache/haslambench/env.sh && cd tools/research/llm-design/synth && . .venv/bin/activate
haslamsynth api                                       # every design.py call: signature + one-line doc (~2k tokens)
haslamsynth build ../designs/<slug>/design.py -v      # checks + KiCad files + ERC + parity
haslamsynth sym 'Relay:.*G5LE'                        # search symbols; `haslamsynth sym Lib:Name` prints pins
haslamsynth fp 'TerminalBlock_Phoenix:.*5.08'         # search footprints; `haslamsynth fp Lib:Name` prints pads
haslamsynth parts search 'buck-boost' --min-pitch 0.65 # JLC parts; also `datasheet`, `fp-fetch` (see Parts)
pytest tests                                        # KiCad tests skip without kicad-cli
```

`env.sh` sets `HASLAM_KICAD_WRAP` (the container wrapper, or empty for a native KiCad) and
`KICAD10_SYMBOL_DIR`/`KICAD10_FOOTPRINT_DIR`; `haslambench doctor --pipeline` checks them and this venv. The rules check
imports `haslam.board.dru_check` (setup.sh `--all` puts `haslam/src` on this venv's path with a `.pth` file); without it,
the build runs haslamsynth's own lint only and says so.

Fab limits come from a profile (`src/haslamsynth/fab/<name>.json`, `d.board(fab=...)`, default `jlc-2layer-1oz`): every limit with its source, written into the board setup, the top of the `.kicad_dru` and (via `sch_to_board.py`) the board file; preflight's `board.fab` checks a board against it. Without it, a clean DRC is clean against KiCad's defaults, not the fab's.

`build` exits non-zero while any unwaived error remains. Iterate until it is clean, then read
`report.md`: warnings are things a reviewer will ask about.

## What `haslamsynth build` checks, in order

This is stage 3 of the board pipeline; the whole pipeline (board, pre-flight, size, layout, physics, review, fab),
run by `scripts/pipeline.py`, is the stage table in [README Part 1](../../../../README.md#part-1-design-a-pcb).

1. **Brief → requirements.** `require`, `assume`, `question(blocking=...)`, `hazard(...)` records
   live in `design.py`. An unanswered blocking question marks the build "not ready for fabrication".
2. **Architecture.** Blocks (one schematic sheet each), voltage domains, barriers.
3. **Parts.** `PartDef`s with MPN, symbol, footprint, pins, ratings and `source=` provenance.
4. **Circuit.** Nets with domain, voltage range, current, kind. Every pin connected or `nc_pins(..., reason=)`.
5. **Checks** (deterministic, pin-level messages; table below).
6. **Emit + KiCad gates:** `kicad-cli sch erc` and a **netlist round trip** — the schematic KiCad
   reads must be pin-for-pin identical to the IR. Then the `.kicad_dru` check: haslamsynth's lint
   (net-class names), then `haslam dru-check`'s static and KiCad passes (kicad-cli 10.0.7 drops a
   bad file silently and exits 0, so a plain DRC run proves nothing;
   [kicad-cli.md](../../../../docs/topics/kicad/kicad-cli.md)).

ERC-clean is a low bar ([evidence](../../../../docs/topics/synthesis/part-selection-and-verification.md)):
the design-level checks and an independent review are what catch wrong designs.

## Writing `design.py`

`haslamsynth api` prints every call below with its full signature, generated from the code (current by
construction); read it instead of an example design. This section gives the semantics.

```python
from haslamsynth import Design, Hole, Isolation, PinDef, Ratings, VLimit
from haslamsynth.lib import C, IC, LED, NMOS, R, Conn, Fuse, PINMAP_SOT23_FET

def build():
    d = Design("my-board", title="...", brief="<the user's words>")
    d.require("REQ-1", "Survive 40 V load dump", value="40 V, 400 ms", source="ISO 16750-2", verify="bench")
    d.question("Q-1", "Which battery chemistry?", blocking=True, default="LFP")
    d.hazard("HZ-1", "Short on output harness", mitigation="fuse at battery end", parts=["F1"], single_fault_safe=True)

    # Domains: every net belongs to one. `ref` is the domain's 0 V net.
    d.net("GND", domain="LV", v=0, kind="ground")
    d.domain("LV", ref="GND", kind="selv")
    d.net("+12V", domain="LV", v=(9, 16), kind="power", i_max=2, external=True, threats=("reverse_polarity", "overcurrent"))
    ...
    blk = d.block("input", title="12 V input protection")
    f = blk.add(Fuse(3, 32, "Fuse:Fuse_1206_3216Metric", mpn="...", datasheet="..."), ref="F1")
    sw = blk.net("SW", v=(-0.7, 16), kind="switching", i_max=2)    # local to the block
    d.nets["+12V"].connect(j[1], f[1])
    ...
    d.place.edge(j, "west"); d.place.hot_loop([u["VIN"], cin[1], cin[2], u["PGND"]])
    d.board(width_mm=60, height_mm=40, layers=2, holes=[Hole(3.5, 3.5, 3.2)])
    return d
```

### Domains and voltages (what the rating checks run on)

- `d.domain(name, ref=<net>)`. If `ref` is a net *of this domain* (with `v=0`), the domain is a
  **root**: galvanically separate from other roots. If `ref` is a net of *another* domain, the
  domain floats on it — e.g. battery k of a series stack is `d.domain("B3", ref="B2_POS")`.
- Every net gets `v=(min, max)` in volts relative to its domain's ref (peak for AC: 120 Vrms
  mains is `(-170, 170)`). The checker computes the worst voltage between any two nets by
  summing ranges along the domain chain, so stacked batteries are exact, not interval-blown.
- Envelopes are conservative. When a part can never see the full envelope difference (a shunt,
  an LED that cannot be reverse biased), declare `blk.add(part, v_across=0.1)` and say why in a comment.
- Anything connecting two **roots** must declare `Ratings(isolation=[Isolation(a_pins, b_pins,
  v_iso_rms | v_iso_dc, grade, v_work_rms, v_work_dc, creepage_mm, material_group)])`, and a `d.barrier(a, b, grade, v_work,
  creepage_mm, clearance_mm, standard, v_test_rms, source)` must exist. Spacing numbers come from
  the standard's tables (cite them in `source`); the framework does not invent them.
  Set `ac=True` on mains barriers (`v_work` is then a peak and parts' Vrms ratings are scaled by
  sqrt 2); DC barriers need `v_work_dc` (an rms rating is applied to DC unscaled).
  `creepage_by_group={"I": 4.0}` gives the package creepage required for better-CTI moulds.
- `Domain(edge_clearance_mm=, edge_source=)` keeps that domain's copper off the board edge
  (emitted as a `.kicad_dru` `edge_clearance` rule).
- Spacing: a net class's clearance covers voltages inside its own domain; between domains of
  one root the `.kicad_dru` gets IPC-2221B functional rules from the exact worst voltage of each
  domain pair, then barrier rules (inherited before direct, so the most specific wins), then an
  exemption for the pads of parts that bridge spaced domains (their package sets that spacing).
- `d.barrier` also works between non-root domains (functional spacing, e.g. relay contacts vs
  line); `d.place.separate(a, b)` turns it into a placement relation; the `.kicad_dru` carries it.

### Adding parts with their connections (`blk.wire`, `Wiring`)

- `blk.wire(defn, ref, {pin: net}, nc=[pins], nc_reason="...", **part_kw)` adds a part and connects each pin (number or
  name) to a net given by name or as a `Net`. Names resolve to the block's own nets, then global ones; an undeclared
  name is a `DesignError`, never a new net (a typo cannot open a net).
- `Wiring(d, name, title, description, domain=, board=, nets=[(name, v, kind, {Net kwargs}), ...])` is a block plus
  its local nets, with `w.add(defn, ref, {pin: net}, ...)` (= `blk.wire`), `w.R(ref, ohms, a, b, pkg=, note=, tol=)`
  (`ohms` a number, 4700 → `4.7k`, or text) and `w.C(ref, value, v_rating, a, b, pkg=, diel=, note=)`; `w.b` is the
  Block (for `d.place`), `w.n(name)` a net. Part arguments (`p_diss`, `v_across`, `fields`, ...) in `R`/`C`'s `**kw`
  go to the part, the rest to the part card (`lib.R`/`lib.C`). `designs/obd-solar/design.py` uses it (`class
  Blk(Wiring)` fixes the domain).

### Parts

- **Library symbol** (`symbol="Lib:Name"`): pins come from KiCad. Prefer this for passives,
  connectors, relays and anything KiCad has. Check pins with `haslamsynth sym Lib:Name`.
- **Generated symbol** (`IC(mpn, pins=[PinDef(number, name, type, side=None), ...], footprint=...)`):
  for ICs; pin numbers and names from the datasheet pin table. Types: `input output bidirectional
  tri_state passive power_in power_out open_collector open_emitter no_connect free`.
- **Unnamed library pins** (relays, many connectors): pass `pin_names={"1": "COM", "5": "COIL_A", ...}`
  from the datasheet and connect by name. Check the mapping against the symbol graphic: KiCad's
  `Relay:G5LE-1` coil is pins 2/5, not 1/2.
- **Transistors** from `lib.NMOS/PMOS/NPN` need `pinmap=` from the datasheet (KiCad's generic
  symbols use letter pins); there is no default.
- `source={"pins": "...", "pinmap": "...", "ratings": "..."}` and `datasheet=` on every non-generic
  part: datasheet revision, page, table. Missing provenance is a warning a reviewer will chase.
- Ratings: `v_max` (2-terminal), `limits=[VLimit(("D",), ("S",), 100)]` (symmetric abs max;
  `v_min=-8` makes it directional; `v_rec=3.6` gives the recommended operating maximum, inside
  which no derating warning fires — use it for IC supply and I/O pins; `derate=False` for nodes
  the IC drives itself, such as charge-pump, soft-start or compensation pins: hard limit only), `i_max` / `pin_i_max`,
  `p_max`, `polarity=("1", "2")`, `isolation=[...]`. Set `p_diss=` on parts from your calculations.
- Generic passives (`R`, `C` without MPN) are allowed; resistors default to thick-film package
  ratings, capacitors need a voltage rating. Pass an MPN and real ratings for anything stressed.
- Multi-unit library symbols (op-amps, relays with separate coil units) are placed unit by unit.
- `lifecycle="active" | "nrnd" | "obsolete"`, `second_source="..."` feed the BOM checks.

### Choosing parts: `parts search`, `datasheet`, `fp-fetch`

```bash
haslamsynth parts search "buck-boost" --min-pitch 0.65 --min-stock 500 [--basic] [--package 'TSSOP|SOIC'] [-n 20]
haslamsynth datasheet TPS709B33DBVR --design ../designs/<slug> --pages auto     # or a C-number; --pages 32-35
haslamsynth fp-fetch C580689 --design ../designs/<slug> --name LTC3115_FE20 --check-part ../designs/<slug>/parts.py:LTC3115
```

| Command | Does | Writes |
|---|---|---|
| `parts search KEYWORD` | JLCPCB parts search, one line per hit: LCSC, MPN, basic/ext, stock, package + pitch, maker, description, datasheet URL; filters on up to 100 results, basic first then stock | nothing |
| `datasheet MPN\|C-number` | tries `--url`, the maker's URL pattern (TI, ADI, ST), the JLC API URL, `datasheet.lcsc.com`, each once; `--pdf FILE` takes a user-supplied copy; lists the pages naming typical application, layout, pins, abs max, package outline; `--pages` renders PNGs | `<design>/datasheets/<MPN>.{pdf,txt,source.json}`, `<MPN>-p<N>.png` (folder git-ignored: vendor copyright; cite the URL in the part card) |
| `fp-fetch C-number` | EasyEDA land pattern via easyeda2kicad, `kicad-cli fp upgrade` to KiCad 10, renamed; `--check-part parts.py:NAME` compares pads with the card's pin numbers (missing pad: exit 1) | `<design>/footprints/custom.pretty/<name>.kicad_mod` (no overwrite without `--force`) |

- Pitch in `parts search`: `P0.65` from the package name or a one-pitch family, `~P0.5` typical for that
  QFN/DFN body, `<=P0.8` an upper bound from a square body, `P?` unknown. `--min-pitch` drops only parts
  known to be finer; read the package drawing for the rest.
- `fp-fetch` needs the `parts` extra: `uv pip install -e '.[parts]'` (easyeda2kicad, AGPL-3.0, used as a
  separate library). The footprint reader also reads legacy `(module ...)` files and the build warns
  `lib.footprint_legacy`; upgrade them with `kicad-cli fp upgrade --force <lib>.pretty`.
- **Licence:** footprints fetched from EasyEDA/LCSC have no stated licence (obd-solar FRICTION #27). The
  command says so and writes it into the footprint's `Source` property. Before committing one, add a
  REUSE.toml entry recording the decision, or redraw the land pattern from the datasheet. Always check it
  against the datasheet's recommended land pattern.
- Fetching is gentle (`src/haslamsynth/fetch.py`, shared by `jlc` too): one request at a time, >= 1 s between
  requests per host, `Retry-After` honoured, at most 3 tries and only for 429/5xx; 403s and timeouts are
  reported, remembered for 6 h and not retried. Responses are cached under `~/.cache/haslamsynth/http`
  (`HASLAMSYNTH_CACHE` moves it; JLC searches for a day, the rest until deleted; `--refresh` asks again).
  From a cloud host LCSC datasheet URLs answered 403 and st.com stalled: when every source fails, find a
  mirror (`--url`) or ask the user for the PDF (`--pdf`) instead of retrying.

### Nets

`kind`: `signal power ground hv mains switching sense analog high_current pe clock diff`.
`width_mm=` forces a track width (e.g. a 15 A mains path drawn at 7.5 mm on both layers).
`external=True` for nets leaving the board; `threats=("esd", "surge", "overcurrent",
"reverse_polarity", "load_dump", "overvoltage")` require a protector of the matching category on
that net. `i_max` drives current checks and net-class track widths. A part that carries less than its net's current
declares `i_through=` (amps, or `{pin: amps}` per winding/pin).

### Placement relations (`d.place.*`; ordinal magnitudes, never coordinates)

`group(block)`, `region(block | part | [parts], "north")`, `pins_toward(part, ["A1", "A2"], "south")`
(rotate so those pins face that side — use it instead of free-text orientation), `near(a, b, "tight|close|loose")`, `far(a, b)`,
`hot_loop([pins...])`, `edge(part, "north|south|east|west|any")`, `orient(part, facing)`,
`separate(domA, domB)`, `keepout(obj, what, layers)`, `thermal(part, watts, sink)`,
`array(parts, axis)`, `align(parts, axis)`, `symmetric(pairs, axis)`, `side(part, "top|bottom")`,
`custom(kind, ...)` for anything else. Objects are parts, pins (`u["VIN"]`), blocks or domains.
The build adds inferred relations (block groups, decoupling caps next to their IC pin, external
connectors on an edge) marked `source: auto`. `d.board(...)` records outline, layers, holes,
height limits, enclosure and coating.

### Several boards and harness items

`d.board("main", ...)`, `d.board("batt_end", ...)` declare boards; `d.block(..., board="batt_end")`
puts a block on one (default: the first). `board="off"` is for harness items with no PCB
(inline fuses, ring terminals): they are in the BOM, not on a board. A net may run between
boards only through a connector on every board it touches (`board.crossing_without_connector`).
The build writes the whole system schematic in `out/` (review, ERC, system parity) and one
KiCad project per board in `out/board-<name>/`, each with its own parity check (the intent file is written for the
whole design only).

### Nets that ride on other nets

A bootstrap or high-side gate supply rides on a switch node: give it a domain floating on that
net, `d.domain("BST1", ref="SW1")`, and `v=(0, 12)` relative to it. Worst-case voltages to
everything else then follow from the switch node's own range.

### Operating intent for haslam (`<slug>.haslam_intent.json`)

haslam reads a board's operating facts from `<board>.haslam_intent.json` beside it (haslam.intent/1; `haslam/src/haslam/intent/facts.py`).
haslamsynth writes it from three places, later ones winning:
- nets declared with `v_typ=` (typical volts, or `(lo, typ, hi)` when the operating range is narrower than `v=`);
- part cards with `haslam=dict(f_sw_Hz=..., v_sw_max_V=..., why=...)` (facts that belong to the part);
- `d.haslam.net(...)`, `d.haslam.part(...)`, `d.haslam.cell(controller, "buck"|"boost", I_A=(lo, typ, hi), V_V=..., vin=, vout=)`,
  `d.haslam.cable(...)`, `d.haslam.term(...)` (what this design chooses: rail sources and efficiencies, a cell's current and
  switched bus, cables, priced terms). Every fact says why; haslam's own loader checks the file at build time.
- placement relations in haslam's vocabulary (docs/topics/placement/relations-unified.md): `d.place.near/far/group`
  (near, keep_away, group; `mag` tight/close/loose, which haslam scales to the parts), `edge` (on_edge; `any` is
  edge:nearest), `region`, `side`, `array`/`align` (row), and the decoupling nears the circuit implies;
  `near(..., within_mm=, note=)` takes a datasheet distance, written as `mag: "<v> mm"` and measured pad to pad. The
  build checks each against board.json's fixed parts and the footprints as haslam measures. Other relation kinds are
  not written and come back as `haslam_intent.relation_unused` warnings with the reason. Only fields haslam reads are written
  (docs/topics/workflow/intent-file-fields.md).

### Calculations and waivers

`d.calc(name, value, unit, expr=, note=, limit=, op="<=")` records a calculation in the report
and fails the build if the limit is violated. `d.waive(check, regex, reason, by)` accepts a
finding on the record; never waive an error you have not understood. A waiver that matches nothing
is reported (`waiver.unused`), so stale ones get removed.

A relay or switch whose contacts join two parts of a circuit that can be connected (e.g. a
converter output and the pack it charges) belongs to one root: model the worst case
(connected), with a functional barrier across the open contacts.

## Checks

| Check | Severity | Catches |
|---|---|---|
| `conn.unconnected_pin`, `conn.single_pin_net`, `conn.nc_without_reason` | error/warn | unaccounted pins, dangling nets |
| `erc.output_conflict` | error | two push-pull outputs on one net |
| `net.no_domain`, `domain.ref`, `net.no_voltage` | error/warn | nets the voltage model cannot place |
| `rating.voltage`, `rating.polarity` | error/warn | worst-case voltage vs `v_max`/`limits`, reverse-biased electrolytics |
| `rating.current`, `rating.power`, `rating.dc_bias` | error/warn | net current through series parts, dissipation, MLCC DC bias |
| `domain.crossing`, `barrier.*` | error | non-isolating parts across roots; isolation grade, withstand, working voltage, package creepage |
| `lib.*` | error/warn | missing symbols/footprints, symbol pins without pads, hidden power pins |
| `part.no_datasheet`, `part.no_provenance`, `bom.*` | warn/error | unsourced facts, missing MPN, NRND/obsolete |
| `protect.threat`, `protect.entry_fuse` | error/warn | external wires without the protector their threat needs |
| `calc.limit`, `hazard.*`, `intent.blocking_question`, `place.*` | error/warn/info | design calculations, hazard mitigations, open questions, relation sanity |
| `kicad.erc.*`, `kicad.netlist_roundtrip`, `kicad.dru_parse` | error/warn | the emitted files, as KiCad reads them |
| `rules.pin_escape`, `rules.pad_gap` | error | a pad no minimum-width track can leave past its neighbours under the generated clearances; pads of one footprint closer than their nets allow (`haslamsynth/layout.py`; necessary, not sufficient: corners and centre pads are not modelled) |
| `layout.density`, `layout.fab_minimums` | warn/info | courtyard area vs board area (warn above 40 % on 2 layers); board min track/clearance from the finest pitch when `BoardSpec` leaves them unset (0.127/0.15 mm at <= 0.65 mm pitch) |
| `haslam_intent.invalid` | error | the `<slug>.haslam_intent.json` haslam's own loader rejects, or names that are not in the design |
| `haslam_intent.relation_infeasible`, `layout.relation` | error/warn/info | a relation for haslam that board.json's fixed parts already break, or that the footprints' courtyards (pad centres, quarter turns, both on one side) or the 0.5 mm copper-to-edge clearance make impossible (error, with the distance to loosen to), or allow only with courtyards touching (warning, above 90 %); relations whose sides are all fixed are dropped from the intent file (info) |
| `haslam_intent.relation_unused` | warning | a `d.place` relation haslam has no reader for (each with the reason: a physics term, a board rule, `board.json`, no placer term yet) |

## Known limits

- Schematic layout is label-based (exact by construction, readable, not pretty): parts cluster
  around the multi-pin part they connect to. No wire routing between symbols.
- No distributor lookup yet: MPNs and lifecycle are what the design says, so `source=` and an
  independent review carry the weight. Part cards should move to a resolved catalog.
- Custom footprints: `footprint="custom:Name"`, drawn in `designs/<slug>/footprints/custom.pretty/`
  (the project's fp-lib-table points there; pads are checked once the file exists).
- No SPICE yet: a reviewer found a watchdog whose hand calculation missed a discharge
  path. Time-domain behaviour needs a testbench; until then, calculations must state
  every scenario (signal stuck high and stuck low) and reviewers re-derive them. Typed interfaces (I²C pull-ups, address uniqueness) are not modelled.
- `kicad-cli` 10.0.7 segfaults running DRC with `creepage` rules on a board without an
  Edge.Cuts outline; `dru_check`'s probe board has one.
- Output targets KiCad 10 (`20260306`); KiCad 9 cannot open it.
