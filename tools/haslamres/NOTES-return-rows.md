# Return rows: remaining steps

Built: `tools/haslamres/return_board.py` (rows, keep-out rule areas, per-net worst uncovered length, fast-net rows,
adjacent-layer coverage on 4+ layers, `paired()` for the quality report), 7 synthetic tests in
`tools/haslamres/tests/test_return_board.py`, README section. Checked against the stage 0 prototype on 10 stored
board-arms (5 boards, human and bridge): every row identical.

Not done:

1. Done (branch ground-side-default): `haslamres quality NAME --control C --return-rows` adds the rows; measured once per
   stored board and process (`measure_cached`). Validation against KiCad: `tools/haslamres/experiments/ground-side-ladder/VALIDATION.md`.
2. Speed: a board took about 3 s single core on the stage 0 boards, so a 65-board, two-arm report is several minutes; it measures on every call.
   If the report runs often, store the rows as `evals/return-<id>.json` like `mfg_board.py` does.
3. Test environment: the bench venv has no shapely, so these tests (like `test_mfg_board.py`) skip there; they were
   run with a venv that has shapely 2.2.
