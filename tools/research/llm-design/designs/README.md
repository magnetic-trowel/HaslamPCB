# Designs

Boards designed from plain-language briefs with [`haslamsynth`](../synth/README.md). Each folder has:

- `DESIGN.md`: requirements, hazards, trade study, calculations, parts, placement;
- `CONNECTIONS.md`: net tables and naming rules;
- `parts.py` and `design.py`: the circuit as code;
- `REVIEW.md`: an independent review and the designer's response;
- `out/`: the generated KiCad 10 project, `intent.yaml`, BOM and `report.md`. Only `report.md`
  and `erc.json` are committed here; rebuild the rest with `haslamsynth build designs/<slug>/design.py -v`
  (deterministic up to the title-block date, `--date`).

Write-up: [docs/research/llm-design](../../../../docs/research/llm-design/README.md).
Licensing: our files are GPL-3.0-or-later (docs CC-BY-4.0); the Phoenix Contact footprint in
`liion-balancer/footprints/` is copied from the KiCad library (CC-BY-SA-4.0 with the KiCad
libraries exception), see `REUSE.toml`.

| Design | What it is | Parts | Status |
|---|---|---|---|
| [rpi-mains-relay](rpi-mains-relay/) | Pi Zero 2 W switching six 120 V receptacles, one polycarbonate enclosure, on-board listed 5 V supply, hardware heartbeat watchdog | ~70 | Reviewed twice. Checks pass; 4 blocking questions |
| [liion-balancer](liion-balancer/) | 13–16S home-pack active balancer: per-cell isolated flyback (LT8584) + ADBMS1818, hardware trips, BMS-OK enable | 448 | Reviewed. 32 errors on haslamsynth main (`rules.pad_gap`/`rules.pin_escape`, added after its review); checks passed when reviewed; 6 blocking questions |
| [leadacid-balancer](leadacid-balancer/) | 2–4 × 12 V lead-acid switched-capacitor balancer, MCU-free, fail-safe alarm | ~390 | Reviewed. 1 error on haslamsynth main (`rules.*`, added after its review); checks passed when reviewed; 4 blocking questions |
| [solar-small](solar-small/) | <= 10 W, 25 V solar charger for a 12 V lead-acid / 4S LiFePO4 battery: LTC3130 in RUN-hiccup mode, DAC-set charge voltage and panel point, LTC2959 coulomb counter, FireBeetle 2 ESP32-C6; taken through haslam place/route and physics scoring ([brief-to-board](../../../../docs/topics/workflow/brief-to-board.md)) | 68 | Checks pass; routed clean at 120 x 90 mm (one seed); not reviewed |
| [prius-solar-mppt](prius-solar-mppt/) | 2017 Prius Prime roof solar: 2 × 32 C60 strings, MPPT, isolated step-up into the Li-ion pack, car on or off, current-capped, 3-layer OV; main and battery-end boards | 485 | Reviewed. 323 errors on haslamsynth main (`rules.pad_gap`/`rules.pin_escape`, added after its review); checks passed when reviewed; 6 blocking questions |
| [bme280-array](bme280-array/) | 16 x BME280/BMP280 on one I2C port (TCA9548A), any host 1.8-12 V (MOSFET translators, TPS63900/TPS629203 dual-path 1.8 V rail, TPS3700 selector), sensor field thermally isolated by a SlotBarrier; the end-to-end test behind FRICTION.md (63 friction points, their fixes) | 90 | Checks pass; routed clean, fab package in `fab/`; not reviewed |

"Checks pass" means 0 errors, a clean KiCad ERC, and a schematic netlist identical to
the design. Remaining check findings are waived with written reasons in `out/report.md`.

**None of these is ready to fabricate.** Each has blocking questions that only the owner, an
installer or a certification body can answer, listed in its `out/report.md`. They have not
been simulated in SPICE, built, or reviewed by a licensed engineer.
