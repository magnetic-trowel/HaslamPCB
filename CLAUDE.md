# HaslamPCB

Tools for LLM-driven KiCad placement and routing. Code is GPL-3.0-or-later; docs
CC-BY-4.0 (see `LICENSING.md`). New source files carry SPDX headers.

## Docs: load little, follow links

- Look up a term with `grep -i '<term>' docs/SUBJECTS.md` (idea ids: `grep -w XD113 docs/IDS.md`)
  and open only the linked section; otherwise start at `docs/INDEX.md`. Don't bulk-read
  `research_notes/`; it is raw evidence cited by the topic docs.
- When writing docs, follow `docs/CONVENTIONS.md`: reference-text style (formulas, tables,
  numbered facts), each fact once with links elsewhere, `Scope:`/`Keys:` header lines.
  Re-run `python3 tools/docs/subjects.py` after editing docs.
- Before using any `.kicad_dru` you wrote or edited, run `haslam dru-check FILE` (from `haslam/`:
  `PYTHONPATH=src python -m haslam.board.dru_check FILE`). KiCad silently drops the whole file on
  one syntax error, so DRC would pass without your rules; exit 1 means fix it first.
  After a KiCad version bump, run `pytest haslam/tests/test_board_dru_check.py` (drift tests) and
  follow `docs/topics/kicad/drc-rule-language-reference.md#keeping-the-checker-in-sync-with-kicad`.

## Local board corpus

~14k accepted boards live in one local folder (default `~/haslam-boards`; the host's
`CLAUDE.local.md` says where), one `boards/<id>/board.kicad_pcb` each plus `manifest.jsonl`.
It is never committed. Build it with `bench/scripts/build-corpus.sh` after `setup.sh`.
Treat it as read-only and copy boards out before editing. Read
`docs/topics/data/local-board-corpus.md` before using it.

## Benchmark harness (`bench/`, package `haslambench`)

Setup on an Ubuntu host (no sudo needed: installs Apptainer rootless and runs KiCad from its official image): `bench/scripts/setup.sh`, then `source bench/.venv/bin/activate`
and `haslambench doctor`. Tests: `pytest bench/tests` (KiCad tests skip without KiCad).

Closed loop:

```bash
M=bench/manifests/candidates.jsonl
haslambench fetch -m $M -j 16
haslambench prepare -m $M -j 16                       # HASLAM_DRC_TIMEOUT=3600 for big boards
haslambench tasks --write-suite haslam-work/qualified.txt
haslambench run --adapter <name> [--command "..."] --kinds route -k 3 --timeout 900 -j 16 \
  --only @haslam-work/qualified.txt --name <run>
haslambench report haslam-work/results/<run> haslam-work/results/<baseline-run>
```

- Fast iteration: `--splits A` (≤ 31 pads) or `--only id1,id2`; full runs take hours.
- Run long jobs through `haslamq` (below) and wait with one background `haslamq wait`; don't hold a foreground
  command or poll a log.
- Host-specific paths (KiCad, Freerouting, data dirs) go in a git-ignored `CLAUDE.local.md`.
- Re-using `--name` resumes a run; use a new name after changing a method.
- Per-attempt artifacts: `haslam-work/results/<run>/<adapter>/<kind>/<id>/attempt-N/`
  (`attempt.json`, `adapter.log`, `score/drc.json`).
- Long or heavy jobs on the shared host go through the `haslamq` queue (`tools/haslamq/README.md`), never run directly.
  Results of every method on every board, with the code that made them: `tools/haslamres/README.md` (`~/haslam-baselines/boards/<id>/runs/`).
- New methods plug in with `--command` (reads `{input}`, writes `{output}`) or a class in
  `bench/src/haslambench/adapters.py`.

## Many sessions share this host and its queue

Several Claude sessions run experiments here at once; tokens are the scarce resource. Details: the `haslamq` skill.
- Your jobs record your session (`$CLAUDE_CODE_SESSION_ID`). Look after only your own jobs and experiments: never
  wait on, retry, cancel, analyse or report on another session's (`haslamq sessions` shows whose is whose).
- After submitting, stop: the haslamq dispatcher messages you at a campaign's first failure, its 25% mark and its end.
  (Without a dispatcher, `haslamq wait` in the background does the same; see the skill.) No
  polling: no `send_later`/`ScheduleWakeup`/`Monitor`/sleep loops, no repeated `haslamq status`, `haslamqtop` or log tails.
- Tell another session about a problem in its work with `haslamq note <session-or-owner> "..."`; it reads it when its
  wait returns. Message a session directly only to answer its question or when you are blocked on it: one message
  with everything, no status updates, FYIs or thanks.

## Experiment tiers

Every experiment runs on the sprint suites first; details: `docs/topics/verification/experiment-tiers.md`.
- Suites in `bench/suites/`: `sprint-frontier.txt` + `sprint-quality.txt` (every experiment), `ladder.txt` (only what
  passed sprint, `--tier ladder`), `canary.txt` (big boards, weekly, `--tier canary`).
- `haslamres exp create|submit` print the estimated CPU-hours and refuse a sprint over 40 CPU-h or with a board whose
  history is over 0.5 CPU-h per method-run. The refusal's second line says what to do.
- Procedure: `bench/suites/README.md`. Build on the weekly tag (`baseline/2026-w47`) plus one change; `haslamres sprint`
  runs only the new arm against the stored control (`control-w47`). Don't migrate queued work when main moves.
- "Undecided" is a valid verdict. Queue sprint campaigns at priority 5 (`haslamq prio 5 --owner exp-NAME`).

## Rules for closed-loop work

- Never change scoring to improve a score. Scoring and integrity checks
  (`score.py`, `tools.summarize_drc`, `prepare.py`) define the benchmark. If one is
  wrong, fix it in a separate commit that says why, and re-run the baselines.
- Compare against a baseline run made with the same KiCad version, manifest and suite.
  Report both `cp1` and `cpk`, plus completion and error counts. Read the per-type
  errors in `drc.json` before concluding anything.
- A router's own log is not a score; only `kicad-cli` on the re-opened board counts.
- `haslam-work/` is git-ignored. Commit code, manifests, suites and summarized results,
  never boards (third-party licences).
