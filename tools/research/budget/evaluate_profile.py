#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`python -m kae.excite.evaluate` with the work clock's exit report, for calibrating the field-solver rates.

The evaluator's CLI sets no budget and prints no `[kae.budget]` line. This runs it unchanged (same arguments,
same output) after `kae.budget.start_run`, so with KAE_BUDGET_PROFILE=1 the report at exit carries `units` and
`wall_by_kind` for calibrate.py; in work mode (KAE_BUDGET=work) it shows what the evaluation charged.

    KAE_BUDGET_PROFILE=1 evaluate_profile.py BOARD --intent I --drc D --scope losses -o EV.json
"""
from __future__ import annotations

import os
import sys

from kae import budget


def main(argv=None):
    budget.start_run(float(os.environ.get("KAE_EVAL_BUDGET_S", "36000")))    # a ceiling far above any evaluation
    from kae.excite.evaluate import main as evaluate_main
    evaluate_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
