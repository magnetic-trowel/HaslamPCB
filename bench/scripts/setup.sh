#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Set up a haslambench host (Ubuntu 22.04/24.04 x86_64): KiCad 10, Freerouting 2.5.0 (explicit use only), venv.
# Works without sudo: KiCad then runs from the official kicad/kicad image via
# Apptainer/Singularity (installed rootless into HASLAM_HOME if absent; needs unprivileged
# user namespaces), and the venv comes from uv if python3-venv is missing.
#
#   bench/scripts/setup.sh [--all] [--kicad auto|apt|container|none] [--no-freerouting] [--venv DIR] [--dry-run]
#
# --all: also the whole design pipeline (README.md Part 1): haslam/.venv with haslam[dev,fast], the haslamsynth venv
# (tools/research/llm-design/synth/.venv, with haslam/src on its path for the rules and intent checks), and the
# Freerouting fork of bench/freerouting.ref built and pinned when nothing is pinned yet.
# --dry-run: print the install commands instead of running them; env.sh is still written (tests use it).
#
# Environment: HASLAM_HOME (default ~/.cache/haslambench) holds Freerouting, the KiCad image
# and env.sh (sourced by the venv's activate script), which exports every variable the pipeline reads:
# HASLAM_HOME, HASLAM_KICAD_WRAP (empty with a native KiCad), KICAD10_SYMBOL_DIR, KICAD10_FOOTPRINT_DIR and, with
# a container KiCad, APPTAINER_BIND. KICAD_IMAGE_TAG (default 10.0.7).
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$BENCH_DIR/.." && pwd)"
HASLAM_HOME="${HASLAM_HOME:-$HOME/.cache/haslambench}"
VENV="$BENCH_DIR/.venv"
KICAD_MODE=auto
DO_FR=1
DO_ALL=0
DRY=0
FR_VERSION="2.5.0"
FR_ZIP_SHA256="e8ffca14914e5307a2fa9aea723fb93d11b99bebda20d126472da5460c03196e"
KICAD_IMAGE_TAG="${KICAD_IMAGE_TAG:-10.0.7}"
APPTAINER_VERSION="1.5.4"
APPTAINER_INSTALLER_SHA256="a097956eafa6ab3dd843ee429d0b774ed029753bfadf013b8046556228fac6f2"
# the control's Freerouting fork ref: first non-comment line of bench/freerouting.ref
FR_REF="$(sed 's/#.*//' "$BENCH_DIR/freerouting.ref" | awk 'NF {print $1; exit}')"

while [ $# -gt 0 ]; do
  case "$1" in
    --kicad) KICAD_MODE="$2"; shift ;;
    --no-kicad) KICAD_MODE=none ;;
    --no-freerouting) DO_FR=0 ;;
    --venv) VENV="$2"; shift ;;
    --all) DO_ALL=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

# run: execute, or with --dry-run print the command
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }

mkdir -p "$HASLAM_HOME"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; HAVE_SUDO=1
elif sudo -n true 2>/dev/null; then SUDO="sudo"; HAVE_SUDO=1
else SUDO=""; HAVE_SUDO=0
fi
ENV_FILE="$HASLAM_HOME/env.sh"
ENV_LINES=("export HASLAM_HOME=\"$HASLAM_HOME\"")

kicad_major() { kicad-cli version 2>/dev/null | cut -d. -f1; }
container_tool() {
  command -v apptainer || command -v singularity ||
    { [ -x "$HASLAM_HOME/apptainer/bin/apptainer" ] && echo "$HASLAM_HOME/apptainer/bin/apptainer"; } || true
}
userns_ok() { unshare -Ur true 2>/dev/null; }

install_apptainer_unpriv() {
  # Apptainer's own no-root installer unpacks EL8 RPMs; rpm2cpio and cpio fall back to
  # Python shims when the host lacks them.
  local dest="$HASLAM_HOME/apptainer" shims="$HASLAM_HOME/shims" inst="$HASLAM_HOME/install-unprivileged.sh"
  echo "Installing Apptainer $APPTAINER_VERSION without root into $dest"
  rm -rf "$dest" "$shims"
  mkdir -p "$shims"
  command -v rpm2cpio >/dev/null || ln -s "$BENCH_DIR/scripts/rpm2cpio.py" "$shims/rpm2cpio"
  command -v cpio >/dev/null || ln -s "$BENCH_DIR/scripts/cpio_extract.py" "$shims/cpio"
  curl -fsSL -o "$inst" \
    "https://raw.githubusercontent.com/apptainer/apptainer/v$APPTAINER_VERSION/tools/install-unprivileged.sh"
  echo "$APPTAINER_INSTALLER_SHA256  $inst" | sha256sum -c - >/dev/null
  PATH="$shims:$PATH" bash "$inst" -d el8 -v "$APPTAINER_VERSION" "$dest"
  rm -rf "$inst" "$shims"
}

install_kicad_apt() {
  . /etc/os-release
  echo "Installing KiCad 10 from ppa:kicad/kicad-10.0-releases (no recommends)"
  FP=$(curl -fsSL "https://api.launchpad.net/1.0/~kicad/+archive/ubuntu/kicad-10.0-releases" |
       python3 -c "import json,sys; print(json.load(sys.stdin)['signing_key_fingerprint'])")
  curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$FP" |
    $SUDO gpg --dearmor --yes -o /usr/share/keyrings/kicad-10.gpg
  echo "deb [signed-by=/usr/share/keyrings/kicad-10.gpg] https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu ${VERSION_CODENAME} main" |
    $SUDO tee /etc/apt/sources.list.d/kicad-10.list >/dev/null
  $SUDO apt-get update -qq
  # kicad-symbols/kicad-footprints are only recommends: haslamsynth needs both (obd-solar FRICTION.md #6)
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends kicad kicad-symbols kicad-footprints
}

install_kicad_container() {
  local tool dir
  tool="$(container_tool)"
  dir="$HASLAM_HOME/kicad-$KICAD_IMAGE_TAG"
  if [ ! -x "$dir/usr/bin/kicad-cli" ]; then
    rm -rf "$dir"   # a partial unpack from an interrupted run
    echo "Unpacking docker://kicad/kicad:$KICAD_IMAGE_TAG into $dir with $(basename "$tool") (~2.5 GB, no root needed)"
    # an unpacked directory needs neither root nor /dev/fuse at run time
    APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-$HASLAM_HOME/apptainer-cache}" \
      "$tool" build --sandbox "$dir" "docker://kicad/kicad:$KICAD_IMAGE_TAG"
    [ -n "${APPTAINER_CACHEDIR:-}" ] || rm -rf "$HASLAM_HOME/apptainer-cache"   # keep a user-set cache
  fi
  # kicad-exec sizes KiCad's thread pool to the job's CPUs (see the script); cpus/N is what it shows KiCad
  install -m 755 "$BENCH_DIR/scripts/kicad-exec" "$HASLAM_HOME/kicad-exec"
  mkdir -p "$HASLAM_HOME/cpus"
  local n
  for n in $(seq 1 "$(getconf _NPROCESSORS_ONLN)"); do printf '0-%d\n' $((n - 1)) > "$HASLAM_HOME/cpus/$n"; done
  ENV_LINES+=("export HASLAM_KICAD_WRAP=\"$HASLAM_HOME/kicad-exec $tool $dir\"")
  # haslamsynth reads the image's libraries; the container sees $HOME, /tmp and the cwd, so bind the checkout too
  [ -d "$dir/usr/share/kicad/symbols" ] && ENV_LINES+=("export KICAD10_SYMBOL_DIR=\"$dir/usr/share/kicad/symbols\"" \
    "export KICAD10_FOOTPRINT_DIR=\"$dir/usr/share/kicad/footprints\"")
  ENV_LINES+=("export APPTAINER_BIND=\"\${APPTAINER_BIND:-$REPO}\"")
}

has_env() { printf '%s\n' "${ENV_LINES[@]}" | grep -q "^export $1="; }

if [ "$DRY" = 1 ] && [ "$KICAD_MODE" != none ]; then
  echo "+ install KiCad 10 (--kicad $KICAD_MODE)"
  KICAD_MODE=none
fi
case "$KICAD_MODE" in
  none)  # keep the KiCad variables an earlier run configured
    if [ -f "$ENV_FILE" ]; then
      while IFS= read -r line; do ENV_LINES+=("$line"); done < \
        <(grep -E '^export (HASLAM_KICAD_|KICAD10_|APPTAINER_BIND=)' "$ENV_FILE" || true)
    fi ;;
  apt) install_kicad_apt ;;
  container)
    if [ -z "$(container_tool)" ]; then
      userns_ok || { echo "no apptainer/singularity, and unprivileged user namespaces are disabled" >&2; exit 1; }
      install_apptainer_unpriv
    fi
    install_kicad_container ;;
  auto)
    if [ "$(kicad_major || echo 0)" -ge 10 ] 2>/dev/null; then
      echo "KiCad $(kicad-cli version) already installed"
    elif [ "$HAVE_SUDO" = 1 ] && grep -q '^ID=ubuntu' /etc/os-release 2>/dev/null; then
      install_kicad_apt
    elif [ -n "$(container_tool)" ]; then
      install_kicad_container
    elif [ "$(uname -m)" = x86_64 ] && userns_ok; then
      install_apptainer_unpriv
      install_kicad_container
    else
      cat >&2 <<'EOF'
KiCad 10 is not installed, there is no sudo or Apptainer/Singularity, and Apptainer cannot
be installed rootless here (needs x86_64 and unprivileged user namespaces; `unshare -Ur true`
fails, e.g. on Ubuntu 24.04 with kernel.apparmor_restrict_unprivileged_userns=1). Options:
  - ask an admin to run: bench/scripts/setup.sh --kicad apt   (KiCad PPA, no recommends)
  - ask an admin to install apptainer, then re-run this script (KiCad runs from the official image)
  - flatpak --user install flathub org.kicad.KiCad, then set
      HASLAM_KICAD_CLI="flatpak run --command=kicad-cli org.kicad.KiCad"
      HASLAM_KICAD_PYTHON="flatpak run --command=python3 org.kicad.KiCad"
Re-run with --kicad none to install the rest now.
EOF
      exit 1
    fi ;;
  *) echo "unknown --kicad mode $KICAD_MODE" >&2; exit 2 ;;
esac

if [ "$DO_FR" = 1 ]; then
  DEST="$HASLAM_HOME/freerouting-$FR_VERSION-linux-x64"
  if [ -x "$DEST/bin/freerouting" ]; then
    echo "Freerouting $FR_VERSION already at $DEST"
  elif [ "$DRY" = 1 ]; then
    echo "+ download Freerouting $FR_VERSION into $DEST"
  else
    ZIP="$HASLAM_HOME/freerouting-$FR_VERSION-linux-x64.zip"
    curl -fsSL -o "$ZIP" \
      "https://github.com/freerouting/freerouting/releases/download/v$FR_VERSION/freerouting-$FR_VERSION-linux-x64.zip"
    echo "$FR_ZIP_SHA256  $ZIP" | sha256sum -c -
    python3 -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$HASLAM_HOME"
    chmod +x "$DEST/bin/freerouting" "$DEST/lib/runtime/bin/"* "$DEST/lib/runtime/lib/jspawnhelper" 2>/dev/null || true
    rm -f "$ZIP"
  fi
  # upstream 2.5.0 is for explicit use only (HASLAM_FREEROUTING). haslambench and the bridge run the build
  # pinned in $HASLAM_HOME/haslam-freerouting.pin, the magnetic-trowel fork (the control):
  if [ ! -s "$HASLAM_HOME/haslam-freerouting.pin" ]; then
    if [ "$DO_ALL" = 1 ]; then
      run env HASLAM_HOME="$HASLAM_HOME" "$REPO/tools/research/routing/install_freerouting_fork.sh" "$FR_REF" --pin
    else
      echo "No Freerouting pinned yet: run tools/research/routing/install_freerouting_fork.sh $FR_REF --pin" \
           "(the control, bench/freerouting.ref), or re-run with --all"
    fi
  elif ! grep -q "haslam-freerouting-fork-$FR_REF/" "$HASLAM_HOME/haslam-freerouting.pin"; then
    echo "Freerouting pin $(cat "$HASLAM_HOME/haslam-freerouting.pin") is not the control $FR_REF (bench/freerouting.ref);" \
         "kept. Re-pin with tools/research/routing/install_freerouting_fork.sh $FR_REF --pin"
  fi
fi

# make_venv DIR PYTHON_MIN PIP_ARGS...: a venv from python3 -m venv, else python3-venv via apt, else uv; one
# connection at a time to the package index (CLAUDE.md: be gentle with external hosts)
make_venv() {
  local dir="$1" pymin="$2"; shift 2
  if python3 -c "import ensurepip, venv, sys; sys.exit(sys.version_info < tuple(map(int, '$pymin'.split('.'))))" 2>/dev/null; then
    run python3 -m venv "$dir"
    run "$dir/bin/pip" install -q --upgrade pip
    run "$dir/bin/pip" install -q "$@"
  elif [ "$HAVE_SUDO" = 1 ] && python3 -c "import sys; sys.exit(sys.version_info < tuple(map(int, '$pymin'.split('.'))))"; then
    run $SUDO apt-get install -y -qq python3-venv
    run python3 -m venv "$dir"
    run "$dir/bin/pip" install -q --upgrade pip
    run "$dir/bin/pip" install -q "$@"
  else
    echo "python3-venv (Python >= $pymin) is missing and cannot be installed: using uv for $dir"
    command -v uv >/dev/null || [ -x "$HOME/.local/bin/uv" ] || run sh -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
    local uv; uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
    run "$uv" venv -q --python 3.12 "$dir"
    run env UV_CONCURRENT_DOWNLOADS=1 "$uv" pip install -q --python "$dir/bin/python" "$@"
  fi
}

make_venv "$VENV" 3.10 -e "$BENCH_DIR[test]"
SYNTH="$REPO/tools/research/llm-design/synth"
if [ "$DO_ALL" = 1 ]; then
  # pipeline.py runs haslam/.venv/bin/python and synth/.venv/bin/haslamsynth by these paths
  make_venv "$REPO/haslam/.venv" 3.11 -e "$REPO/haslam[dev,fast]"
  make_venv "$SYNTH/.venv" 3.10 -e "$SYNTH[test]"
  # haslamsynth's rules check (haslam.board.dru_check) and intent check (haslam.intent) are pure Python: put
  # haslam/src on the synth venv's path instead of PYTHONPATH in every shell (obd-solar FRICTION.md #5)
  if [ "$DRY" = 1 ]; then
    echo "+ write $REPO/haslam/src into $SYNTH/.venv site-packages/haslam-src.pth"
  else
    site="$("$SYNTH/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    echo "$REPO/haslam/src" > "$site/haslam-src.pth"
  fi
fi

# every variable the pipeline reads, on every KiCad path (obd-solar FRICTION.md #7): scripts run
# `$HASLAM_KICAD_WRAP kicad-cli ...` under `set -u`, so a native KiCad still needs the (empty) variable
has_env HASLAM_KICAD_WRAP || ENV_LINES+=('export HASLAM_KICAD_WRAP=""')
if ! has_env KICAD10_SYMBOL_DIR && [ -d /usr/share/kicad/symbols ]; then
  ENV_LINES+=('export KICAD10_SYMBOL_DIR=/usr/share/kicad/symbols' 'export KICAD10_FOOTPRINT_DIR=/usr/share/kicad/footprints')
fi
has_env KICAD10_SYMBOL_DIR || echo "WARN no KiCad symbol library found: set KICAD10_SYMBOL_DIR and KICAD10_FOOTPRINT_DIR" \
  "in $ENV_FILE (haslamsynth needs Device.kicad_sym and the .pretty folders)"
printf '%s\n' "${ENV_LINES[@]}" > "$ENV_FILE"
echo "wrote $ENV_FILE"
if [ "$DRY" = 1 ]; then
  echo "+ haslambench doctor"
  exit 0
fi
grep -qF "$ENV_FILE" "$VENV/bin/activate" || echo "[ -f \"$ENV_FILE\" ] && . \"$ENV_FILE\"" >> "$VENV/bin/activate"
echo
( . "$ENV_FILE" && "$VENV/bin/haslambench" doctor $([ "$DO_ALL" = 1 ] && echo --pipeline) )
echo
echo "Activate with: source $VENV/bin/activate"
[ "$DO_ALL" = 1 ] && echo "Design pipeline: README.md Part 1 (pipeline.py runs haslam/.venv and the synth venv)"
exit 0
