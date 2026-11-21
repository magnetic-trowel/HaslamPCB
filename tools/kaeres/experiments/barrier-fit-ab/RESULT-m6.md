<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# barrier-fit2-ab-m6: result on the kept boards (2026-11-20)

**Verdict: gain.** On the kept boards, `barrier_split=2` lowers per-attempt opens by 28 %, the 95 % CI is below 0, and
every guard holds.

There are two open items:
- The len42 family loses on 5 of its 6 boards.
- The four boards that motivated the board-by-board reading are mostly untested here: three of them were parked by the
  trim.

## Setup
- **Arms.** Control `0f9b70f9fcf9` and split2 `e630fe4ddf1b`, both at kae and harness c71761c4. Freerouting is fork
  37b1a8b, under counted work, with k=1.
- **Primary.** Per-attempt fresh first-wave opens from `restarts.json`, paired by seed. This is the m4 addendum's primary.
- **Boards.** 46 boards finished, all `ok`. That is the 44 `kept_boards` of `TRIM-2026-11-20.json`, plus two boards
  that are in neither list (arthursaunier output-mixer and tommie1236 keypad). The 30 parked boards were not resubmitted.
- **Data.** Scripts and rows are in the local analysis work dir: `collect.py`, `addseeds.py`, `runs-m6.jsonl`
  and `m6.txt`.

## Primary

| set | n | effect | 95 % CI | SD | MDE80 | lower / higher |
|---|---|---|---|---|---|---|
| all 46 | 46 | −28.2 % | [−42.2, −13.1] | 0.71 | 34 % | 26/15 |
| kept list only | 44 | −29.3 % | [−43.3, −13.9] | 0.72 | 36 % | 25/14 |
| acting (5 inert removed) | 41 | −31.1 % | [−45.6, −14.2] | 0.75 | 39 % | 26/14 |
| repo-family cluster bootstrap (31 families) | 46 | −28 % | [−45.9, −8.4] | – | – | – |
| without len42 | 40 | −33.5 % | [−47.8, −17.9] | 0.73 | 38 % | 25/10 |

The direction matches both earlier builds: −45 % on acting boards at ef6cc04 and −25 % at ac5ed85.

## Guards
- **Delivered opens:** −20.4 % [−34.8, −5.0], from 715 to 655. Clean boards rise from 3 to 8.
- **`legal`:** 31 boards in both arms, and no board flips either way.
- **Illegal first-wave seeds:** 1 in control against 4 in split2. gameinstance esp32-audio has 1 and 3, and
  quinnfreedman biodata has 0 and 1. This is not a pre-registered guard; it is reported here.
- **DRC errors:** 1084 → 1027, a ratio of 0.95.
  - Falling types: copper_edge_clearance 291 → 265, solder_mask_bridge 364 → 345, hole_clearance 107 → 100 and
    starved_thermal 11 → 2.
  - Rising type: clearance 135 → 139 (+3 %, within the 3.4 % A/A spread).
- **Near-miss closure,** reported apart: there are 81 seed pairs where either arm is within 5 opens of clean.
  - On those pairs split2 has −52 % [−63, −40], with 46 lower and 8 higher.
  - Zero-open seeds rise from 22 to 44.
  - These pairs overlap the primary, so they are not a separate test.
- **Big boards:** none in this stage. That is what the canary below is for.
- **Cost:** 104 CPU-h for the 46 jobs.

## Board by board
**Large gains, mostly on small eurorack and synth boards.**
- gridbugs diode-ladder: 9 → 0 opens delivered.
- gridbugs arduino-delay: 3 → 0.
- alloyed 4gates: 2 → 0.
- glaubinator rca: 11 → 1.
- weee psutap: 2 → 0.
- 4 of the 6 fihdi eurorack boards gain: −1.43, −1.20, −0.58 and −0.50.
- arthursaunier output-mixer: −0.27, a gain on its third build.

**The len42/synth family loses on 5 of 6 boards.** The per-board d values are: bus-driver +0.31, buff-mult +0.42,
attenuverter +0.20, filter2 +0.15, envelope2 +0.04 and noise-sh −0.07. len42-synth-adder lost on both earlier builds,
so this is a consistent family effect, not noise. It is the main item to study before adopting a default.

**The four boards named for reading:**
- **tommie1236 keypad:** +0.27, with delivered opens 1 → 3. It is now a harm on three builds.
- **len42-synth-adder:** parked, not run on m6. Its family harm is replicated above.
- **mprosk wow-and-flutter:** parked, not run on m6.
- **fabriziotappero esp32-li-ion:** parked, not run on m6. Its legality loss on both earlier builds is therefore
  **untested on this build**. Guard 2's pass here does not cover the one board known to fail it.

**Other harms:**
- phyx rpi-fez-dac: +0.47, with delivered opens 0 → 1.
- gameinstance esp32-audio: +0.38, with delivered opens 18 → 31 and 2 more illegal first-wave seeds.
- rabidaudio chorus: +0.34.
- bleepsound vco: +0.32, with delivered opens 24 → 40.

**Inert:** 5 boards gave the same placement in both arms: arthursaunier multiplexer, damianevans busker, erikvanzijst
radioclock, rabidaudio buzz and aroum pncateho.

## Next
**Canary submitted (standing rule).**
- Experiment `barrier-fit2-canary-m6`, owner `exp-barrier-fit2-canary-m6`, kaeq #116751-#116770.
- Prio 5, class timed, both arms on the 10 boards of `canary-big.txt`, k=1, seed 0. That is 20 jobs, with 1253 jobs
  queued ahead of them.
- None of the canary boards is a true split; the barrier scan lists one region or nothing for them. So split2 should
  run the control's path there, and the canary checks for crashes and identity, not effect.
- Pass rule, set before any result: every run valid, no timeouts or ceiling hits, outputs identical (or opens and errors
  within 1.03x C), and no error type added.
- Expected cost: about 60-90 CPU-h. The restart portfolio runs at 4 CPUs on big boards.

**Before any default PR:**
1. Read the len42 family boards at 0 CPU-h. Their regions are panel PCB pairs: find which parts fit_split moves and why
   opens rise there.
2. Run fabriziotappero esp32-li-ion once (k=1). Its legality loss is the known guard failure, and the trim parked it.

Commits stay local, because the push is blocked by missing credentials.

## Canary result (2026-11-20, barrier-fit2-canary-m6, 20 of 20 ok)
**The canary passes the pre-set rule.** Pooled opens are 5546 vs 5512 (1.006x), errors 731 vs 730, and no error type
was added.
- No crash, timeout or over-time run. The longest run is beagleplay at 9,624 s, against a ceiling of 15,916 s
  (4x its 3,979 s budget).
- The only bug records are the boards' own `drc` records, the same in both arms.

**Identity:**
- 9 of 10 boards have the same placement in both arms.
- On two of them the router output differs by one open: sdi-mipi 299/298 and dvhx 4/3. That is router noise, not the
  mechanism.

**sinara zotino is a real split, not a fault.**
- kae's `true_split` gives it 2 regions (14,746 and 1,178 mm²), with 0 cross nets, not over capacity. The barrier scan
  covered only usable boards, so it never listed zotino.
- Fresh first-wave seeds mostly fall: 575/488, 444/423, 465/496, 448/445, 351/345, 285/276.
- The resumed attempts and the delivered board are worse: 86/99 → 128/122, and delivered opens 85 → 121.
- Errors go 15 → 16.
- This is a big board, and one board decides nothing. It is reported, not read as harm.

## Why the len42 boards lose (existing runs and `true_split` on the corpus boards; no queue time)
**Main finding:** the harm follows the split's assignment, not the family.

| boards | n | effect | lower / higher |
|---|---|---|---|
| some signal net crosses regions (`cross_nets` > 0) | 15 | +0.2 % [−12.1, +14.0] | 5/8 |
| no signal net crosses regions | 31 | −38.9 % [−54.9, −20.9] | 21/7 |

`moved_for_room` > 0 (the capacity rule moved parts between regions) gives almost the same split: 13 boards at +2.3 %
against 33 at −37.6 %.

**The len42 boards** are 2-region panel PCB pairs:
- **4 cross nets each, or more:** buff-mult 7, bus-driver 4, attenuverter 10, envelope2 23.
- **Parts moved for room:** buff-mult 5, bus-driver 9, attenuverter 7, envelope2 26.
- **What changes:** split2 halves their placement HPWL (buff-mult 1,350 → 666, bus-driver 956 → 457), yet opens rise.
  All of the opens are "geometry" blocks. The split packs each region on its own, and the parts on the cross nets lose
  their pull toward the other region's connector.
- **Exceptions:**
  - filter2 has 0 cross nets and still loses (+0.15). It has 74 parts assigned by area.
  - noise-sh (0 cross nets) is neutral.

**Gainers.** The large gains (gridbugs, fihdi, alloyed, glaubinator) all have 0 cross nets and no parts moved.

**What this implies.** A gate (split only when no signal net crosses regions) is suggested, but it is post hoc. It needs
its own pre-registered test, on the parked boards or fresh boards. It is not part of the default PR.
