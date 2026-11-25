#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the magnetic-trowel/freerouting fork and install it where haslam's bridge finds it:
#   $HASLAM_HOME/haslam-freerouting-fork-<sha>/bin/freerouting
# with its own Java runtime (jlink, the modules of the upstream 2.5.0 bundle), so it runs in
# the benchmark sandbox without a system JDK. haslam.route.freerouting runs the build named by
# HASLAM_BRIDGE_FREEROUTING or pinned in $HASLAM_HOME/haslam-freerouting.pin, never the newest install:
# --pin makes this build the pinned one. haslambench's own `freerouting` adapter keeps using the
# upstream release, so the human+Freerouting baseline does not change.
#
#   tools/research/routing/install_freerouting_fork.sh [REF] [SRC_DIR] [--pin]
# REF defaults to origin/master; SRC_DIR to $HASLAM_HOME/src/freerouting (cloned if missing).
# Gradle provisions the JDK 25 toolchain the fork needs.
set -euo pipefail
PIN=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--pin" ]; then PIN=1; else ARGS+=("$a"); fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"
HASLAM_HOME=${HASLAM_HOME:-$HOME/.cache/haslambench}
REF=${1:-origin/master}
SRC=${2:-$HASLAM_HOME/src/freerouting}
URL=https://github.com/magnetic-trowel/freerouting
MODULES=java.base,java.datatransfer,java.xml,java.prefs,java.desktop,java.logging,java.management,java.net.http,java.transaction.xa,java.sql,jdk.crypto.ec,jdk.management

if [ ! -d "$SRC/.git" ]; then
  git clone -q "$URL" "$SRC"
fi
git -C "$SRC" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git -C "$SRC" fetch -q --prune origin
git -C "$SRC" checkout -q --detach "$REF"
SHA=$(git -C "$SRC" rev-parse --short=7 HEAD)
DEST=$HASLAM_HOME/haslam-freerouting-fork-$SHA
pin() {
  if [ "$PIN" = 1 ]; then
    echo "$DEST/bin/freerouting" > "$HASLAM_HOME/haslam-freerouting.pin"
    echo "pinned: $DEST/bin/freerouting ($HASLAM_HOME/haslam-freerouting.pin)"
  fi
}
if [ -x "$DEST/bin/freerouting" ]; then
  echo "already installed: $DEST/bin/freerouting"
  pin
  exit 0
fi
# Gradle's wrapper needs a java to start: JAVA_HOME, else java on PATH, else a JDK in HASLAM_HOME
if [ -z "${JAVA_HOME:-}" ] && ! command -v java > /dev/null; then
  for d in "$HASLAM_HOME"/jdk-25*; do [ -x "$d/bin/java" ] && export JAVA_HOME=$d && break; done
fi
(cd "$SRC" && ./gradlew -q executableJar)
JAR=$(ls "$SRC"/build/libs/*-executable.jar)
# jlink from a JDK 25: the toolchain gradle provisioned, else JAVA_HOME (gradle uses it when it is 25)
JDK=$( (ls -d "$HOME"/.gradle/jdks/*25*/ 2>/dev/null || true) | grep -v '\.tar' | head -1 || true)
if [ ! -x "${JDK:-/nonexistent}/bin/jlink" ] && [ -n "${JAVA_HOME:-}" ] \
   && "$JAVA_HOME/bin/java" -version 2>&1 | grep -q 'version "25'; then
  JDK=$JAVA_HOME
fi
[ -x "${JDK:-/nonexistent}/bin/jlink" ] || { echo "no JDK 25 for jlink (gradle toolchain or JAVA_HOME)"; exit 1; }
TMP=$DEST.tmp
rm -rf "$TMP" && mkdir -p "$TMP/bin" "$TMP/lib"
"$JDK/bin/jlink" --add-modules "$MODULES" --strip-debug --no-header-files --no-man-pages \
  --output "$TMP/lib/runtime"
cp "$JAR" "$TMP/lib/freerouting.jar"
cat > "$TMP/bin/freerouting" <<'EOF'
#!/bin/sh
D=$(cd "$(dirname "$0")/.." && pwd)
exec "$D/lib/runtime/bin/java" $FREEROUTING_JAVA_OPTS -jar "$D/lib/freerouting.jar" "$@"
EOF
chmod +x "$TMP/bin/freerouting"
echo "$SHA $(git -C "$SRC" log -1 --format=%s)" > "$TMP/VERSION"
mv "$TMP" "$DEST"
"$DEST/bin/freerouting" --help 2>&1 | grep -m1 "Freerouting v" || true
echo "installed: $DEST/bin/freerouting"
pin
