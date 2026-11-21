#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build TraceMaker (https://github.com/DingoOz/TraceMaker, GPL-3.0-or-later) for the CPU and install it
# where the benchmark sandbox can run it:  $KAE_HOME/tracemaker-<sha8>/bin/tracemaker  (+ lib/).
# Its source is never copied into this repository.
#
#   install_tracemaker.sh WORKDIR TOOLCHAIN_PREFIX [REF]
#     WORKDIR           scratch dir (source, header-only dependencies, build tree)
#     TOOLCHAIN_PREFIX  a conda-forge prefix with gcc/g++ 15, cmake >= 3.28, ninja, boost >= 1.81, zstd, sqlite
#     REF               git ref (default v0.12.1)
#
# TraceMaker needs C++20 and is tested with GCC 15 only; Ubuntu 22.04's GCC 11 does not build it.
# nlohmann_json, CLI11 and Eigen are fetched as header-only installs; Clipper2 is fetched by its own CMake.
# libstdc++/libgcc are linked statically; the remaining shared libraries the toolchain prefix provides
# (zstd, sqlite, ...) are copied into lib/ and found through RPATH $ORIGIN/../lib.
set -euo pipefail
W=$(realpath -m "$1"); ENV=$(realpath "$2"); REF=${3:-v0.12.1}
KAE_HOME=${KAE_HOME:-$HOME/.cache/kaebench}
export PATH=$ENV/bin:/usr/bin:/bin
J=${KAEQ_CPUS:-$(nproc)}
mkdir -p "$W"
[ -d "$W/src/.git" ] || git clone -q https://github.com/DingoOz/TraceMaker "$W/src"
git -C "$W/src" fetch -q --tags origin
git -C "$W/src" checkout -q "$REF"
SHA=$(git -C "$W/src" rev-parse HEAD)
dep() { [ -d "$W/deps-src/$1" ] || git clone -q --depth 1 -b "$3" "$2" "$W/deps-src/$1"; }
dep nlohmann_json https://github.com/nlohmann/json.git v3.11.3
dep CLI11 https://github.com/CLIUtils/CLI11.git v2.4.2
dep eigen https://gitlab.com/libeigen/eigen.git 3.4.0
for d in nlohmann_json CLI11 eigen; do
  cmake -S "$W/deps-src/$d" -B "$W/deps-build/$d" -G Ninja -DCMAKE_INSTALL_PREFIX="$W/deps" \
    -DJSON_BuildTests=OFF -DCLI11_BUILD_TESTS=OFF -DCLI11_BUILD_EXAMPLES=OFF -DCLI11_BUILD_DOCS=OFF \
    -DBUILD_TESTING=OFF -DEIGEN_BUILD_DOC=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >/dev/null
  cmake --build "$W/deps-build/$d" --target install -j "$J" >/dev/null
done
cmake -S "$W/src" -B "$W/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DTM_ENABLE_CUDA=OFF -DTM_BUILD_TESTS=OFF -DTM_BUILD_PYTHON=OFF \
  -DTM_WERROR=OFF -DTM_STATIC_RELEASE=ON \
  -DCMAKE_CXX_COMPILER="$ENV/bin/x86_64-conda-linux-gnu-g++" \
  -DCMAKE_PREFIX_PATH="$W/deps;$ENV" \
  -DCMAKE_INSTALL_RPATH='$ORIGIN/../lib' -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON
cmake --build "$W/build" -j "$J" --target tracemaker
BIN=$(find "$W/build" -type f -executable -name tracemaker | head -1)
DEST="$KAE_HOME/tracemaker-${SHA:0:8}"
rm -rf "$DEST"; mkdir -p "$DEST/bin" "$DEST/lib"
cp "$BIN" "$DEST/bin/"
# shared libraries from the toolchain prefix (system libraries stay with the system)
LD_LIBRARY_PATH=$ENV/lib ldd "$DEST/bin/tracemaker" | awk -v e="$ENV/" 'index($3, e) == 1 {print $3}' |
  while read -r so; do cp -L "$so" "$DEST/lib/"; done
echo "$SHA $REF" > "$DEST/SOURCE"
"$DEST/bin/tracemaker" version
echo "installed $DEST (TraceMaker $REF = $SHA)"
