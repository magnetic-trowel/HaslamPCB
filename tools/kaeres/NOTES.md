<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# ledger.py: what is missing

- `fill-drc` is not built. Staged and joint runs store no DRC item list, so their open connections are known
  only from `blocked` records. The command should print kaeq command lines that re-run the DRC of a run's
  `output.kicad_pcb.gz` through the harness scorer into a cache dir under `--out`, never into the store.
  Open point: the store keeps the output board but not the task's project file (`.kicad_pro`), so the job
  must rebuild the prepared task (or take the project from the task's prepared input) before the DRC, or the
  rules differ from the scored ones. `build` would then read `<out>/drc-cache/<run>.drc.json.gz` when present.
- Persistence is between two methods only; losing attempts' open lists are not stored, so persistence across
  restarts of one run cannot be computed.
- Class shares have no interval (k=1 runs).
