<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# exact-repack: CP-SAT repack of what the closed loop leaves illegal, placement only (2026-11-23)

haslam on main 1cdbf617 plus this branch (a5fe7587). Placement only, counted work, seeds 8 and 9, one fresh process per
run, same harness and budget as crowded-ab2 (`scripts/place_ab.py`, `scripts/job.sh`). Arms: control, and
`exact_repack=1`. KiCad errors whose items all belong to one footprint are counted apart (in-fp), not as placement
errors.

| board | seed | legal | exact findings | KiCad placement errors | part shorts | HPWL | in-fp |
|---|---|---|---|---|---|---|---|
| itsybitsy-rp2040 | 8 / 9 | no -> no | 2 -> 2 / 2 -> 2 | 2 -> 2 / 2 -> 2 | 0 -> 0 | same | 0 |
| itsybitsy-esp32 | 8 | no -> no | **60 -> 34** | **83 -> 38** | **31 -> 0** | 607 -> 666 (+10 %) | 1 |
| itsybitsy-esp32 | 9 | no -> no | 9 -> 9 | 6 -> 6 | 2 -> 2 | same | 1 |
| qt-py-esp32-c3 | 8 / 9 | no -> no | 37 -> 37 / 60 -> 60 | 35 -> 35 / 154 -> 154 | 0 / 46, same | same | 4 |
| xenon | 8 / 9 | no -> no | 60 -> 60 / 60 -> 60 | 116 -> 116 / 92 -> 92 | 32 / 26, same | same | 42 |
| fercus | 8 | **no -> yes** | **29 -> 0** | **26 -> 1** | **10 -> 0** | 249 -> 382 (+53 %) | 0 |
| fercus | 9 | **no -> yes** | **12 -> 0** | **13 -> 1** | **1 -> 0** | 206 -> 502 (+143 %) | 0 |
| doorman | 8 / 9 | no -> no | 12 -> 12 / 12 -> 12 | 6 -> 6 / 9 -> 9 | 2 / 3, same | same | 0 |
| olimex-lora | 8 | no -> no | **4 -> 60** | **4 -> 64** | **0 -> 23** | 479 -> 485 | 0 |
| olimex-lora | 9 | **yes -> no** | **0 -> 60** | **0 -> 67** | **0 -> 24** | 578 -> 535 | 0 |
| snappergps, bioamp, sphale, splinky | 8 / 9 | yes -> yes | 0 -> 0 | 0 -> 0 | 0 | identical poses | 29 (snappergps) |

Failing stratum (14 board-seeds): legal 1 -> 2 (fercus twice gained, olimex-lora seed 9 lost). Crowded stratum: no
change (identical poses).

## Why
- **fercus:** the repack makes it exactly legal on both seeds (the closed loop leaves 12-29 findings), with KiCad's
  one remaining error a 'clearance' item. The cost is wirelength: +53 % and +143 %. The free level moves every
  part, and the displacement term outweighs HPWL.
- **olimex-lora regresses:** with the option on, the closed loop gets half its time (REPACK_SHARE); on lora the
  full time is what makes it legal or nearly so. With half it ends with 68-72 findings, and the box model of that
  state is infeasible (dropping edge or copper frees it), so nothing is kept. The regression is the time split,
  not a kept repack.
- **itsybitsy-esp32 seed 8:** shorts 31 -> 0 and placement errors 83 -> 38, at +10 % HPWL. It cannot be legal: the
  JP2/JP4 rows cannot keep the 0.5 mm edge clearance in any rotation (35.70 mm against a 35.56 mm board; the
  human layout breaks it too), and their edge findings are what is left.
- **itsybitsy-rp2040:** control already ends with only those 2 unavoidable edge findings.
- **qt-py:** no packing found in the time (UNKNOWN); copper binds. The human layout is illegal here too.
- **xenon:** the box model is infeasible (copper, and on seed 8 also edge, bind). HEAD1 is left unplaced in both
  arms.
- **doorman:** no packing found; edge (and on seed 9 courtyards) bind.
- **Counted work:** the repack's solves are charged at 2.4 x the CP-SAT rate (measured 8-24 s of solver wall per
  dtime unit). With that, its wall stays at or under its charge (e.g. fercus 8.9 s of wall for 11.9 s charged).

## Verdict
Not a default, and not proposed as is: one regression (olimex-lora, from halving the closed loop's time), and the
fercus gain costs 1.5-2.4 x wirelength. Next, if pursued: give the closed loop its full time and run the repack
only on the time left (or only after the loop stalls), and weight HPWL over displacement on the free level. Then
rerun on these boards.

## Round 3 (2026-11-23): stall handoff, HPWL-weighted free level (cef6a954, b09c1aa2)

The closed loop keeps its time; with the repack on, the repair ends once no move has succeeded and the findings
have not fallen for max(5 s, 25 % of its time), and the repack gets the rest. The free level's first packing
weighs HPWL (1) and displacement (5). Same boards, seeds and control rows.

| board | seed | legal | exact findings | KiCad placement errors | part shorts | HPWL |
|---|---|---|---|---|---|---|
| itsybitsy-rp2040 | 8 / 9 | no -> no | 2 -> 2 | 2 -> 2 | 0 | same poses |
| itsybitsy-esp32 | 8 | no -> no | **60 -> 22** | **83 -> 27** | **31 -> 0** | +9 % |
| itsybitsy-esp32 | 9 | no -> no | 9 -> 9 | 6 -> 6 | 2 -> 2 | same poses |
| qt-py-esp32-c3 | 8 | no -> no | 37 -> 39 | 35 -> 37 | 0 -> 1 | -2 % |
| qt-py-esp32-c3 | 9 | no -> no | 60 -> 60 | 154 -> 154 | 46 | same poses (no slack) |
| xenon | 8 | no -> no | 60 -> 60 | 116 -> 116 | 32 | same poses |
| xenon | 9 | no -> no | 60 -> 60 | 92 -> 121 | 26 -> 26 | same |
| fercus | 8 | **no -> yes** | **29 -> 0** | **26 -> 1** | **10 -> 0** | +32 % |
| fercus | 9 | **no -> yes** | **12 -> 0** | **13 -> 1** | **1 -> 0** | +15 % |
| doorman | 8 | no -> no | 12 -> 12 | 6 -> 6 | 2 | same poses |
| doorman | 9 | **no -> yes** | **12 -> 0** | **9 -> 0** | **3 -> 0** | +3 % |
| olimex-lora | 8 | no -> no | **4 -> 60** | **4 -> 64** | **0 -> 23** | +1 % |
| olimex-lora | 9 | **yes -> no** | **0 -> 60** | **0 -> 67** | **0 -> 24** | -8 % |
| snappergps, bioamp, sphale, splinky | 8 / 9 | yes -> yes | 0 -> 0 | 0 -> 0 | 0 | identical poses |

Failing stratum: legal 1 -> 3 (fercus x 2 and doorman seed 9 gained, olimex-lora seed 9 lost). Crowded stratum
unchanged. The one remaining KiCad error on the legal fercus boards is a 'clearance' item.

**It does not pass:** olimex-lora seed 9 loses its legality again. In control, lora's repair needs 79-88 s and its
first successful move (an eviction that clears most findings) comes only after more than 21 s of failed tries; the
stall window (max(5 s, 25 %) = about 21-23 s) ends it before that. The repack's box model of the state left is
infeasible (edge and copper bind), so nothing is kept. The same early stop made xenon seed 9 (92 -> 121 KiCad
errors) and qt-py seed 8 (37 -> 39) slightly worse where the repack then found nothing.

A time window cannot tell a slow repair that is about to succeed from a stalled one. Next, if pursued: hand off
only on a structural stall (a full round of culprits with no successful move, or reseed attempts that end no
better), or run the repack on a copy of the state and keep the better of the two (the repair's full result or
the repack's), which needs the loop's time split again; or keep the repair whole and give the repack time from
the next stage only when the loop ends illegal.

## Round 4 (2026-11-23): after the placement, on time from the next stage (the proposed method)

The closed loop is untouched. `pipeline.repack_after` runs the repack once placement is done, only when it ends
with exact findings, on min(30 s, 10 % of the next stage) beyond the placement's own time (here 30 s: the next
stage is 70 % of the board's budget). Same boards, seeds and control rows (made on main 1cdbf617).

| board | seed | legal | exact findings | KiCad placement errors | part shorts | HPWL | repack charged (s) |
|---|---|---|---|---|---|---|---|
| itsybitsy-rp2040 | 8 / 9 | no -> no | 2 -> 2 | 2 -> 2 | 0 | same poses | 28.4 / 28.5 |
| itsybitsy-esp32 | 8 | no -> no | **60 -> 35** | **83 -> 40** | **31 -> 0** | +28 % | 32.6 |
| itsybitsy-esp32 | 9 | no -> no | 9 -> 9 | 6 -> 6 | 2 | same poses | 29.4 |
| qt-py-esp32-c3 | 8 / 9 | no -> no | 37 / 60, same | 35 / 154, same | 0 / 46 | same poses | 26.3 / 26.3 |
| xenon | 8 / 9 | no -> no | 60 / 60, same | 116 / 92, same | 32 / 26 | same poses | 23.5 / 16.7 |
| fercus | 8 | **no -> yes** | **29 -> 0** | **26 -> 1** | **10 -> 0** | **+32 %** | 28.2 |
| fercus | 9 | **no -> yes** | **12 -> 0** | **13 -> 0** | **1 -> 0** | **+33 %** | 28.0 |
| doorman | 8 / 9 | no -> no | 12 / 12, same | 6 / 9, same | 2 / 3 | same poses | 26.2 / 27.1 |
| olimex-lora | 8 | no -> no | 4 -> 4 | 4 -> 4 | 0 | same poses | 16.4 |
| olimex-lora | 9 | yes -> yes | 0 | 0 | 0 | identical (not run) | 0 |
| snappergps, bioamp, sphale, splinky | 8 / 9 | yes -> yes | 0 | 0 | 0 | identical (not run) | 0 |

- Legal on the failing stratum 1 -> 3 of 14 (fercus on both seeds), none lost; the crowded stratum is untouched.
- Wherever the repack keeps nothing, the poses are identical to control: it only adds time.
- **Routing-time cost:** where it fires (every failing board-seed but legal lora seed 9), it charges 16-33 s,
  at most 32.6 s against its 30 s share (the exact checks after the last solve run over it). In the joint loop the
  first route gets 0.6 of what is left, so it loses about 10-20 s on a 500-1100 s budget.
- What binds where it fails: itsybitsy JP2/JP4 cannot keep the edge clearance in any rotation (35.70 mm on a
  35.56 mm board); qt-py copper; xenon copper (and edge); doorman edge and courtyards; lora edge and copper. These
  are box-model verdicts, an over-approximation, not proofs that no legal layout exists.
- KiCad's one error left on fercus seed 8 is a 'clearance' item; seed 9 is clean.
