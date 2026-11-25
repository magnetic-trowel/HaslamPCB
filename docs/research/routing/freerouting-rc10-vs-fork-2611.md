<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Upstream Freerouting 2.6.0-RC10-era nightly vs our fork (R11, 2026-11-08)

Scope: whether upstream's 2.6.0 line, which carries RipupMemory, the partial-board optimizer and the JTS geometry change, routes better than the fork as the standalone control router. Not here: RipupMemory ported onto the fork -> [freerouting-ripupmemory](freerouting-ripupmemory.md); the fork's own fixes -> [haslam-freerouting-bridge](haslam-freerouting-bridge.md).
Keys: R11, RC10, 2.6.0-RC10, nightly 099368c, fork 2e1125a, stock 2.5.0, r11-rc10, r11-bridge, freerouting-nomp, maxPasses 0, control router, rebase vs refresh

**Status:** did not work: the nightly loses to the fork; the fork stays the control (decided 2026-11-09). Stock 2.5.0 and RC10 are no longer run as controls (user, 2026-11-11).
**First published:** this page, 2026-11-15. Plan pre-registered 2026-11-08 before any run (decision rule below); haslamres experiments `r11-rc10` (213 boards) and `r11-bridge` (8 boards); harness [353d3e0](https://github.com/magnetic-trowel/HaslamPCB/commit/353d3e0698e94c7504d8bb6df285c485754a90d9). No code: three binaries behind the same haslambench Freerouting adapter, with a wrapper that removes the `-mp` pass cap.

## Arms
| Arm | Router commit | Notes |
|---|---|---|
| nightly | upstream [099368c](https://github.com/freerouting/freerouting/commit/099368c6d5a9196aa384ec435901d2070bb612b6) (RC10 commit `4c83f2832` + 12) | upstream has no RC10 tag or release; the rolling `SNAPSHOT` asset of 2026-11-06 reports `v2.5.1-SNAPSHOT`; includes JTS `PlanarArea` (`003033236`) and the stagnation live-loop fix merge (`38232d325`) |
| fork | [2e1125a](https://github.com/magnetic-trowel/freerouting/commit/2e1125a3f0dd0226d74b07d58143fd472174c315) | production pin then |
| stock 2.5.0 | [b647a2f](https://github.com/freerouting/freerouting/commit/b647a2f824cfbc54bc4dcaee71b03b7cd945eb76) | reference only |

One run per board per arm, attempt 0, 900 s, `-mt 1`, 2 Java processors, no pass cap (all three report `maxPasses = 0`; stagnation constants identical: 10 passes, threshold 0.5, 3 recovery passes), one haslamq job per board with the arms side by side. KiCad 10.0.7 scores. 213 merit boards.

## Decision rule (pre-registered)
The nightly replaces the fork only if all hold: (1) total opens ≥ 5 % lower with a paired sign-flip p < 0.05; (2) cp1 ≥ +3.0 pp with exact McNemar p < 0.05; (3) DRC errors ≤ 1.02 × fork and no type (≥ 30 errors) worse by > 25 % at p < 0.05. A tie keeps the fork.

## Results
| Arm | cp1 | clean boards | opens (213) | completion | DRC errors / board | timeouts | CPU h |
|---|---|---|---|---|---|---|---|
| nightly 099368c | 0.131 | 28 | 9,390 | 0.858 | 37.26 | 44 | 15.4 |
| fork 2e1125a | 0.150 | 32 | 6,017 | 0.883 | 39.60 | 30 | 13.4 |
| stock 2.5.0 | 0.103 | 22 | 10,032 | 0.839 | 55.78 | 33 | 14.6 |

- Paired, 211 boards: opens nightly 7,728 vs fork 5,107. Neither timed out (168 boards): 829 vs 707, nightly worse on 52, better on 25. Both timed out (29 boards): 6,500 vs 4,033. So the budget does not explain the gap.
- By split, cp1 nightly / fork: A 0.533 / 0.600 (15 boards), B 0.208 / 0.194 (72), C 0.040 / 0.071 (126); 4 layers 0.029 / 0.088 (34).
- On dilemma (1,352 pads, smoke) the nightly spent about 777 s in 20 fanout passes of about 30 s and had about 20 s left for routing; on magtag it logs `Polyline: must contain at least 2 different points` thousands of times.
- Through the bridge (`r11-bridge`, 8 boards, 300 s, seed 0, directional only): 8/8 runs ok, clean 2 vs 2, opens 17 vs 27 (nightly vs fork).
- Sources: haslamres `r11-rc10` and `r11-bridge` reports; 100 human-reference runs in the report were scored by an older evaluator (marked there).

## Verdict
Did not work: the nightly fails rules 1 and 2 (more opens, fewer clean boards); the fork stays. Upstream changes reach haslam only by porting single commits and testing each (RipupMemory: [freerouting-ripupmemory](freerouting-ripupmemory.md), no gain). A full rebase onto 2.6.0 (ledger R12, estimated 2–3 days thin, 5–8 days full) waits for the 2.6.0 tag.

## Lessons for running routers
- A test build installed under the bridge's default prefix becomes the default: when `HASLAM_BRIDGE_FREEROUTING` is unset, `haslam.route.freerouting.command()` picks the newest `haslam-freerouting-fork-*` by mtime, so this experiment's no-cap wrapper (and later test builds) became the default for unpinned runs on 2026-11-08/10; haslamres methods set the variable and were unaffected. Test builds now go under another prefix (`haslam-fr-*`).
- haslambench's `freerouting_cmd` picked RC10 by name sort from 2026-11-09; fixed in PR #62 (`HASLAM_FREEROUTING`, else the pin file, else an error; the router binary's sha256 is recorded). An audit found no stored run affected. Set `HASLAM_FREEROUTING` / `HASLAM_BRIDGE_FREEROUTING` explicitly in every recipe.

## Open questions
- Whether the 2.6.0 release, at a longer budget (upstream's own benchmark gave 360 min), changes the big-board result.
