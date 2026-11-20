<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# llm-design

Designs from plain-language briefs, and the tools that take them to boards.

- The process, step by step, with its gates and known gaps (start here):
  [docs/topics/workflow/brief-to-board.md](../../../docs/topics/workflow/brief-to-board.md).
- `synth/`: haslamsynth, typed circuit IR -> checked KiCad schematic and `<slug>.haslam_intent.json`
  ([synth/README.md](synth/README.md)); `synth/scripts/sch_to_board.py` builds the unplaced board.
- `designs/<slug>/`: one design each ([designs/README.md](designs/README.md)); `solar-small/` also holds
  the layout A/B and scoring scripts (`run_ab.sh`, `eval_ab.sh`).
