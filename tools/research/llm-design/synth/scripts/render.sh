#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Review renders of a board with KiCad's 3D viewer, headless (docs/topics/workflow/brief-to-board.md, S10):
#   render.sh BOARD.kicad_pcb OUTDIR [basic|high]
# writes OUTDIR/<stem>-top.png, -bottom.png, -iso.png (1600 x 1200). basic: ~20 s each; high (ray-traced): ~160 s.
# Parts show as 3D bodies only when KiCad's 3D models are installed (apt: kicad-packages3d, or
# bench/scripts/setup.sh --3d); without them the renders show bare pads, silkscreen and copper, which is
# enough to review silkscreen and placement. kicad-cli: HASLAM_KICAD_CLI, else $HASLAM_KICAD_WRAP kicad-cli.
set -euo pipefail
[ $# -ge 2 ] || { sed -n '4,9p' "$0" >&2; exit 2; }
B=$(realpath "$1") OUTD=$(realpath -m "$2") Q=${3:-basic}
STEM=$(basename "$B" .kicad_pcb)
read -r -a CLI <<< "${HASLAM_KICAD_CLI:-${HASLAM_KICAD_WRAP:-} kicad-cli}"
mkdir -p "$OUTD"
models=${KICAD10_3DMODEL_DIR:-/usr/share/kicad/3dmodels}
[ -d "$models" ] || echo "render: no 3D models at $models (install kicad-packages3d): parts render as bare pads" >&2
fail=0
for view in "top:--side top" "bottom:--side bottom" "iso:--side top --rotate -45,0,45 --zoom 0.9 --perspective"; do
  name=${view%%:*}
  read -r -a opts <<< "${view#*:}"
  if "${CLI[@]}" pcb render --quality "$Q" --width 1600 --height 1200 --background opaque "${opts[@]}" \
       -o "$OUTD/$STEM-$name.png" "$B" > "$OUTD/render-$name.log" 2>&1 && [ -s "$OUTD/$STEM-$name.png" ]; then
    echo "render: $OUTD/$STEM-$name.png"
    rm -f "$OUTD/render-$name.log"
  else
    echo "render FAILED: $name view (see $OUTD/render-$name.log)" >&2
    fail=1
  fi
done
exit $fail
