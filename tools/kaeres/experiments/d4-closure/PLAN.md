# d4-closure-replay: conflict-set closure on stored near-miss boards (checkpoint replay, micro tier)

Hypothesis. Opens left on boards 1-5 opens from clean close when the nets their free path crosses are ripped as a
set and re-routed jointly. Measured: 21-25 such boards per method; 69 of 102 of their opens cross 3 nets or fewer.
Boards. The 45 stored near-miss outputs of s2-merit213 (list and input rebuild: designs/4/cs_near.json, cs_run.py).
Arms from the same stored board, 120 s each: control = lastmile close with rip-up; closure = the same with closure=1
(branch d4-closure). Second factor when available: the looped repair and last mile fix, as a 2 x 2.
Endpoint. Boards rank-clean and opens closed by kicad-cli DRC on the written board; no board worse.
Deciding result. 6 or more boards closed beyond the control and none worse: go to sprint (`--base bridge --set closure=1`).
3-5: undecided, go to sprint for power. Kill: fewer than 3, or any board worse.
CPU-h. 3 (6 with the 2 x 2).
