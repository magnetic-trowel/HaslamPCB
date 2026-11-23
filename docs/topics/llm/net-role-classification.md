# Net-role classification

Scope: deciding net roles (power, ground, diff pair, clock, high-speed, analog) and pin roles from schematic, names, IBIS and topology. Not here: block recognition -> [block-recognition](block-recognition.md); SI thresholds -> [rules/si-fundamentals](../rules/si-fundamentals.md).
Keys: net role, net class, diff pair suffix, +/-, P/N, A/B, t/c, implicit net class, pin electrical type, IBIS, [Diff Pin], [Ramp], Model_type, edge rate, rise time, pin-mux, HWE-Bench, PCBSchemaGen 32-role ontology, Quilter power nets, Flux Net Type, kicad-happy keyword classes

## Layered classifier

Four signals exist: power symbols and names, suffix/keyword rules, pin names/roles on connected IC pins, designer-assigned net classes. Quilter and Flux key off native net classes first [V]. Classify in layers, recording evidence per layer, higher overriding lower [I]:

1. Explicit intent: net classes, directive labels, "Power" or diff-pair classes.
2. IBIS `[Pin]`/`[Diff Pin]`/`Model_type`/`[Ramp]` when an `.ibs` exists; else datasheet pin roles mapped to a role ontology.
3. Topology: SW pin + L -> switch node; FB + divider -> feedback; XIN/XOUT + crystal -> crystal net.
4. Names: suffix and keyword rules.
5. LLM adjudication for leftovers, citing pins.

Rules [I]:
- "Is this net fast?" is a computation: estimated route delay (length / propagation velocity) vs edge rise time t_r: > t_r/6 flag for SI review; > t_r/2 must be terminated (threshold CONTESTED -> [rules/si-fundamentals](../rules/si-fundamentals.md)). IBIS `[Ramp]` gives 20–80% time ≈ 0.75 × 10–90% time for a linear edge. Protocol data-rate and impedance tables stay deterministic in the interface rule packs (rules area, rules_hs_emi cluster).
- Propose renames to `+`/`-` or `_P`/`_N` when a detected pair uses A/B, t/c or P/M; never rely silently on non-KiCad conventions.
- Resolve MCU pin-mux from vendor pin-config exports or an explicit schematic table, not by LLM inference (LLMs fail on multiplexed and redundant pins -> [Pin semantics](#pin-semantics)).
- Show defaults (Quilter-style 200/500 mA) as needing confirmation; state undetected nets as "generic low-speed".

## Fast nets (built)

`kae.circuit.edges` answers "is this net fast?" with the computation above, not with names.

- **t_r** is the fastest driver on the net: an IC, module or oscillator pin typed output, bidirectional, tri-state or open-drain (untyped pins count). Each family row names its source and is marked `assumed`: it is a family default, not this part's datasheet or IBIS `[Ramp]`. Values are 10–90 %. Logic and FPGA rows are the family's fastest edge; MCU rows are the pin's reset default, since the netlist cannot show what slew firmware sets (user decision, 2026-11): the brief's `edge.slew` and every edge hazard's fix say that a pin set to a fast slew or higher drive needs review.

  | Family | t_r | Source |
  |---|---|---|
  | 74LVC/ALVC/AVC/LVT, NC7SZ; 74AC/ACT/F | 1.5 ns | TI E2E [S]; *Complete PCB Design* family table [S] |
  | 74AHC; 74HC; 74HCT; 74LS | 2.3; 6; 8; 10 ns | TI E2E (0.7 ns/V) [S]; [SN74HC04](https://www.ti.com/lit/ds/symlink/sn74hc04.pdf) t_t typ at 6 V [P]; SN74HCT04 [P]; family table [S] |
  | STM32; GD32/APM32 | 100 ns | DS8626 I/O AC table, OSPEEDR=00 (reset) at 50 pF; 2.5 ns only at OSPEEDR=11 [S]; GD32 assumed alike [I] |
  | nRF52 | 8 ns | PS GPIO: DRIVE resets to S0S1, 8 ns at 15 pF (simulated) [S] |
  | SAM D/L/C | 13 ns | I/O pin characteristics: DRVSTR=0 at reset, 13–15 ns at 20 pF [S] |
  | AVR | 3.6 ns | ATmega328P Table 28-6, SPI master; no slew setting [P] |
  | RP2040/RP2350, ESP32, PIC, other MCUs and MCU modules | 10 ns | assumed slow: reset is slow slew (RP2040 `SLEWFAST=0`, PIC `SLRCON=1`) or undocumented, and no rise time is published [I] |
  | FPGA | 0.5 ns | assumed: vendors defer to IBIS; as fast as a CMOS oscillator at 5 pF [I] |
  | oscillator | 1.3 ns | [SiT8008B](https://www.sitime.com/sites/default/files/gated/SiT8008B-datasheet.pdf) 1 ns 20–80 % at 15 pF, ×1.33 [P] |

  Other parts have no row and their nets are not judged (`edge.t_r_ns: null`). Interfaces whose standards set edge and termination (USB, PCIe, SATA, HDMI, DP, MIPI, LVDS, SerDes, Ethernet MDI, DDR, CAN, RS-485) are left to their rule packs.
- **t_pd**: microstrip √(0.475 εr + 0.67)/c (IPC-2141 fit), stripline √εr/c, εr from the stackup or 4.5. At εr 4.6, TI [SCAA082A](https://www.ti.com/lit/an/scaa082a/scaa082a.pdf) Table 2 gives 5.8–5.9 ps/mm microstrip and 7.15 ps/mm stripline [P]; the fit gives 5.65 and 7.15.
- **Brief** (`nets[n].edge`): t_r, source, the review (t_r/6) and terminate (t_r/2) lengths. A plain `signal` net whose terminate length is shorter than the outline's w + h becomes `high_speed`/`fast_edge` (confidence 0.73): power copper keeps its victim gap from it, and placement weights it `fast_edge_weight` (1.5; `KAE_FAST_EDGE_WEIGHT`, 1 = off), a trade-off the place report records under `fast_edge`. Sprint A/B (12 boards × 2 seeds): 2.3 fewer nets per board over t_r/2 [−4.0, −1.0], fast nets 128 mm shorter [−267, −9], total HPWL +116 mm [−13, +249] (median +1.2 %), legality, probe opens and physics unchanged. An analog victim structure still outranks it.
- **Hazards** on every board kae writes (`board_hazards.finish`): driver-to-farthest-load delay over t_r/2 is `edge_ringing_risk` (warn), over t_r/6 `edge_si_review` (info); routed copper where it reaches the load (Dijkstra on delay per layer), else a Manhattan estimate. The fix names a series resistor at the driver pin, a shorter route or a lower slew, per rule 5 of [si-fundamentals](../rules/si-fundamentals.md): never auto-insert terminations.

## KiCad naming and class rules

- Diff pairs are strictly name-based: "nets with a common base name and a positive and negative suffix… + and -, or P and N… cannot be mixed: USB+ and USB_N do not form a differential pair". Gap comes from the net class ([KiCad 9 PCB manual](https://docs.kicad.org/9.0/en/pcbnew/pcbnew.html)) [P].
- Net-class patterns ([KiCad 9 Schematic manual](https://docs.kicad.org/9.0/en/eeschema/eeschema.html)) [P]: wildcards (`*`, `?`) and regex; dynamic assignment; a net matching several patterns gets all classes, the highest-priority class holding a field wins (Default is fallback); names include the sheet path.
- Community hazards [S] ([forum](https://forum.kicad.info/t/differential-pair-doesnt-work-with-any-of-the-suffixes/26166)): suffix must be the last character; symbol pin names like `Pin_P` don't create pairable nets; `XTAL_P`/`XTAL_N` apply diff-pair rules to single-ended traces.
- Pin electrical types (12): Input, Output, Bidirectional, Tri-state, Passive, Free (not internally connected), Unspecified, Power input, Power output, Open collector, Open emitter, Unconnected ([pin_type.cpp @10.0](https://gitlab.com/kicad/code/kicad/-/blob/10.0/eeschema/pin_type.cpp)) [P]. The doc mirror cited in the notes omits Free and calls the last type "Not connected".

## Commercial detectors

| Tool | Rule | Source |
|---|---|---|
| Quilter diff pairs | Needs a differentialpair (or synonymous, e.g. 75 ohm) net class **and** a suffix: `+`/`–`, A/B, P/M (last or second-to-last char), P/N, t/c; names starting with V excluded; pairs with series R/C merged; user gives Zdiff, single-ended Z, carrier GHz; unsupported: multi-drop, fly-by, 2-layer stack-ups, coplanar waveguide (microstrip only) | [docs](https://docs.quilter.ai/physics-constraints/differential-pairs) [V] |
| Quilter power nets | Name pattern or "Power" class; default max current **200 mA below 3 V, 500 mA above 3 V**; IPC width per stack-up; "Overheated Length" flags estimated rise **> 20 °C**; single-ended impedance (50/75 Ω) **manual only**, width within 5%, invalid-width tolerance 10%; uncaptured signals "generic, low-speed digital" | [docs](https://docs.quilter.ai/physics-constraints/power-nets) [V] |
| Flux Net Type | 7 priority buckets (High Speed, Analog, Power, Medium Speed, Low Speed, Uncertain, Ground), inferred, user-editable, routed in that order; users told to mark diff pairs and add Max Current or Thermal Rise | [Flux](https://www.flux.ai/p/blog/ai-auto-layout-just-got-smarter) [V] |
| kicad-happy keyword classes | ground, power, clock (SCL/SCK/CLK/XTAL), data, high_speed (USB/CAN/LVDS/ETH), analog (ADC/AIN/VREF), control, chip_select, interrupt, debug, config; rails from `#PWR`/`#FLG` symbols + names; IO domains via VDDIO and VCCA/VCCB | [methodology](https://github.com/aklofas/kicad-happy/blob/main/skills/kicad/scripts/methodology_schematic.md) [P] |

## Pin semantics

- HWE-Bench: with conventional names ("USBD, USBP, CLK, SDA, TXD, RXD, RST") connection accuracy is "extremely high"; multiplexed or redundant pins (parallel grounds) cause "serious omissions or connection hallucinations" ([2603.18102](https://arxiv.org/abs/2603.18102)) [P].
- PCBSchemaGen 32-role pin ontology in 7 groups ([2602.00510v2](https://arxiv.org/abs/2602.00510)) [P]: supply vdd/gnd; signal I/O (sense ±, out ±); logic; MOSFET gate, drain, source, **kelvin source**; **buck vin, gnd, sw, fb, en, boot**; half-bridge hb, hs, ho, lo; transformer and passive. Four predicate templates: supply-pair, must-be-connected, driving-pair, diff-pair-distinct.

## IBIS 7.2 keywords

Spec read directly [P] ([PDF](https://ibis.org/ver7.2/ver7_2.pdf)). IBIS holds facts no other source has; no tool uses IBIS to classify nets for layout (open opportunity) [P].

| Keyword | Layout-relevant content |
|---|---|
| `[Pin]` | signal_name + model_name per pin; reserved **POWER, GND, NC**; optional R/L/C package parasitics |
| `[Diff Pin]` | non-inverting pin, `inv_pin`, `vdiff`, `tdelay_typ/min/max`: **authoritative pairing, independent of net names** |
| `Model_type` | Input, Output, I/O, 3-state, Open_drain/sink/source, ECL variants, Terminator, Series; **Input_diff, Output_diff, I/O_diff, 3-state_diff**; Vinl/Vinh thresholds |
| `[Ramp]` | dV/dt **20–80%** into 50 Ω, typ/min/max (example 2.20 V / 1.06 ns) |
| `[Model Selector]` | alternative drive strengths |

- A practitioner guide calls `[Ramp]` "the best place to get rise and fall times" for constraints ([PCEA](https://pcea.net/wp-content/uploads/2022/04/High-Speed-Constraint-Values-v2-Pfeil.pdf)) [S].
- KiCad ingests IBIS for simulation: fields `Sim.Library`, `Sim.Ibis.Pin`, `Sim.Ibis.Model`; helper symbols IBIS_DEVICE, IBIS_DEVICE_DIFF; KiCad ships no IBIS models [P].

## Open questions

- Fraction of BOM parts with IBIS files: unquantified.
- No measured accuracy for net-role classification on PCB netlists.
- Allegro and Xpedition constraint managers not checked for IBIS-driven classification.

## Sources
- [netlist_datasheet_understanding.md § 2](../../../research_notes/LLM%20driven%20PCB%20placement%20and%20routing/netlist_datasheet_understanding.md)
