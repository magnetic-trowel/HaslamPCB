# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Physics-first placement: problem model, clusters, seed, annealer, legalizer, writer.

    from haslam.place.pipeline import place
    result = place(board, seed=0, time_s=120, physics=True)

See haslam/src/haslam/place/pipeline.py for the stages and docs/topics/placement/ for the plan.
"""
