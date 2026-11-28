<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# obd-solar: independent design review

Reviewer: Claude (independent pass, 2026-11-28). Scope: revision A as committed: `design.py`, `parts.py`,
`DESIGN.md`, `out/report.md`, `out/netlist.json` and `out/bom.csv`. I read these datasheets:

- Consonance CN3767 Rev 1.0;
- ADI LTC3115-1 Rev. E (p.6 and p.35 were rendered and read as figures);
- TI TPS709 SBVS186H and TLV7031 SLVSE13J.

I did not read the STM32G071 datasheet (ST was unreachable), the USB PD specification, or the discrete
datasheets (AO3407A, SS34, SMBJ/SMAJ, Littelfuse 466, Sunlord SWPA). Where I quote those I say so. Page
numbers are the datasheets' printed page numbers. `design.py:N` means the line in `design.py`.

Keys: obd-solar, review, CN3767, LTC3115-1, TLV7031, reverse-current block, load dump, USB PD, standby current

## Verdict

**Not ready to order.** The architecture suits the brief, and most of the detail is right:

- The panel side draws nothing from the battery at night.
- The CN3767 is isolated behind Q203.
- The FETs and diodes face the right way.
- Every IC pinout I checked matches its datasheet.

Problems remain, though:

- One pin strap means the USB-C output cannot deliver more than about 0.1 A (B-1).
- The 18 W rating is not supported by the datasheet's current or thermal figures.
- The vehicle-side protection would not survive a suppressed load dump, and its fuse cannot safely break a
  car-battery fault.
- The reverse-current comparator has a tolerance window wide enough to latch on.

Counts: **1 BLOCKING, 7 MAJOR, 15 MINOR, 4 NOTE.**

## What was checked and found correct

- **Pinouts** (netlist.json against the datasheets):
  - CN3767 SSOP-10 (DS p.1, p.3);
  - LTC3115-1 FE-20 pins 1-21, with the exposed pad (pin 21) on PGND (DS p.2, p.11-12);
  - TLV7031 SOT-23-5 (Table 4-1);
  - TPS709B DBV: GND 1, IN 2, OUT 3, NC 4, EN 5 (Table 5-1);
  - SOT-23 FETs: 1 G, 2 S, 3 D;
  - diode and electrolytic polarities;
  - STM32G071K pins 4/5/6/7/8/17/18/24/25 against KiCad's `STM32G071K_8-B_TxN` (PA8 = UCPD1_CC1,
    PB15 = UCPD1_CC2).
- **CN3767 support parts** (DS p.3, p.7-8):
  - 100 nF from VG to VCC;
  - COM network of 120 Ω + 220 nF;
  - three-part input capacitor and electrolytic + ceramic output;
  - AO3407A switch;
  - RCS 0.18 Ω gives ICH = 0.67 A (VCS 113-127 mV, so 0.63-0.71 A);
  - MPPT divider 1.205 × 13.7 = 16.5 V;
  - trickle, recharge and float thresholds in REQ-2 = 75 %, 83.95 % and 91.57 % of 14.8 V.
- **LTC3115-1 values against DS p.35** (12 V, 1 MHz):
  - RT 35.7 k; L 10 µH;
  - RTOP 1 M; CFF 33 pF + RFF 10 k;
  - RFB 40.2 k + CFB 820 pF from VC to FB;
  - 0.1 µF BST caps; VCC tied to PVCC.
  - The 12 V RBOT is 249 k ∥ 249 k ∥ 340 k = 92.6 k, against the reference's 90.9 k.
  - RUN from a 3.3 V GPIO is within "RUN ≤ VIN + 0.3 V" and above the 1.26 V comparator maximum. R311
    holds it below the 0.3 V logic threshold, which gives the 3 µA shutdown (DS p.16).
- **Night isolation.** With no light, U202 is unpowered and its POR holds OUT low (SLVSE13J §6.4). R216
  keeps Q204 off, and R209 holds Q203's gate at its source.
  - Q203's body diode points CHG_OUT → VBAT, so the battery cannot reach the CN3767.
  - The inputs are fail-safe with V+ = 0 (§6.4.1), so 1.15-2.2 V on CMP_INN is harmless.
  - The only battery load in this block is R214/R215.
- **Reversed panel.** Q201's body diode is reverse-biased, and its gate divider is referred to PV_IN, which
  stays at 0 V, so Q201 is off. |VDS| ≤ Voc. D201 never sees reverse current. HZ-1 holds.
- **24 V jump start in daylight.** PV_IN ≤ 22 V < 1.022 × 24 V, so U202 turns Q203 off, and Q203 sees
  only 24 − 14.8 ≈ 9 V. At night it sees 24 V: within 30 V, at 80 %.
- **Defaults.** U401 in reset leaves U301 off (R311), FB at 5 V (R309/R310) and the VBUS discharge off
  (R313). The LTC3115-1 disconnects its output in shutdown (DS p.1).

## BLOCKING

### B-1 PWM/SYNC is tied to GND, so U301 runs only in Burst Mode and VBUS collapses above ~0.1 A

- **What.** `design.py:236` connects `"PWM": "GND"`. The note at `design.py:241-242` says "Burst Mode at
  light load", which assumes the part leaves Burst Mode by itself at higher load.
- **Evidence.** LTC3115-1 DS p.12: "Forcing this pin low places the IC into Burst Mode operation". DS p.15:
  "The output current capability in Burst Mode operation is substantially lower than in PWM mode and is
  intended to support light standby loads (typically under 50mA) … If the converter load in Burst Mode
  operation exceeds the maximum Burst Mode current capability, the output will lose regulation." There is
  no automatic change to PWM. DS p.6, curve G13 (L = 22 µH), gives the maximum Burst load at VIN = 12 V:
  about 200 mA at 5 V out and about 100 mA at 12 V out. With 10 µH it is lower, because each burst pulse
  stores ½·L·(1 A)². The reference design this board copies (DS p.35) ties PWM/SYNC to PVCC/VCC.
- **Consequence.** No PDO above about 0.1-0.2 A can be delivered. REQ-4 fails outright.
- **Fix.** Drive PWM/SYNC from a spare U401 GPIO. The input threshold is 1.5 V maximum (DS p.3), so 3.3 V
  works. Add a 100 k pull-down so the pin is defined during reset. Firmware sets PWM before it accepts any
  request above 5 V or about 100 mA. Burst Mode can stay for an attached but idle sink: PWM no-load input
  current is about 15 mA at 12 V (DS p.6, G11). If a GPIO cannot be spared, tie PWM/SYNC to VCC as on p.35.

## MAJOR

### M-1 12 V 1.5 A (and 9 V 2 A) at 11.5-12.6 V in has no margin for current, and the thermal calc is optimistic

- **Current.**
  - REQ-4 (`design.py:83-86`) advertises 12 V at 1.5 A. Its own source line cites "1.4 A at 12 V from
    10 V (DS p.15, p.35)".
  - DS p.6, curve G47 (15 µH, 1 MHz): the 12 V-out maximum load is about 1.1 A at 10 V in and roughly
    1.5-1.7 A at 11.5-12 V in. It peaks at about 2.2 A only near 15 V in.
  - This board uses 10 µH, which has more ripple and so less current (DS p.18). DS p.15 says capability
    also falls above 750 kHz.
  - The engine-off battery at 11.5-12.6 V, which is the main use case, therefore puts 12 V 1.5 A at or
    beyond the typical curve.
  - 9 V 2 A at 11.5 V in needs an average inductor current of about 2 A plus 0.12 A half-ripple. The
    primary limit regulates *average* inductor current to 2.4 A minimum (DS p.3, p.13). That leaves about
    15 % margin, which is acceptable, but the margin is still not stated anywhere.
- **Thermal.**
  - `u301_tj_rise` (`design.py:368-370`) uses 92 % efficiency and assumes "70 % of the loss in the IC".
  - The p.35 efficiency curve reads about 90-91 % at 1.5 A and 12 V in, so the loss is
    18 × (1/0.905 − 1) ≈ 1.9 W.
  - L301's DCR (29 mΩ × ~1.8 A²) takes under 0.1 W. The IC therefore carries about 95 % of the loss, not
    70 %.
  - With θJA = 38 °C/W, which is the JEDEC 4-layer figure on DS p.2, ΔTj ≈ 68 °C. On this 2-layer 1 oz
    board the real θJA will be higher.
  - At the design's own 70 °C ambient (`design.py:440`), Tj ≈ 140 °C or more. That exceeds the 125 °C E-grade
    limit and approaches the 165 °C thermal shutdown (DS p.17).
- **Fix.**
  - Advertise 12 V at 1.25 A and 9 V at 1.67 A (a 15 W cap), or prove 18 W on the bench at VBAT = 11.5 V
    and 70 °C.
  - Consider 500 kHz with 22 µH. DS p.6, G12 shows the 12 V curve reaching 2 A by 12-13 V in. This needs
    the loop recompensated.
  - Redo `u301_tj_rise` with η from the p.35 curve, about 95 % of the loss in the IC, and a 2-layer θJA
    (say 50 °C/W). Add the thermal-via array under pad 21 to the placement intent.
  - Have firmware fold the advertised power back when VBAT is low or the board is hot.

### M-2 The PDO list does not fit the USB PD power rules (Q-5 is real, not a formality)

- **What.** The PDOs are 5 V 2 A, 9 V 2 A and 12 V 1.5 A, which is an 18 W PDP.
- **Evidence (PD 3.x power rules, from memory, not re-read for this review).**
  - A source with a PDP over 15 W must offer 5 V at 3 A.
  - 12 V is not one of the normative voltages (5/9/15/20 V).
  - At 5 V out from 12 V in, buck mode, 3 A needs an average inductor current above 3 A. The LTC3115-1
    primary limit is 2.4 A minimum, 3.0 A typical (DS p.3), so 5 V at 3 A cannot be guaranteed. The design
    says the same in Q-5.
- **Consequence.** As drawn, the PDOs make a non-compliant source. Strict sinks or a PD analyser
    (REQ-4 verify) will flag it.
- **Fix.** Pick one before ordering:
  - (a) accept a 10 W PDP: 5 V 2 A, and drop or derate 9 V to stay inside 10 W;
  - (b) use a converter that can deliver 5 V at 3 A, so that an 18 W PDP is legitimate;
  - (c) record that compliance is waived knowingly.
  Then update REQ-4, which is not something firmware alone can fix.

### M-3 Vehicle transients: the SMBJ24A cannot absorb a suppressed load dump, and the parts behind it are not rated for its clamp

- **What.** A-1 (`design.py:91-92`) says "load dump suppressed by the vehicle (centralised) to ≤ 35 V;
  SMBJ24A clamps the residue (VC 38.9 V < 45 V U301 abs max)".
- **Energy.**
  - The SMBJ24A breaks down at 26.7-29.5 V (parts.py `SMBJ24A`).
  - A centrally suppressed load dump holds the bus at up to 35 V for hundreds of milliseconds, behind a
    source impedance of about 0.5-4 Ω.
  - The on-board TVS then tries to clamp the whole vehicle bus several volts below 35 V. Example: 3 A at
    about 32 V for 0.2-0.4 s is roughly 20-40 J.
  - The SMB 600 W rating is for a 10/1000 µs pulse, about 0.6 J. The TVS fails short and F101 opens:
    every load dump kills the board.
  - The same applies to a jump start above 26.7 V (24 V systems, or jump packs at 27-28 V). A-1 assumes
    exactly 24 V.
- **Ratings that the 35-38.9 V window exceeds.**
  - Q203 (AO3407A, 30 V; parts.py:126). At night it is off with CHG_OUT bled toward 0 V, so its VDS equals
    VBAT. Any VBAT above 30 V avalanches it, and AO3407A avalanche energy is not given in parts.py.
  - C101 (`design.py:138`, 35 V electrolytic) on VBAT.
  - In daylight Q203 is on until U202 reacts. R209 × Ciss gives about a 1 ms gate time constant. Until
    then VBAT reaches the CN3767 BAT/CSP pins (abs max 28 V, DS p.3). It also back-feeds PV_IN through
    L201 and Q202's body diode into D201 and the CN3767 VCC (33 V abs max).
- **Fix.**
  - Choose a TVS with VBR above the suppressed-load-dump level, for example SMCJ33A (VBR ≥ 36.7 V). It
    then handles only ISO 7637-2 pulses 2a and 3a/3b.
  - Rate everything on VBAT for its clamp:
    - Q203 → a 60 V PMOS with Vgs ≥ ±20 V. R209/R210 already limit Vgs to VBAT/2.
    - C101 → 50 V or more.
  - The SMCJ33A clamp (about 53 V at its rated current) exceeds U301's 45 V. Isolate U301 behind a 60 V
    high-side PMOS switched by U401, gated through a divider like Q203's. This also:
    - removes U301's 3-10 µA shutdown current from the standby budget;
    - gives HZ-5 a hardware cut-off (firmware can only open it);
    - lets a zener-and-transistor overvoltage turn-off open it above about 30 V.
  - State the vehicle-transient assumption as an ISO 16750-2 / ISO 7637-2 test list, and check each pulse
    against each VBAT part.

### M-4 F101 (Littelfuse 466, 50 A interrupting) is below the prospective fault current of a car battery

- **What.** `FUSE_5A` (parts.py:174-176) gives `breaking_a=50`. The fault path is battery → vehicle
  harness → OBD pin 16 → 0.5 m pigtail → F101 → D101 or a failed part.
- **Estimate.** Battery about 5-10 mΩ, harness and connector about 50-100 mΩ, pigtail about 30 mΩ. The
  prospective current is roughly 100-200 A, which is 2-4 × the fuse's interrupting rating. The trigger is
  a shorted TVS (M-3), a reversed pigtail (D101 forward) or a shorted U301.
- **Consequence.** A 1206 chip fuse asked to break above its rating can hold an arc or rupture on the PCB
  until the vehicle's own pin-16 blade fuse clears. The design has no calc of the fault current.
- **Fix.**
  - Put the 5 A protection in the pigtail as an inline mini-blade (ATM) fuse. Those are rated about 1 kA
    at 32 VDC.
  - Or pick a board fuse whose datasheet DC interrupting rating is at least 200 A at 32 V.
  - Add a `fault_current` calc and compare it with `breaking_a`.

### M-5 The reverse-current comparator's tolerance window reaches the latch-up condition

- **Mechanism (correct in principle).** Q203 turns on when PV_IN > k·VBAT with k = 1.022
  (`design.py:211-216`, calc `cmp_ratio`). With Q203 on and the panel dark, the battery can feed PV_IN
  through Q203 → R203 → L201 → SW_CHG → Q202's body diode. That holds PV_IN at VBAT − Vf. The loop is
  self-blocking only while k·VBAT > VBAT − Vf, that is, while k > 1 − Vf/VBAT.
- **Worst case, falling trip.**
  - **Resistors.** R212 −1 %, R213 +1 %, R214 +1 % and R215 −1 % give
    11.043 / 11.202 = 0.986.
  - **Comparator.** VIO ±8 mV plus V_HYS/2 up to 8.5 mV (SLVSE13J §5.7: 2-17 mV) acts on IN− ≈ 1.15 V.
    That is −1.4 %, so k_min ≈ 0.972.
  - **Diode.** Q202's body diode at tens of µA conducts at about 0.35-0.5 V hot, so the back-fed ratio is
    0.96-0.97 at 12.6 V.
  - The windows overlap. At the corners, and especially hot, Q203 can stay on after dusk and keep itself on.
- **Board leakage.** The PV-side divider is 10 MΩ (R212). A 100 MΩ surface-leakage path across R212 from
  condensation or flux in a car raises CMP_INP by about 9 %. That alone pushes k below 0.95.
- **Cost of a latch.** The board draws:
  - 44 µA into the CN3767 through this exact path (DS p.9);
  - 66 µA in R211/D205;
  - 9 µA in R204/R205;
  - about 2 µA in the other dividers.

  That totals about 0.12 mA. On top comes the panel's dark current: Q201 is on, at Vgs ≈ −4.4 V. REQ-3
  and REQ-5 both fail.
- **Fix.**
  - The PV-side divider costs nothing at night. Make it low-impedance, for example R212/R213 =
    100 k / 9.76 k scaled to the same ratio, and use 0.1 % parts for all four resistors (or a matched
    network).
  - Add about 1-2 % of external hysteresis (a high-value resistor from OUT to IN+, as in SLVSE13J §7.1.2),
    and raise k to about 1.04.
  - Check the opposite corner too. U202 must keep Q203 on in absorb:
    k_max × 15.02 V (VOC max) < V_MPPT,min ≈ 15.9 V. If it fails there, the charge current runs through
    Q203's body diode at about 0.6 V and 0.4 W in a SOT-23.
  - Better: AND the comparator with "CN3767 awake", meaning CHRG or DONE low. Both go high-Z when
    VCC < VBAT (DS p.7, Table 1), so the back-fed state cannot hold Q203 on.
  - Write the worst-case k window as a calc next to `cmp_ratio`.

### M-6 CC1/CC2 have no system-level ESD or VBUS-short protection; the waiver argument does not hold

- **What.** The waiver at `design.py:340-341` cites "STM32G071 UCPD pins have on-die ESD". HZ-4
  (`design.py:124-126`) accepts that a VBUS-CC short puts 12 V on PA8/PB15.
- **Evidence.** On-die ESD is an HBM component rating, typically 2 kV; I could not verify the STM32 figure.
  A USB-C receptacle on a car dashboard faces IEC 61000-4-2 levels of 8 kV contact and 15 kV air. A
  VBUS-CC short is a known USB-C failure mode with worn cables, and 12 V exceeds any STM32 I/O rating.
- **Consequence.** One ESD event or one bad cable destroys U401. Then U301 is uncontrolled and PD is gone.
- **Fix.** Fit ST's TCPP01-M12 (or TCPP02-M18, which is meant for sources) between J301 and PA8/PB15.
  These devices are made for this MCU family: CC over-voltage protection plus IEC ESD. HZ-4 then becomes
  mitigated, and the waiver can be removed.

### M-7 Fixed 14.8 V / 13.55 V with no temperature compensation, restarted every sunrise

- **What.** The CN3767 thresholds are internal (DS p.4), and BAT is both the current and the voltage sense,
  so no offset can be added. The charger restarts each morning, because removing and reapplying VCC begins
  a new cycle (DS p.5-6). It then holds 14.8 V until the current falls below 0.25 A.
- **Consequence.**
  - Usual practice is about −3 to −5 mV/°C per cell, around −25 mV/°C for a 12 V battery.
  - An engine-bay battery at 40-50 °C in summer should absorb at about 14.2-14.4 V. Held at 14.8 V, its
    gassing and float current can stay above the 0.25 A exit threshold for hours, so absorb can last all
    day.
  - The result is water loss in flooded batteries and dry-out or thermal-runaway risk in AGM.
  - This is the "correct charge, absorb, float" in the brief, and A-2 does not mention temperature.
- **Fix.** Either:
  - use a charger with an external voltage-feedback divider and MPPT input regulation (for example
    Consonance CN3722), and add an NTC for compensation;
  - or keep the CN3767 and add a hardware high-temperature inhibit, for example an NTC on the board or in
    the pigtail plus a comparator that holds Q203 off above about 45 °C.

  At minimum, state the limitation in A-2 and in the user documentation.

## MINOR

1. **L201 breaks the CN3767 inductor rule.** DS p.8 requires L > 5 × (VCC − VBAT) µH.
   - With the panel near Voc in trickle or float (22 V against 11-13.5 V), that is 42-55 µH. With a cold Voc
     of about 25.6 V at 13.55 V it is 60 µH.
   - The charger also starts each morning with CHG_OUT ≈ 0 V behind Q203.
   - 47 µH (`design.py:172`) meets it only at the MPPT point.
   - Use 68-100 µH; a larger SWPA8040 still has Isat ≥ 1 A. Add the rule as a calc next to `l201_ripple`.
2. **The MPPT set point has too little margin, and the Q-3 reasoning is wrong.**
   - **Tolerance stack.** With VMPPT 1.18-1.23 V (DS p.4) and 1 % resistors, V_MPPT can be as low as
     15.87 V. `vin_for_absorb` needs 16.04 V at full current, and Dmax is given only as typical (94 %, no
     minimum).
   - **Consequence at the low corner.** Absorb at 14.8 V is reached only below about 0.3 A, and barely so.
     At Dmax ≈ 92 % the charger sits duty-limited at about 14.6 V, never enters the voltage loop and never
     terminates to float.
   - **Q-3 answer.** It says "a hot panel below 16.5 V charges nothing". That is wrong: the CV loop holds
     16.5 V as long as the hot Voc (about 19.5 V at 60 °C) exceeds it. The panel then runs on the Voc side
     of its MPP, at roughly 80 % of the available power.
   - **Brief.** A fixed CV point is not "efficient MPPT" in the brief's sense. Expect 80-97 % tracking over
     temperature. Say so in DESIGN.md.
   - **Fix.** Make `v_mppt` and `vin_for_absorb` worst-case calcs.
3. **Standby budget is typical-only and misses contributors.** The 11.7 µA total (`design.py:371-373`) is
   built as follows:
   - TPS709 is entered as 1.0 µA. SBVS186H §6.5 gives IGND = 1.3 µA typ and 2.05 µA max for VOUT ≤ 3.3 V.
   - The LTC3115-1 shutdown figure is 10 µA max, and its leakage grows with temperature.
   - "0.5 µA for Q203, D101, D401, D301, C101 leakage" is not credible for a 100 µF/35 V electrolytic held at
     12.6 V and up to 70 °C. Its rated maximum is 0.01CV ≈ 35 µA, and real values are a few µA hot.
   - STM32 Stop current with UCPD attach detection remains unverified (Q-4) and rises steeply with
     temperature.
   - Typical at 25 °C is about 13-15 µA; maximum or hot is 30-60 µA.

   Even 60 µA is only about 45 mAh a month. That is still "almost zero" next to battery self-discharge,
   but REQ-5's < 15 µA would then be a typical figure, not a limit. Fixes:
   - give typ and max columns;
   - the U301 high-side switch from M-3 removes 3-10 µA;
   - use a ceramic for C101, or account for its leakage.
4. **The pin-16 current arithmetic has the wrong sign.** Q-2 (`design.py:101-103`) says "2.5 A with
   charging", and F101's note (`design.py:136`) says "plus charging". Charge current flows *out* through
   pin 16 into the battery, so it subtracts from the USB draw. The worst case is USB at full load with no
   sun: about 1.8-2.0 A at 85-90 % from 11.5 V. Correct Q-2 and the F101 note.
5. **Pin 5 is used as a power return.** J101.2 is "pins 4+5" (`design.py:135`). Pin 5 is the vehicle's
   signal ground, the ECU and CAN reference. Returning up to 2 A through it can shift that reference.
   Return power on pin 4 (chassis) only, and leave pin 5 open or connect it through a high-value resistor.
6. **Reverse battery and ISO 7637 pulse 1 are handled only by D101 forward conduction.**
   - D101 drags VBAT to about −1 to −3 V for milliseconds, and in a reversed pigtail it does so until F101
     opens.
   - Below −0.3 V (DS p.2), U301's PVIN, VIN and RUN conduct through internal body diodes. C101 is
     reverse-biased.
   - Q203's body diode is reverse-biased, so the CN3767 side is safe.
   - The 60 V high-side PMOS from M-3, gated through a divider, would also block reverse polarity for U301
     and the LDO at no standby cost.
7. **Negative ESD on PV_RAW avalanches Q201.** The waiver at `design.py:337-338` holds for a reversed panel,
   but a negative strike on a 5 m roof lead drives Q201's drain far below its source. Fit a *bidirectional*
   TVS (for example SMAJ26CA) directly at J201. It blocks a reversed panel up to its VRWM and clamps both
   polarities.
8. **The PVIN decoupling placement is not constrained.**
   - DS p.11 asks for 4.7 µF or more at PVIN, "as close to the IC as possible".
   - The only PVIN hot loop (`design.py:417`) uses C306, which is 100 nF. C102 and C103 (10 µF) sit in the
     IN block with no placement relation to U301.
   - Add one of them to the hot loop, or add a 4.7-10 µF X7R next to pin 17.
9. **The VCC capacitor is undersized after derating.** C303 is a 4.7 µF/10 V X5R 0805 (`design.py:246`),
   about 2.5-3 µF at 4.45 V. DS p.11 and p.18 ask for at least 4.7 µF. Use 10 µF/10 V, or 4.7 µF/25 V 1206
   X7R.
10. **Inductive output short.**
    - DS p.11 recommends a Schottky from GND to PVOUT when the output can be shorted through an inductive
      load. A USB cable is one.
    - D301 (`design.py:267`) is a TVS, whose forward drop at amps exceeds the −0.3 V PVOUT limit.
    - Add an SS34-class Schottky at PVOUT.
    - L301's Isat is 4.1 A, against the fast limit at 160 % of the primary limit, 4.8 A typical
      (DS p.13). Brief saturation in a hard short is likely; prefer Isat ≥ 5 A.
11. **The FB divider impedance and switching are not checked.**
    - RTOP = 1 MΩ, so VOUT moves by Ileak × 1 MΩ. FB pin current alone is up to 50 nA (DS p.3), which is
      ±50 mV.
    - 2N7002 off-state leakage and PCB surface leakage on FB9/FB12 add directly.
    - Switching RBOT steps the reference instantly. With a 3 A limit into about 45 µF, the slew can reach
      about 65 mV/µs. My recollection of the PD vSrcSlewPos/Neg limit is 30 mV/µs (not re-read).
    - The comp values are the 12 V reference values. The DS front page uses 60.4 k / 3300 pF / 15 k for
      5 V out, so 5 V and 9 V phase margin is unverified.
    - Fix: put an RC (for example 100 k + 47 nF) on the Q302/Q303 gates so RBOT changes over milliseconds.
      Simulate or bench-measure the loop at 5/9/12 V with VBAT at 11.5 V and 14.8 V (an LTspice model
      exists).
12. **R403 = 1 kΩ starves U401 at low VBAT.**
    - At VBAT = 11.5 V, LDO_IN must stay above about 3.4 V, which limits the MCU to about 8 mA.
    - An STM32G0 at 64 MHz with UCPD active can approach that; the figure is unverified (Q-4).
    - Either cap the core clock in A-3 (for example 16 MHz) or use 330 Ω. With 330 Ω, D401 takes about
      36 mA × 27 V for the duration of a clamp event, so check its pulse rating.
13. **No VBUS current sense and no hardware VBUS OVP.**
    - Firmware cannot enforce per-PDO current limits or detect a light load (needed for B-1's
      Burst/PWM choice). It relies on U301's 2.4-3.7 A limit for a 1.5 A PDO.
    - If R305 opens, FB = 0 and U301 drives VBUS to D301's clamp. D301 then carries 3 A at about 18 V and
      fails.
    - Add a small shunt with an ADC channel. Have firmware drop RUN when VBUS_SNS exceeds the requested
      voltage by more than 10 %.
14. **Smaller rating and wording problems.**
    - R312 (`design.py:269`, 1206, 0.25 W) dissipates 0.31 W if firmware leaves Q304 on at 12 V. Use 2010,
      or state it as a pulse-only rating with a firmware time-out.
    - The VBAT_SNS 10 M / 1 M divider gives a 0.91 MΩ source. 100 nA of pin leakage hot is about 1 V of
      VBAT error against REQ-6's 12.0 V threshold. Use a switched divider, or calibrate.
    - REQ-6 "12.0 V for 10 s" is measured under up to 1.8 A through about 0.1-0.2 Ω of OBD wiring, so the
      cut-off depends on the load. Compensate using the known load, or measure with U301 briefly off.
15. **Errors in the report text.**
    - A-3 says "USB-C off (R411)". The part is R311.
    - HZ-3 lists F101 as mitigation for a USB short. F101 (5 A) cannot act on a ≤ 3.7 A U301 input.
    - REQ-3's verification ("battery current < 3 µA") cannot be measured at the board terminals, which
      also carry roughly 12 µA of other loads. Specify the Q203 branch current instead.
    - `qb_vgs_jump` (`design.py:362`) checks Vgs at a jump start, but Q203 is off then (U202). The relevant
      stress is VDS = VBAT at night (M-3).
    - The F101 waiver (`design.py:342-343`) argues about open-fuse voltage. The real gap is the
      interrupting rating (M-4).
    - `ambient_c=(-30, 70)`: CN3767 is rated −40 to 85 °C ambient. A board under a sun-loaded dashboard can
      exceed 70 °C, so state where the board lives.

## NOTE

1. **Q-1 and Q-4 are still blocking.** Q-4 matters more now: U401 is the only thing turning the USB
   converter off (HZ-5), and its standby current is the largest unverified entry.
2. **STM32G0 dead-battery Rd.** Leaving DBCC1/DBCC2 open is right for a source. I recall that firmware
   must also set the UCPD1_STROBE bit (SYSCFG) so that the dead-battery pull-downs are released from the CC
   pins. Not verified here; add it to A-3.
3. **Battery disconnected in sunlight.** With J101 unplugged and the panel lit:
   - the CN3767 charges CHG_OUT to float through Q203's body diode, and VBAT rises to about 13 V;
   - U401 boots;
   - a USB sink can then draw from a 0.67 A, CC-limited source.

   This is harmless, but firmware should refuse a PD contract when VBAT is not a real battery (for example
   when VBAT_SNS ripple tracks the panel).
4. **Not verified.**
   - All STM32G071 electrical figures;
   - AO3407A avalanche and IDSS at temperature;
   - SS34 leakage;
   - the SWPA inductor ratings (parts.py cites LCSC only);
   - the Littelfuse 466 interrupting rating (taken from parts.py);
   - the PD specification numbers in M-2 and Minor 11.

## Recommended order of work

1. B-1 (PWM/SYNC to a GPIO).
2. M-3 and M-4 together: TVS VBR > 35 V, 60 V Q203, a 60 V PMOS isolating U301 (which also helps Minor 3
   and Minor 6), and a fuse with an adequate interrupting rating.
3. M-5 comparator window.
4. M-6 TCPP0x.
5. Settle the PDO list (M-1, M-2).
6. Decide on temperature compensation (M-7).
7. Then the Minor items.
8. Re-run the build so the calcs (worst-case k, L201 rule, U301 Tj, standby typ/max, fault current) are
   checked by the pipeline rather than by hand.

## Designer's response (2026-11-28)

| Finding | Response |
|---|---|
| B-1 PWM/SYNC tied low (Burst Mode, < 50 mA) | **Fixed.** Confirmed in DS p.15 ("intended to support light standby loads (typically under 50mA) ... the output will lose regulation"). PWM/SYNC now on U401 PA6 (net BB_MODE) with R316 1 M to GND: Burst Mode at standby, PWM before a contract. The error came from carrying the TPS552892's MODE semantics (auto PFM) over to the new part. |
| M-1 18 W / Tj | **Fixed.** REQ-4 now 5 V 2 A, 9 V 1.5 A, 12 V 1 A; calc u301_tj_rise uses 90 % efficiency and 95 % of the loss in the IC: 48 C rise, 118 C at 70 C ambient. |
| M-2 USB PD power rules | Open: Q-5 now cites this review; the PDO list must be checked against the USB PD 3.x spec text (the review quoted it from memory). |
| M-3 load dump energy and 30-35 V ratings | Open: needs a larger TVS (SMC/SMDJ class sized for the suppressed load-dump energy) and 40 V+ parts on VBAT (Q203, C101). |
| M-4 fuse interrupting rating | Open: OBD pin 16 sits behind the vehicle's own fuse, which limits the prospective fault current; to be confirmed, else a higher-breaking fuse. |
| M-5 comparator latch window | Open: add hysteresis (feedback resistor from OUT to IN+) and lower-impedance dividers. |
| M-6 CC protection | Open: TCPP02-class protector (HZ-4). |
| M-7 temperature compensation | Open: CN3767 has none; accept (A-2) or move to an MCU-trimmed charger. |
| Minor findings | Q-3 wording, L201 rule, standby leakage terms and the pin-5 return are queued for the next revision. |
