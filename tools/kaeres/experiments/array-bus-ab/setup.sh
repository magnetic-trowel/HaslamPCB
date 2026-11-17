#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# array-bus-ab (PLAN.md): the arms and experiment, from the shared setup.
#   SHA=<pushed commit> tools/kaeres/experiments/array-bus-ab/setup.sh
exec "$(dirname "$0")/../array-matrix-ab/setup.sh" bus
