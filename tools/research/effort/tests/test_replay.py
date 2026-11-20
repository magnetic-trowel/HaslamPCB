# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python tests of the restart-policy replay on a synthetic attempt log of three boards (4 lanes)."""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import replay as R  # noqa: E402


def rank(opens):
    return [0, 0, 0, 0, 0] if opens == 0 else [0, 1, opens, 0, 0]


def att(k, opens, cpu, base=None):
    return dict(k=k, seed=k, rank=rank(opens), cpu_s=cpu, resumed_from=base)


# board 1: clean in wave 0 (attempt 1); one wave only
LOG1 = [att(0, 4, 10), att(1, 0, 10), att(2, 2, 10), att(3, 3, 10)]
# board 2: wave 1 resumes the wave-0 incumbent (k0); final resumes k6
LOG2 = [att(0, 10, 10), att(1, 12, 10), att(2, 11, 10), att(3, 15, 10),
        att(4, 9, 20), att(5, 14, 20), att(6, 7, 30, 0), att(7, 8, 30, 0),
        dict(att('final', 5, 5, 6))]
# board 3: k1 and k3 tie; wave 1 resumes k1 (exact) and k3 (approx); final resumes k5
LOG3 = [att(0, 20, 10), att(1, 10, 10), att(2, 30, 10), att(3, 10, 10),
        att(4, 9, 20), att(5, 6, 30, 1), att(6, 7, 30, 3), att(7, 12, 20),
        dict(att('final', 4, 5, 5))]


def boards():
    return [R.make_board(f'b{i}', log, pads=50 * i) for i, log in enumerate((LOG1, LOG2, LOG3), 1)]


def run(B, pol):
    return R.simulate(B, pol)


def test_make_board_waves():
    B1, B2, B3 = boards()
    assert len(B1['waves']) == 1 and len(B2['waves']) == 2
    assert [a['k'] for a in B2['waves'][1]] == [4, 5, 6, 7]
    assert B2['final']['resumed_from'] == 6 and B1['final'] is None


def test_fixed_equals_log():
    B1, B2, B3 = boards()
    for B, log in ((B2, LOG2), (B3, LOG3)):
        cpu, best, fl = run(B, R.fixed)
        assert cpu == sum(a['cpu_s'] for a in log)
        assert best == min(tuple(a['rank']) for a in log)
        assert fl['censored'] == 0 and fl['final_dropped'] == 0
    cpu, best, fl = run(B1, R.fixed)
    assert (cpu, best[1]) == (40, 0)
    assert run(B2, R.fixed)[1][2] == 5 and run(B3, R.fixed)[1][2] == 4


def test_approx_when_ranks_tie():
    _, _, B3 = boards()
    assert run(B3, R.fixed)[2]['approx'] == 1          # k6 resumed k3, incumbent k1 has the same rank


def test_wave_cap():
    _, B2, B3 = boards()
    cpu, best, fl = run(B2, R.cap(0))
    assert (cpu, best[2]) == (40, 10)
    assert fl['stopped'] == 1 and fl['final_dropped'] == 1   # final resumed k6, which the cap never ran
    assert run(B2, R.cap(1))[:2] == run(B2, R.fixed)[:2]


def test_probe1_drops_three_attempts():
    B1, B2, _ = boards()
    cpu, best, _ = run(B1, R.probe(1))
    assert (cpu, best[2]) == (10, 4)                   # k1..k3 and their 30 s are gone; the clean k1 too
    cpu, best, fl = run(B2, R.probe(1))
    assert cpu == sum(a['cpu_s'] for a in LOG2) - 30
    assert best[2] == 5 and fl['censored'] == 0


def test_censored_when_resume_base_dropped():
    _, _, B3 = boards()
    cpu, best, fl = run(B3, R.probe(1))
    assert fl['censored'] == 2                         # k5 (base k1) and k6 (base k3) not run by the probe
    assert (cpu, best[2]) == (10 + 20 + 20, 9)
    assert fl['final_dropped'] == 1                    # kept board k4 is not the one the final resumed


def test_final_only_when_kept_board_matches():
    _, _, B3 = boards()
    cpu, best, fl = run(B3, R.probe(2))                # probe keeps k1, so k5 is exact, k6 approx
    assert fl['approx'] == 1 and fl['censored'] == 0 and fl['final_dropped'] == 0
    assert (cpu, best[2]) == (20 + 100 + 5, 4)
    later = R.probe(2, dict(fresh=2, resume=0))       # no resumes: kept board k4, final not applied
    cpu, best, fl = run(B3, later)
    assert (cpu, best[2], fl['final_dropped']) == (60, 9, 1)


def test_bootstrap_seeded():
    BS = boards()
    base = R.evaluate(BS, lambda B: R.fixed)[0]
    rows = R.evaluate(BS, lambda B: R.probe(1))[0]
    a = R.boot(base, rows, n=300, seed=7)
    assert a == R.boot(base, rows, n=300, seed=7)
    pt, ci = R.eq_boot(BS, lambda B: R.probe(1), n=100, seed=2)
    assert (pt, ci) == R.eq_boot(BS, lambda B: R.probe(1), n=100, seed=2)


def test_frontier_interpolates():
    front = [(1.0, 10, 100, 5.0), (3.0, 20, 50, 3.0)]
    assert R.frontier_at(front, 2.0) == [15.0, 75.0, 4.0]
    assert R.frontier_at(front, 0.5) == [10, 100, 5.0]
    assert R.frontier_at(front, 9.0) == [20, 50, 3.0]


def test_load_experiment(tmp_path):
    exp = tmp_path / 'experiments' / 'x'
    exp.mkdir(parents=True)
    (exp / 'boards.txt').write_text('b2\nb1\n')
    with open(exp / 'results.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['board', 'method', 'run', 'attempt', 'pads'])
        w.writerow(['b1', 'm restarts', 'r1', '0', '40'])
        w.writerow(['b2', 'm restarts', 'r2', '0', '400'])
        w.writerow(['b2', 'm restarts', 'r2b', '1', '400'])
        w.writerow(['b1', 'human', 'h', '0', '40'])
    for b, run_, log in (('b1', 'r1', LOG1), ('b2', 'r2', LOG2)):
        d = tmp_path / 'boards' / b / 'runs' / run_
        d.mkdir(parents=True)
        (d / 'restarts.json').write_text(json.dumps(dict(attempt_log=log)))
    data = R.load_experiment(str(tmp_path), 'x', ['restarts'])
    assert list(data) == ['m restarts']
    assert [B['board'] for B in data['m restarts']] == ['b2', 'b1']   # boards.txt order
    assert data['m restarts'][0]['pads'] == 400
    assert R.load_experiment(str(tmp_path), 'x', ['nothing']) == {}
