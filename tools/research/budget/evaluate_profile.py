#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`python -m haslam.excite.evaluate` with the work clock's exit report, for calibrating the field-solver rates.

The evaluator's CLI sets no budget and prints no `[haslam.budget]` line. This runs it unchanged (same arguments,
same output) after `haslam.budget.start_run`, so with HASLAM_BUDGET_PROFILE=1 the report at exit carries `units` and
`wall_by_kind` for calibrate.py; in work mode (HASLAM_BUDGET=work) it shows what the evaluation charged.

    HASLAM_BUDGET_PROFILE=1 evaluate_profile.py BOARD --intent I --drc D --scope losses -o EV.json
"""
from __future__ import annotations

import os
import sys

from haslam import budget


def main(argv=None):
    budget.start_run(float(os.environ.get("HASLAM_EVAL_BUDGET_S", "36000")))    # a ceiling far above any evaluation
    from haslam.excite.evaluate import main as evaluate_main
    evaluate_main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
