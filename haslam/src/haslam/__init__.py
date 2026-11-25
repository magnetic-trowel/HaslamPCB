# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam: physics-first joint placement and routing for KiCad boards.

Subpackages: `haslam.board` (board model, KiCad file reader, transforms, pcbnew bridge),
`haslam.circuit`, `haslam.physics`. `haslam` never imports `haslambench`; methods plug into the
harness through `haslambench run --command`.
"""
__version__ = "0.1.0"
