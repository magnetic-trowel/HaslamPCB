# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""One wall deadline through every layer of a run (kaeq job, kaeres, kaebench, the method, kae and
its tools): KAE_DEADLINE, epoch seconds. Each layer's timeout is no later than the deadline it was
given, and what it starts gets that timeout less a margin to finish in, so an inner layer can never
outlive an outer one and be killed with nothing written."""
import os
import time


def deadline_env(env=None, timeout=None):
    """(env, timeout): `timeout` (wall s, None = none) no later than this process's KAE_DEADLINE, and
    `env` (default os.environ) with the child's KAE_DEADLINE, that timeout from now less 10 % (at most
    30 s)."""
    env = dict(os.environ if env is None else env)
    d = os.environ.get("KAE_DEADLINE")
    if d:
        left = max(1.0, float(d) - time.time())
        timeout = left if timeout is None else min(float(timeout), left)
    if timeout is not None:
        env["KAE_DEADLINE"] = f"{time.time() + timeout - min(30.0, 0.1 * timeout):.0f}"
    return env, timeout
