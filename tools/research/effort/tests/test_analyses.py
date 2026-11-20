# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Light tests of the certified-opens classes, the recurrence run states and the conflict-set file names."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import certified  # noqa: E402
import conflict_sets  # noqa: E402  (imports kae only inside `diagnose`)
import recurrence  # noqa: E402


def ent(cause, net='N'):
    return dict(net=net, cause=cause)


def test_classify():
    assert certified.classify(None) == ('no diagnosis', 0, 0)
    assert certified.classify(dict(blocked=[ent('rule'), ent('geometry')], undiagnosed=0))[0] == 'all hard'
    assert certified.classify(dict(congestion=[ent('congestion')]))[0] == 'all congestion'
    assert certified.classify(dict(blocked=[ent('rule')], congestion=[ent('congestion')])) == ('mixed', 1, 2)
    assert certified.classify(dict(blocked=[ent('rule')], undiagnosed=2))[0] == 'capped'


def run(**k):
    r = dict(board='b', run='r', status='ok', unconnected=1, entries=None, undiagnosed=None, drc=None)
    r.update(k)
    return r


def test_recurrence_states():
    item = ('N1', 'pad', 'U1', '1', 'pad', 'R2', '2')
    R = [run(unconnected=0),                                   # clean by the judge
         run(drc=[item]),                                      # open, from the DRC list
         run(drc=[item] * recurrence.CAP),                     # capped DRC list
         run(entries=[('N2', ('U3.4',), 'congestion', (), (), None)], undiagnosed=0),   # open, from the diagnosis
         run(entries=[('N2', ('U3.4',), 'congestion', (), (), None)], undiagnosed=1),   # capped diagnosis
         run()]                                                # nothing known
    recurrence.prepare(R, out=lambda *a, **k: None)
    assert [r['st'] for r in R] == ['clean', 'open', 'capped', 'open', 'capped', None]
    assert R[1]['nets'] == {'N1'} and R[1]['parts'] == {'U1', 'R2'} and R[1]['pairs'] == {frozenset(('U1', 'R2'))}
    assert R[3]['nets'] == {'N2'} and R[3]['parts'] == {'U3'} and R[3]['cause']['N2'] == {'congestion'}


def test_jaccard():
    assert recurrence.jac(frozenset('ab'), frozenset('bc')) == 1 / 3
    assert recurrence.jac(frozenset(), frozenset()) is None


def test_slug():
    assert conflict_sets.slug('s2 bridge 44041bc (restarts)') == 's2-bridge-44041bc-restarts'
