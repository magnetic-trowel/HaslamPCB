# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the outside commander (an LLM or a rule script) reads to decide kae's next step.

`kae.commander.menu`: the priced loop-back menu. It turns kae's own failure reports (the
"blocked" diagnosis, escape certificates, stop reasons) into a ranked list of earlier
decisions to revisit, each with its evidence, a gain proxy, a price and the exact knob (or
"no knob today"). Pure and deterministic: no router, no pcbnew, no LLM.
"""
