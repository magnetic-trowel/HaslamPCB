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
bench/scripts/setup.sh --no-freerouting   # KiCad 10 (+ apt install kicad-symbols kicad-footprints if missing)
cd tools/research/llm-design/synth && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[test]'
haslamsynth build ../designs/<slug>/design.py -v      # checks + KiCad files + ERC + parity
haslamsynth sym 'Relay:.*G5LE'                        # search symbols; `haslamsynth sym Lib:Name` prints pins
haslamsynth fp 'TerminalBlock_Phoenix:.*5.08'         # search footprints; `haslamsynth fp Lib:Name` prints pads
haslamsynth jlc --search TPS63900 'buck boost' --match 'nA' --min-stock 100 [--basic]   # JLC/LCSC candidates
haslamsynth jlc ../designs/<slug>/design.py           # LCSC numbers for generic passives, stock + basic/extended
                                                      # for every carded LCSC code -> designs/<slug>/jlc.json (dated)
haslamsynth ds TPS3700 --section 'Absolute Maximum'   # datasheet: vendor URL or LCSC's copy, cached, a section
haslamsynth ds U3 --design ../designs/<slug>/design.py --grep 'IDD'   # by reference: the card's datasheet first
haslamsynth check-board ../designs/<slug>/design.py BOARD.kicad_pcb  # calcs with board= on the routed board
pytest tests                                        # KiCad tests skip without kicad-cli
```

`ds` keeps PDFs and their `pdftotext -layout` text in `$HASLAMSYNTH_DS_CACHE` (default `~/.cache/haslamsynth/ds`);
`--section` prints a numbered heading's body up to the next heading of its level (contents lines skipped), `--grep`
the matching lines with page numbers. `check-board` reads the board with haslam's pure-Python loader: `haslamsynth check-board DESIGN BOARD` with
`haslam/src` on `PYTHONPATH` (as for the rules check; shapely is a haslamsynth dependency).

`source ~/.cache/haslambench/env.sh` (written by `bench/scripts/setup.sh`) sets `KICAD10_SYMBOL_DIR` and
`KICAD10_FOOTPRINT_DIR` (apt KiCad: `/usr/share/kicad/...`; container: the image's `usr/share/kicad/...`), and
either `HASLAM_KICAD_WRAP` (container: `kicad-cli` and KiCad's Python run through it) or `HASLAM_KICAD_PYTHON`
(apt: KiCad's own Python; the PATH `python3` may lack `pcbnew`). The scripts in `scripts/` that need KiCad's
Python run as `$HASLAM_KICAD_PYTHON script.py` (else `$HASLAM_KICAD_WRAP python3 script.py`). The rules check imports `haslam.board.dru_check` (put
`haslam/src` on `PYTHONPATH`); without it, the build runs haslamsynth's own lint only and says so.

`build` exits non-zero while any unwaived error remains. Iterate until it is clean, then read
`report.md`: warnings are things a reviewer will ask about.

## Pipeline and gates

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
  A resistor from a power net to a `signal`/`clock` net (a pull-up) is checked at a 50 % low time; give `p_diss=`
  for a line held low longer.
- **Zener**: `Zener(mpn, footprint, vz=(lo, hi), p_max)` (pin 1 K). It clamps by design, so its check is the clamp
  power Vz max x the instance's `i_through=` against `p_max` (and `i_through` against IZM), never the nets across it
  against Vz. A TVS stays `D(..., kind="D_TVS")`.
- **Reverse-polarity PMOS**: `ReversePMOS(block, fet, "VIN_RAW", "VIN_P", "GND", ref="Q1", r_gate=R(...),
  zener=Zener(...), gate="Q1_G")` wires drain to the input lead, source to the rail, gate to ground through the
  resistor and clamped to the source by the Zener (gate net in its own domain on the source, clamp current from R),
  and states V(D-S) in [-VIN, 0.7 V] so the 2 x VIN interval artifact needs no waiver.
- **Correlated nets**: `d.v_rel(a, b, lo, hi, why=)` states V(a) - V(b) in [lo, hi] when the per-net intervals
  cannot (a FET's drain and source move together; a gate is either at its source or clamped). Every difference
  of the two nets (ratings, spacing) uses it; `net.v_rel` lists it and errors when it lies outside the nets' ranges.
- Part cards carry JLC sourcing as `fields={"LCSC": "C92489"}` only: `haslamsynth jlc` looks every code up (stock,
  basic/extended, date) and the build writes the `JLC` field and checks stock (`bom.stock`).
- Part cards may carry haslam facts for every part made from them, `haslam=dict(I_A=[lo, hi], I_sustained_A=typ,
  core_I_A=..., core_f_Hz=..., core: False, why=...)`; keys pass through as written (haslam's loader judges them).
  An IC or module with no `I_A`/`I_sustained_A`/`core_I_A` gets haslam's 10 mA class-prior core
  (`haslam_intent.supply_prior` names it; converter controllers with a `d.haslam.cell` are exempt).
- Multi-unit library symbols (op-amps, relays with separate coil units) are placed unit by unit.
- `lifecycle="active" | "nrnd" | "obsolete"`, `second_source="..."` feed the BOM checks.

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
connectors on an edge) marked `source: auto`.

- `region(x, "north")` is haslam's **third** of the board on that side, not "north of my slot": when that band
  contains part of a slot the build warns (`layout.region_crosses_slot`); use `"area:NAME"`, a named rule area
  (`d.board(areas=...)` or a `SlotBarrier` side).
- `region(..., req="REQ-4")` / `far(..., req=)`: the relation restates that requirement, so it is written
  `requested: true` (haslam keeps its strength against physics) and the id goes into its `why`; an unknown id is an
  error (`place.unknown_requirement`). `level=` sets haslam's strength (required, strong, medium, weak).
- `thermal_isolate(sources, victims, area="POWER", hot=[...], req="REQ-4", level="strong")`: the relations a
  thermal floorplan needs, written for you: each source block/part in `area` (required), and keep_aways from each
  hot part (default: the sources' ICs, inductors, transistors, diodes) to the victims nearest the area (with fixed
  victims: the row within 1 mm of the least distance, e.g. the sensors beside the slot), category thermal.

### Board geometry: one source (`d.board`, `d.place.fixed` -> `out/board.json`)

`d.board(...)` records outline, layers, holes, height limits, enclosure and coating, and the geometry
`synth/scripts/sch_to_board.py` builds the unplaced board from; `d.place.fixed(ref, x, y, rotation=, side=,
source=)` places the parts the mechanics fix. The build writes `out/board.json` (`haslamsynth.boardgeom`), and
`sch_to_board.py OUT_DIR` reads it by default. KiCad's frame: mm, origin at the outline's top-left, y down.

```python
from haslamsynth import Hole, SlotBarrier
d.board(width_mm=50, height_mm=78, quantity=5,                 # quantity: boards per order (bom.stock)
        holes=[Hole(3.5, 3.5, 3.2), ...],                      # M3 only (sch_to_board)
        cuts=[SlotBarrier("y", 20.25, width_mm=1.5, bridges=[(20, 30)], edge_mm=2.5, sides=("POWER", "SENSE"))],
        zones=[{"net": "GND", "layer": "B.Cu", "name": "GND_N", "rect": [0, 0, 50, 19.5]}],   # or "area": "POWER"
        areas={"KEYPAD": (30, 40, 48, 76)}, keepouts=[...], slots=[...], seed_area=(3, 6, 47, 76),
        min_drill_mm=0.3)                                      # smallest hole a footprint may bring (default 0.3)
d.place.fixed("J1", 18.65, 3.5, rotation=90, source="host header on the north edge")
```

A `SlotBarrier` is a milled break declared once: slots from `edge_mm` off the outline to each bridge, copper
keep-outs on the edge strips beyond the slot ends (copper crosses only at the bridges), and named rule areas on
both sides (`sides`), 0.5 mm off the outline and the slot. A hand-written `designs/<slug>/board.json` still works:
every key it shares with the design must agree (`board.geometry`, error, both values named), and keys only it states
are merged into out/board.json and listed (move them into design.py).

### Calculations on the routed board

`d.measure(name, "tracks_crossing", barrier="SLOT" | line=((x0, y0), (x1, y1)), nets=, layers=)` and
`d.measure(name, "copper_area", area="SENSE" | rect=..., nets=["GND"])` name board measurements; a calc's `board=`
recomputes it from them, `lambda m: ...` or `lambda m, calcs: ...` (as-built values of earlier calcs):

```python
d.measure("bridge", "tracks_crossing", barrier="SLOT")
d.calc("bridge_conductance", g_b * 1e3, "mW/K", board=lambda m: (g_fr4 + g_tracks(m["bridge"]["width_mm"])) * 1e3)
d.calc("heat_rise_sensors", rise(g_b), "mK", limit=10, board=lambda m, c: rise(c["bridge_conductance"] * 1e-3))
```

`haslamsynth check-board design.py BOARD.kicad_pcb` prints each measurement (tracks crossing: count, total width,
nets, layers, pours across the line; copper area: tracks, pads, pour outlines) and the designed and as-built values,
and exits 1 when an as-built value breaks its limit. The build checks that each measurement names a barrier or area
the design has (`calc.measure`).

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
| `bom.stock` | error/warning | JLC stock (jlc.json, dated) 0 (error) or below parts per board x `quantity` (default 5); codes never looked up (one warning: run `haslamsynth jlc`) |
| `bom.setup_fees`, `bom.no_lcsc` | info/warning | extended LCSC parts (a setup fee each per order), and which are resistors/capacitors whose value may move to a basic part; generic parts without a number |
| `net.v_rel` | info/error | a `d.v_rel` correlation in use, or one outside the nets' own ranges / across roots |
| `board.geometry` | error/info | a hand board.json key that disagrees with `d.board`/`d.place.fixed`; keys only board.json states (merged) |
| `calc.measure` | error | a `d.measure` naming a barrier or rule area the design does not have |
| `protect.threat`, `protect.entry_fuse` | error/warn | external wires without the protector their threat needs |
| `calc.limit`, `hazard.*`, `intent.blocking_question`, `place.*` | error/warn/info | design calculations, hazard mitigations, open questions, relation sanity |
| `kicad.erc.*`, `kicad.netlist_roundtrip`, `kicad.dru_parse` | error/warn | the emitted files, as KiCad reads them |
| `rules.pin_escape`, `rules.pad_gap` | error | a pad no minimum-width track can leave past its neighbours under the generated clearances; pads of one footprint closer than their nets allow (`haslamsynth/layout.py`; necessary, not sufficient: corners and centre pads are not modelled) |
| `layout.density`, `layout.fab_minimums` | warn/info/error | courtyard area vs board area (warn above 40 % on 2 layers); board min track/clearance from the finest pitch when `BoardSpec` leaves them unset (0.127/0.15 mm at <= 0.65 mm pitch); error: a library footprint with holes below `min_drill_mm` (0.3 mm; KiCad's `_ThermalVias` variants have 0.2 mm), naming a same-library variant that passes |
| `layout.region_crosses_slot` | warning | a compass `region()` (haslam: the board's third on that side) that contains part of a slot: use `area:NAME` |
| `place.unknown_requirement` | error | a relation's `req=` that is no `d.require` id |
| `haslam_intent.supply_prior` | warning | ICs/modules (per part card) with no supply-draw fact: haslam gives each a 10 mA class-prior core |
| `haslam_intent.invalid` | error | the `<slug>.haslam_intent.json` haslam's own loader rejects, or names that are not in the design |
| `haslam_intent.relation_infeasible`, `layout.relation` | error/warn/info | a relation for haslam that board.json's fixed parts already break, or that the footprints' courtyards (pad centres, quarter turns, both on one side) or the 0.5 mm copper-to-edge clearance make impossible (error, with the distance to loosen to), or allow only with courtyards touching (warning, above 90 %); relations whose sides are all fixed are dropped from the intent file (info) |
| `haslam_intent.relation_unused` | warning | a `d.place` relation haslam has no reader for (each with the reason: a physics term, a board rule, `board.json`, no placer term yet) |

## Known limits

- Schematic layout is label-based (exact by construction, readable, not pretty): parts cluster
  around the multi-pin part they connect to. No wire routing between symbols.
- Distributor lookup is JLC/LCSC only (`haslamsynth jlc`: stock, basic/extended; `--search` with a regex filter,
  not a parametric engine). Lifecycle is what the design says, so `source=` and an independent review carry the
  weight. Part cards should move to a resolved catalog.
- Custom footprints: `footprint="custom:Name"`, drawn in `designs/<slug>/footprints/custom.pretty/`
  (the project's fp-lib-table points there; pads are checked once the file exists).
- No SPICE yet: a reviewer found a watchdog whose hand calculation missed a discharge
  path. Time-domain behaviour needs a testbench; until then, calculations must state
  every scenario (signal stuck high and stuck low) and reviewers re-derive them. Typed interfaces (I²C pull-ups, address uniqueness) are not modelled.
- `kicad-cli` 10.0.7 segfaults running DRC with `creepage` rules on a board without an
  Edge.Cuts outline; `dru_check`'s probe board has one.
- Output targets KiCad 10 (`20260306`); KiCad 9 cannot open it.
