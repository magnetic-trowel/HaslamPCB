# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Shared environment for the xf experiments. Source it from the worktree root:
#   source tools/research/xf_common/env.sh
# Override XF_WORK (the haslambench work dir; default <worktree>/haslam-work2, round 2), XF_PHYS
# (the physics-engine worktree) and XF_BIND before sourcing if needed. Round 1 lives in
# haslam-work/ (XF_WORK=$XF_ROOT/haslam-work to read it).
XF_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export XF_ROOT
XF_WORK="$(realpath -m "${XF_WORK:-$XF_ROOT/haslam-work2}")"
export XF_WORK
. "$XF_ROOT/bench/.venv/bin/activate"            # also sources the haslambench env.sh (HASLAM_KICAD_WRAP)
export APPTAINER_BIND="${XF_BIND:-$(dirname "$XF_ROOT")}"   # the KiCad container must see the worktree
export HASLAM_SRC="${XF_PHYS:-$(dirname "$XF_ROOT")/haslam-phys}/haslam/src"
export HASLAM_KICAD_PYTHON="$XF_ROOT/tools/research/xf_common/kicad-python"
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
# Kernels compile once into this cache (warm_numba.sh), not inside every attempt's budget.
# Sandboxed attempts copy it into their own work dir (xf_run.sh): the sandbox makes it read-only.
export NUMBA_CACHE_DIR="$XF_WORK/numba-cache"
mkdir -p "$NUMBA_CACHE_DIR"
