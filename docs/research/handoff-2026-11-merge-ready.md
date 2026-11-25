# Merge-ready w48: branches on current main, tested, with merge commands (2026-11-24)

Companion to MERGE-CANDIDATES-w48.md. Nothing is merged and no PR is open: opening PRs was refused by the session's
permission check (no `gh` on the host; the GitHub API call was denied), so each PR below has its title and a body
file ready. Main had moved 213 commits past the tag (c2dd008a -> bc53829f, among them #111: routing default,
`kae.physics.converter`, evaluator rework); every branch was merged onto bc53829f and conflicts resolved there.

## PR branches (one per change, each = origin/main bc53829f + the change; pushed)

Full kae suite = `pytest kae/tests` with KiCad on, through kaeq. **Every PR branch fails exactly one test, which
fails identically on main itself** (job 125163: `test_place_writer.py::test_sexpr_writer_matches_pcbnew`, "pcbnew
resave timed out after 0.01s"): tests that run a CLI in-process leave `budget.start_run`'s hard deadline on the
process clock. PR 1 fixes it (main + fix: 1600 passed, 0 failed). Merge it first.

| # | Branch (head) | Change (commits) | Suite on main + branch | Verdict / evidence | Notes |
|---|---|---|---|---|---|
| 1 | `pr-w48/test-budget-clock` 2aeeee95 | conftest: drop kae.budget's clock after each test (2aeeee95, new) | 1600 passed, 0 failed | fixes main's flake | test-only |
| 2 | `pr-w48/gfix-pnr-soft` 4474c8f0 | 220bf77e, b994602c, 6c0e2d62 | 1613 passed, 1 failed (main's) | better: opens -1.00/run [-1.33, -0.67], 16/0 of 24 (gfix-pnr-soft-3) | no conflicts |
| 3 | `pr-w48/gfix-place-netrules` dfe09a38 | 5ee3486e | 1617 passed, 1 failed (main's) | better: DRC errors -3.0/run [-6.6, -0.3], clearance -91; opens undecided (gfix-place-netrules, -repro) | no conflicts |
| 4 | `pr-w48/gfix-stitch-on-kconn` 34336221 | a30c188c, 24de76dd, e3ba9c07 + 175acdf9, 34336221 | 1614 passed, 1 failed (main's) | better: opens -0.63/run [-1.20, -0.17] (gfix-stitch-on-kconn) | **34336221 needed on main** (see below) |
| 5 | `pr-w48/gfix-em-topology` c6d905c5 | 66e87717, 5d5aa277, d8abde85 | 1615 passed, 1 failed (main's) | scorer fix; neutral where it should be (gfix-em-topology) | conflicts with #111 resolved; re-score kae.excite evaluations |
| 6 | `pr-w48/gfix-dc-model-2` df956d3a | 1bab31ee, 3024f429, 2a9c3fe6, 0d204f4b | 1611 passed, 1 failed (main's) | scorer fix (gfix-dc-model, -2) | conflicts with `kae.physics.converter` resolved; re-score converter boards |
| 7 | `pr-w48/physics-advisor` badcae68 | a5276292 .. ce1cf225 (v2), on PR 6 | 1627 passed, 1 failed (main's) | feature (stores extra data; what-ifs within 4 % of full solves) | stacked on PR 6: merge after it |
| 8 | `pr-w48/kaeq-retry-scope` 0dc53224 | 228a619b | 1599 passed, 1 failed (main's); test_kaeq 82 passed | tooling | run `tools/kaeq/install.sh` after merging |
| 9 | `pr-w48/mechscreen` 51fc62e8 | efb5c508 | kaeres tests passed | tooling | README: both sections kept |

Merging 1-9 in this order onto bc53829f was tried locally: no conflicts, and the result equals `integrate-w48`
minus the facts sidecar (below).

### Open the PRs (titles and bodies ready)

Bodies: `merge-ready-w48-pr/<file>.md` beside this file (end with the Claude Code line; no @-mentions).

```bash
B=~/kae-baselines/experiments/merge-ready-w48-pr
gh pr create --base main --head pr-w48/test-budget-clock    --body-file $B/clock.md      --title "test: drop kae.budget's process clock after each test (main's pcbnew resave 0.01 s flake)"
gh pr create --base main --head pr-w48/gfix-pnr-soft        --body-file $B/pnrsoft.md    --title "pnr: locked copper is soft for the last mile, under a physics guard (G7)"
gh pr create --base main --head pr-w48/gfix-place-netrules  --body-file $B/netrules.md   --title "place: enforce net-conditioned .kicad_dru clearance rules (G8)"
gh pr create --base main --head pr-w48/gfix-stitch-on-kconn --body-file $B/stitch.md     --title "route: the last mile joins copper as KiCad 10 does, and stitches a net's fill pieces with vias (G18 + G10)"
gh pr create --base main --head pr-w48/gfix-em-topology     --body-file $B/emtopo.md     --title "kae.em: the field mesh keeps copper connected, checked against KiCad's connectivity (scorer change)"
gh pr create --base main --head pr-w48/gfix-dc-model-2      --body-file $B/dc.md         --title "kae.excite: converters in the DC and heat bands (buck-boost, unfed input, facts' eta, DNP) (scorer change)"
gh pr create --base main --head pr-w48/physics-advisor      --body-file $B/advisor.md    --title "kae.intent.advise: the physics advisor and evaluate's what-if hooks (after the dc-model PR)"
gh pr create --base main --head pr-w48/kaeq-retry-scope     --body-file $B/kaeq.md       --title "kaeq: bare retry names its owners; snapshots need no git identity; submit --kicad"
gh pr create --base main --head pr-w48/mechscreen           --body-file $B/mechscreen.md --title "kaeres: mechscreen, a static per-board count of a change's situation"
```

Without `gh`: `https://github.com/magnetic-trowel/kicad-auto-everything/compare/main...pr-w48/<branch>?expand=1`,
paste the title and the body file. Merge each with a merge commit (`gh pr merge N --merge`), in table order.

## The integration branch `integrate-w48` (8b16f83d, pushed)

origin/main + every change above, merged in the order asked, plus the solar-small kae changes judged independent:
f47d5ee4 (kae.intent.facts: a board's `.kae_intent.json` beside it, applied to its brief), 55d26604 (an explicit
`--intent`'s facts reach the brief: evaluate, wideband, pnr, status), 2bb5d30d (excite.params: a 0 V bus range clips
the duty instead of dividing by zero). Included: tested (test_intent_facts, 57 intent tests), off for every board
without a sidecar or `--intent` (benchmark boards have none), and needed to evaluate solar-small under its facts.
Not included: 4976bb92 (last-mile greedy undo; G11 was fixed on main before the tag), the kaesynth design files.
No PR made for the facts sidecar (it also rides on intent-relations; results pending there).

Full suite at 8b16f83d (job 125374): **1701 passed, 14 skipped, 0 failed**. Per-step suites: steps 1-2 only main's
flake; steps 3-5 also 11 failures + 9 errors from one import (below), fixed in 8b16f83d.

Merge it whole instead of the PRs: `git checkout main && git merge --no-ff origin/integrate-w48` (then
`tools/kaeq/install.sh`).

### Conflicts resolved (details in each merge commit)

- **em-topology x main #111** (em/mesh.py, em/kicad.py): main fixed part of the same pad-coverage hole its own way.
  The branch's `Mesh.coverage` (every cell within half a cell diagonal sub-sampled) samples a superset of main's
  outline cells; its `cells_under` contains main's terminal fallback; both replace main's. Main's canonical
  track/via order kept (vias meshed in canonical order, `via_of` indexes `b.vias`). `kae.em.topology.reference`
  also takes main's board-level copper shapes (`Board.copper`) as fill pieces.
- **dc-model-2 x main's `kae.physics.converter`** (excite/dc.py, heat.py): union. Buck-boost (merged cell) and boost
  take the branch's form (I_L = I_in; identical to main's I_out/(1-D) without the facts' eta); a buck keeps main's
  injections (input D I_out/eta, high side D I_out, losses via the controller's ground) with I_in from `_ratio`; the
  unfed-input entry for all; `_ratio`: facts' eta first, buck-boost at the cell's class eta (main's convention; the
  branch used lossless there), else main's `_cell_in`; heat's I_out and rectifier current from main's functions.
- **physics-advisor x main's evaluate** (v1, then v2 ce1cf225): both argument sets, main's Le/Lz/Rcu + `transfer`,
  `sw_cells` + `capacitive` (skipped under `sources`), both CLI flag sets; what-if pad patterns skipped under scope
  "losses" (cost unchanged there).
- **stitch-on-kconn x main** (semantic, no textual conflict): `pour_stitch` imported `repair._nets_of`, which main
  replaced with `kae.drc_items.item_nets` -> ImportError in every stitch round; fixed in 34336221 / 8b16f83d. Main's
  `copper_items` now lists zones: the KiCad connectivity test leaves them out (175acdf9).
- READMEs / SUBJECTS.md: both sides kept. kaeq-retry-scope's integration merge commit has git's default message.

## Task 1: the mesh topology reference follows KiCad's rule

`gfix-em-topology` 5d5aa277 + d8abde85 (pushed): the reference unions any two copper items of a net on a layer
whose copper touches (within 2 um, for the buffered arcs); tests: the 9-case board moved to
`kae/tests/connectivity_fixtures.py`, `test_em_topology_kicad.py` compares the reference with pcbnew's clusters at
0.25 and 0.1 mm (fails on the old rule); tag + 5d5aa277 full suite 1285 passed, 0 failed. Re-run of the topology check (77
fine-pitch boards + solar-small, 0.25 mm, old = 66e87717; 17 boards whose stored check came from an older checker
re-run at 66e87717): **splits unchanged** (fixed raster: 2 boards, both bridged, 0 after repair; unfixed raster: 169
nets on 36 boards); **joins 9 -> 3** (6 -> 2 boards) on the fixed raster, 8 -> 3 on the unfixed one; 4 boards'
reference clusters change (anobli pandora 95 -> 93, crimier blep 55 -> 52, larus vario 260 -> 259, ikajdan hot plate
93 -> 92: tracks crossing a fill, now joined as KiCad joins them); solar-small complete, nothing bridged or joined.

## Task 3: smoke of the combined build

- `integrate-w48-smoke` (2bb5d30d): invalid, every route stopped at the ImportError above (opens +4.33/run). The
  smoke found the bug.
- `integrate-w48-smoke2` (8b16f83d) and `integrate-w48-main` (main alone), bridge recipe, 6 boards x 2 seeds vs
  control-w47: main -0.17 opens/run [-0.42, 0.00], integrated -0.25 [-0.58, 0.00]; both 2 better / 0 worse, clean
  3 -> 5, starved_thermal 8 -> 6, zone opens 5 -> 4 (main) / 3 (integrated). Consistent with main + G18/G10. CPU: 6.8
  CPU-h for the three arms (over the 5 asked: the crashed arm and a main-only reference arm were added).
- solar-small A0 under its facts (`eval-intent.json`), three builds:

| | main alone | main + facts | integrate-w48 | tag + facts + em + dc-model-2 (gfix-dc-model-2) |
|---|---|---|---|---|
| complete | yes (no facts: SYS not cell-fed) | **no** (copper open for dc) | yes | yes |
| T-FB | 1.664 V | 514.1 mV | 514.1 mV | 398.7 mV |
| T-FB3 | 517.9 mV | 369.8 mV | 369.8 mV | 396.4 mV |
| T-TJ | 226.5 C (U301) | not computed | **213.1 C (U201)** | 96.4 C (U301) |
| D1 copper | 1.133 W | - | 269.7 mW | 33 mW |

  Surprises: (1) T-FB moves 398.7 -> 514.1 mV with main's evaluator (#111) alone: identical in main + facts and in
  integrate-w48, so not the merged branches. (2) **U201 (LTC2959 coulomb counter) at 1.5 W, T-TJ 213 C**: main's
  load detection makes U201 a direct load on SYS; with the facts SYS is fed by U101's cell, and the DC plan splits a
  cell's operating current among its rail's direct loads by prior, so U201 alone takes the whole cell current (1.0 A
  typical in a plan dump; main alone 0.01 A because SYS is not cell-fed there). It shows only once dc-model-2 + the
  mesh fix make the DC band compute. A scorer fix for a separate change (with its own re-score), not made here.

## Not included

gfix-thermal-ring (undecided), intent-relations (results pending), solar-small's 4976bb92 and design files.
