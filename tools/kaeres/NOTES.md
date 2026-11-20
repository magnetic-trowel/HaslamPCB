<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# ledger.py: what is missing

- `fill-drc` is built but not yet validated: the re-run uses the corpus board's project files, not the
  prepared task's, so its unconnected list may differ from what the scorer would give. The check is
  `--include-stored` on route runs whose stored list is known; the first smoke (3 small boards) was queued,
  its result is not in this commit.
- Persistence is between two methods only; losing attempts' open lists are not stored, so persistence across
  restarts of one run cannot be computed.
- Class shares have no interval (k=1 runs).
