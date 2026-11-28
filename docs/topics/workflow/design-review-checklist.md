<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Design review checklist: the independent schematic review of an LLM design

Scope: what the independent reviewer of a haslamsynth design (`designs/<slug>/REVIEW.md`, the pipeline's `review` stage) must check beyond the build's own checks, and how it must cite. Not here: the 299-item layout review -> [review-checklist](../verification/review-checklist.md); how experts review layouts -> [delegation-and-expert-review](delegation-and-expert-review.md#how-experts-review); the pipeline stages -> [brief-to-board](brief-to-board.md#s-stages-commands-and-outputs).
Keys: design review, REVIEW.md, reviewer checklist, citation discipline, mode pin, enable pin, sync pin, strap pin, pin semantics, part swap, re-review, stale mention, `part.stale_mention`, automotive transients, ISO 16750-2, ISO 7637-2, load dump, jump start, reverse battery, prospective fault current, standby current
Tags: [P] primary; [I] inference.

The build passes when every typed fact is consistent; it cannot tell whether a fact is the datasheet's. obd-solar's review found a blocking strap error that every gate passed (U301 PWM/SYNC tied low = Burst Mode, < 50 mA) and a vehicle transient no check modelled ([FRICTION #53](../../../tools/research/llm-design/designs/obd-solar/FRICTION.md), [REVIEW B-1, M-3](../../../tools/research/llm-design/designs/obd-solar/REVIEW.md)) [P].

## C. Citation discipline

1. Every finding cites its source: datasheet, revision and printed page or table; standard and clause; or a calculation in the review. The design's own claims are checked the same way.
2. The review opens with what was read and what was not (unreachable datasheets, standards not held); obd-solar's REVIEW.md is the model.
3. A number from memory is marked as such and is a question, not a finding: it cannot carry a BLOCKING or MAJOR verdict until someone reads the source. (obd-solar's reviewer quoted USB PD power rules from memory: FRICTION #53.)
4. Tags as in the design: `[S]` secondary (distributor page, vendor tool), `[I]` inference. An `[S]` or `[I]` fact that a verdict rests on is listed under the review's open items.

## P. Every pin of every IC

5. For each pin: what the netlist does with it (tied high, tied low, floating, driven by which part, at which voltage) and what that state means in the datasheet's pin-function table and operating-mode section. Read the semantics, not the pin name.
6. Mode, enable, sync and strap pins first: MODE, PWM/SYNC, EN, RUN, SHDN, UVLO, PG, SS/TR, ILIM, RT/FREQ, address and boot straps, dead-battery pins (USB-C DBCC), NC versus DNC. A strap that selects a light-load mode, a frequency or an address changes what the circuit does without any check noticing.
7. Floating inputs: is there an internal pull-up or pull-down, and what state results; is the pin allowed to float.
8. Each pin's absolute maximum against every rail it can see, including with other rails off (back-powering through ESD diodes) and during the transients of §A.
9. Exposed pads: which net, as the datasheet says (thermal, ground or a specific pin).

## S. After a part swap

10. Re-review every pin of the new part from its own datasheet (§P); never carry an old part's pin semantics over. obd-solar carried the TPS552892's "MODE low = auto PFM" into the LTC3115-1, whose PWM/SYNC low means Burst Mode (FRICTION #43, #53).
11. Find what still describes the old part: requirements, assumptions, hazards, calcs, waivers, placement relations, `d.haslam` facts, DESIGN.md. The build lists lines of design.py and DESIGN.md that name an MPN an earlier build used and no part uses now (`part.stale_mention`, history in `out/mpn_history.json`); also grep the old part's net names and figures (power, current, frequency).
12. Re-derive every calculation that depends on the part (efficiency, junction temperature, current limit, compensation, standby `i_off`).

## A. 12 V vehicle supplies

13. List the transients the design must survive as test pulses, with levels from the standard or the vehicle maker's specification, cited; never from memory: ISO 16750-2 load dump (unsuppressed test A, centrally suppressed test B), jump start, reverse voltage, starting profile, slow decrease and increase, superimposed AC; ISO 7637-2 pulses 1, 2a, 2b, 3a, 3b.
14. For each pulse: the protector's energy rating against the pulse energy behind its source impedance, not only its clamp voltage (obd-solar M-3: a TVS breaking down below a suppressed load dump absorbs the whole event) [P].
15. Every part on the protected rail rated for the clamp voltage, not the nominal (FETs, electrolytics, IC supply pins and pins reached through body diodes).
16. The fuse's interrupting rating against the prospective fault current of the battery and harness (obd-solar M-4) [P]; the reverse-battery path and what fails short.
17. Standby: every part on an always-on net has its off-state current from the datasheet's EC table, not the headline (`d.standby_budget`, FRICTION #13: a "zero Iq" ideal diode leaks 60 uA typical) [P].

## G. Every design

18. Each requirement has a verification (calc, check, bench) and the calc's inputs are cited.
19. Interface standards (USB PD power rules, I2C rise time, CAN termination) checked against the standard's text.
20. Junction temperatures from θJA or θJC at the stated ambient, with the loss that heats the part.
21. Declared voltage ranges and correlations (`frac=`, `tracks=`, `abs_v=`) each have a reason, and `v_across=`/`i_through=` overrides do not hide a real stress.
22. Every waiver is still true for the design as it now stands.

## Sources

- [obd-solar FRICTION.md](../../../tools/research/llm-design/designs/obd-solar/FRICTION.md) #13, #43, #53.
- [obd-solar REVIEW.md](../../../tools/research/llm-design/designs/obd-solar/REVIEW.md) B-1, M-3, M-4.
