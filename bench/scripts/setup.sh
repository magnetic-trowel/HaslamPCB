#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Set up a haslambench host (Ubuntu 22.04/24.04 x86_64): KiCad 10 with its symbol and footprint libraries,
# Freerouting 2.5.0 (explicit use only) and the pinned Freerouting fork (the control, FR_FORK_REF), venv.
# Works without sudo: KiCad then runs from the official kicad/kicad image via
# Apptainer/Singularity (installed rootless into HASLAM_HOME if absent; needs unprivileged
# user namespaces), and the venv comes from uv if python3-venv is missing.
#
#   bench/scripts/setup.sh [--kicad auto|apt|container|none] [--3d] [--no-freerouting] [--no-fork] [--venv DIR]
#
# --3d installs KiCad's 3D models too (apt: kicad-packages3d, ~5 GB): `kicad-cli pcb render` shows bare pads
# without them. --no-fork skips building the Freerouting fork (needs git, network, ~5 min; Gradle fetches JDK 25).
# Environment: HASLAM_HOME (default ~/.cache/haslambench) holds Freerouting, the KiCad image
# and env.sh (sourced by the venv's activate script; it exports HASLAM_KICAD_WRAP or HASLAM_KICAD_PYTHON and
# KICAD10_SYMBOL_DIR / KICAD10_FOOTPRINT_DIR). KICAD_IMAGE_TAG (default 10.0.7). KICAD_APT_VERSION pins the apt
# package (e.g. 10.0.8; default: whatever the PPA has now, and `haslambench doctor` warns when that is not a
# version the docs and drift tests were checked on, KICAD_TESTED_VERSIONS in bench/src/haslambench/tools.py).
# HASLAM_SETUP_LIB=1 sources the functions only (bench/tests/test_setup_sh.py); HASLAM_SETUP_SYSROOT prefixes the
# system paths native_kicad_env looks at (tests).
set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HASLAM_HOME="${HASLAM_HOME:-$HOME/.cache/haslambench}"
VENV="$BENCH_DIR/.venv"
KICAD_MODE=auto
DO_FR=1
FR_VERSION="2.5.0"
FR_ZIP_SHA256="e8ffca14914e5307a2fa9aea723fb93d11b99bebda20d126472da5460c03196e"
# the magnetic-trowel/freerouting fork build that is the control: the fork the stored baselines ran on (control-w48:
# tools/haslamres/experiments/control-tag.sh FORK=; haslambench.tools.CONTROL_FORK, which doctor checks the pin against)
FR_FORK_REF="37b1a8b"
DO_FORK=1
DO_3D=0
KICAD_APT_VERSION="${KICAD_APT_VERSION:-}"
KICAD_IMAGE_TAG="${KICAD_IMAGE_TAG:-10.0.7}"
APPTAINER_VERSION="1.5.4"
APPTAINER_INSTALLER_SHA256="a097956eafa6ab3dd843ee429d0b774ed029753bfadf013b8046556228fac6f2"

while [ $# -gt 0 ]; do
  case "$1" in
    --kicad) KICAD_MODE="$2"; shift ;;
    --no-kicad) KICAD_MODE=none ;;
    --no-freerouting) DO_FR=0 ;;
    --no-fork) DO_FORK=0 ;;
    --3d) DO_3D=1 ;;
    --venv) VENV="$2"; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$HASLAM_HOME"
if [ "$(id -u)" -eq 0 ]; then SUDO=""; HAVE_SUDO=1
elif sudo -n true 2>/dev/null; then SUDO="sudo"; HAVE_SUDO=1
else SUDO=""; HAVE_SUDO=0
fi
ENV_FILE="$HASLAM_HOME/env.sh"
ENV_LINES=("export HASLAM_HOME=\"$HASLAM_HOME\"")
SYSROOT="${HASLAM_SETUP_SYSROOT:-}"

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

# KiCad's Python (the one that imports pcbnew) and its libraries, for a native install (apt, or one found on
# PATH): the PATH python3 may be another interpreter without pcbnew (a venv, a newer Python), so env.sh names
# KiCad's own as HASLAM_KICAD_PYTHON; scripts run "$HASLAM_KICAD_PYTHON script.py" (else $HASLAM_KICAD_WRAP python3).
native_kicad_env() {
  local py d
  for py in /usr/bin/python3 /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10; do
    py="$SYSROOT$py"
    if [ -x "$py" ] && "$py" -c "import pcbnew" 2>/dev/null; then
      ENV_LINES+=("export HASLAM_KICAD_PYTHON=\"$py\"")
      break
    fi
  done
  for d in SYMBOL:symbols FOOTPRINT:footprints 3DMODEL:3dmodels; do
    if [ -d "$SYSROOT/usr/share/kicad/${d#*:}" ]; then
      ENV_LINES+=("export KICAD10_${d%%:*}_DIR=$SYSROOT/usr/share/kicad/${d#*:}")
    fi
  done
}

# the PPA step needs curl, gpg and python3; a minimal Ubuntu image (docker ubuntu:24.04) has none of them
apt_prereqs() {
  local need=() c
  for c in curl:curl gpg:gnupg python3:python3; do
    command -v "${c%%:*}" >/dev/null || need+=("${c#*:}")
  done
  if [ ! -s /etc/ssl/certs/ca-certificates.crt ]; then need+=(ca-certificates); fi
  if [ ${#need[@]} -gt 0 ]; then
    echo "Installing ${need[*]} (needed to add the KiCad PPA)"
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${need[@]}"
  fi
}

install_kicad_apt() {
  . /etc/os-release
  local pkgs=(kicad kicad-symbols kicad-footprints) v=""
  if [ "$DO_3D" = 1 ]; then pkgs+=(kicad-packages3d); fi
  if [ -n "$KICAD_APT_VERSION" ]; then v="=$KICAD_APT_VERSION*"; fi
  echo "Installing KiCad 10 ${KICAD_APT_VERSION:-(latest)} from ppa:kicad/kicad-10.0-releases: ${pkgs[*]} (no recommends)"
  apt_prereqs
  FP=$(curl -fsSL "https://api.launchpad.net/1.0/~kicad/+archive/ubuntu/kicad-10.0-releases" |
       python3 -c "import json,sys; print(json.load(sys.stdin)['signing_key_fingerprint'])")
  curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$FP" |
    $SUDO gpg --dearmor --yes -o /usr/share/keyrings/kicad-10.gpg
  echo "deb [signed-by=/usr/share/keyrings/kicad-10.gpg] https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu ${VERSION_CODENAME} main" |
    $SUDO tee /etc/apt/sources.list.d/kicad-10.list >/dev/null
  $SUDO apt-get update -qq
  # the libraries are separate packages (recommends): without them haslamsynth finds no symbols or footprints
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${pkgs[@]/%/$v}"
  native_kicad_env
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
  # the image's libraries, for haslamsynth on the host side
  local d
  for d in SYMBOL:symbols FOOTPRINT:footprints 3DMODEL:3dmodels; do
    if [ -d "$dir/usr/share/kicad/${d#*:}" ]; then ENV_LINES+=("export KICAD10_${d%%:*}_DIR=$dir/usr/share/kicad/${d#*:}"); fi
  done
}

# env.sh, and the venv's activate script sourcing it
write_env() {
  printf '%s\n' "${ENV_LINES[@]}" > "$ENV_FILE"
  if [ -f "$VENV/bin/activate" ] && ! grep -qF "$ENV_FILE" "$VENV/bin/activate"; then
    echo "[ -f \"$ENV_FILE\" ] && . \"$ENV_FILE\"" >> "$VENV/bin/activate"
  fi
}

if [ "${HASLAM_SETUP_LIB:-0}" = 1 ]; then return 0; fi

case "$KICAD_MODE" in
  none)  # keep any KiCad wrapper configured by an earlier run
    if [ -f "$ENV_FILE" ]; then
      while IFS= read -r line; do ENV_LINES+=("$line"); done < <(grep -E '^export (HASLAM_KICAD_|KICAD10_)' "$ENV_FILE" || true)
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
      if [ "$HAVE_SUDO" = 1 ] && command -v apt-get >/dev/null; then
        missing=()
        if [ ! -d /usr/share/kicad/symbols ]; then missing+=(kicad-symbols); fi
        if [ ! -d /usr/share/kicad/footprints ]; then missing+=(kicad-footprints); fi
        if [ "$DO_3D" = 1 ] && [ ! -d /usr/share/kicad/3dmodels ]; then missing+=(kicad-packages3d); fi
        if [ ${#missing[@]} -gt 0 ]; then
          echo "Installing KiCad's ${missing[*]} (haslamsynth needs the libraries, renders the 3D models)"
          $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${missing[@]}"
        fi
      fi
      native_kicad_env
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
  FORK_SH="$BENCH_DIR/../tools/research/routing/install_freerouting_fork.sh"
  if [ -s "$HASLAM_HOME/haslam-freerouting.pin" ]; then
    echo "Freerouting pinned: $(cat "$HASLAM_HOME/haslam-freerouting.pin")"
  elif [ "$DO_FORK" = 1 ]; then
    echo "Building the Freerouting fork $FR_FORK_REF (the control) and pinning it"
    HASLAM_HOME="$HASLAM_HOME" bash "$FORK_SH" "$FR_FORK_REF" --pin ||
      echo "WARN: the fork build failed; re-run: $FORK_SH $FR_FORK_REF --pin" >&2
  else
    echo "No Freerouting pinned yet: run $FORK_SH $FR_FORK_REF --pin"
  fi
fi

if python3 -c "import ensurepip, venv" 2>/dev/null; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e "$BENCH_DIR[test]"
elif [ "$HAVE_SUDO" = 1 ]; then
  $SUDO apt-get install -y -qq python3-venv
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -e "$BENCH_DIR[test]"
else
  echo "python3-venv is missing and there is no sudo: using uv for the venv"
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  "$UV" venv -q --python 3.12 "$VENV"
  "$UV" pip install -q --python "$VENV/bin/python" -e "$BENCH_DIR[test]"
fi

write_env
echo
rc=0
DOC=$( . "$ENV_FILE" && "$VENV/bin/haslambench" doctor 2>&1 ) || rc=$?
printf '%s\n' "$DOC"
echo
echo "Activate with: source $VENV/bin/activate"
# doctor FAILs on Freerouting when it was not installed: expected with --no-freerouting (KiCad-only set-ups)
if [ "$rc" != 0 ] && [ "$DO_FR" = 0 ] && ! grep -v '^FAIL freerouting' <<< "$DOC" | grep -q '^FAIL'; then
  echo "(doctor's freerouting FAIL is expected with --no-freerouting)"
  rc=0
fi
exit "$rc"
