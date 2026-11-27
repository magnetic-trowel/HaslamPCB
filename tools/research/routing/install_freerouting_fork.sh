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
# Gradle provisions the JDK 25 toolchain the fork needs; with no Java 17+ to start Gradle, a Temurin JDK 25 is
# downloaded into $HASLAM_HOME/jdk-25. FR_RETRY_WAITS (default "30 90 240") are the seconds between build retries.
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
  # blobless: the full history is ~2.3 GB of old blobs; a checkout fetches only the blobs it needs
  git clone -q --filter=blob:none "$URL" "$SRC" || { rm -rf "$SRC"; git clone -q "$URL" "$SRC"; }
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
# Gradle's wrapper needs a java (17+) to start: JAVA_HOME, else java on PATH, else a JDK 25 in HASLAM_HOME,
# downloaded from Adoptium (Temurin, sha256-checked) on a machine with none: a fresh Ubuntu has no Java
java_major() { { "$1" -version 2>&1 || true; } | sed -n 's/.* version "\([0-9]*\).*/\1/p' | head -1; }
JV=$(command -v java > /dev/null && java_major java || true)
if [ -z "${JAVA_HOME:-}" ] && [ "${JV:-0}" -lt 17 ]; then
  for d in "$HASLAM_HOME"/jdk-25*; do [ -x "$d/bin/java" ] && export JAVA_HOME=$d && break; done
  if [ -z "${JAVA_HOME:-}" ]; then
    case "$(uname -m)" in x86_64) ARCH=x64 ;; aarch64) ARCH=aarch64 ;; *) ARCH=$(uname -m) ;; esac
    read -r JDK_URL JDK_SHA < <(curl -fsSL \
      "https://api.adoptium.net/v3/assets/latest/25/hotspot?os=linux&architecture=$ARCH&image_type=jdk&vendor=eclipse" |
      python3 -c "import json,sys; p=json.load(sys.stdin)[0]['binary']['package']; print(p['link'], p['checksum'])")
    echo "No Java 17+ found: downloading Temurin JDK 25 into $HASLAM_HOME/jdk-25 (~140 MB)"
    rm -rf "$HASLAM_HOME/jdk-25" "$HASLAM_HOME/jdk-25.tar.gz" && mkdir -p "$HASLAM_HOME/jdk-25"
    curl -fsSL -o "$HASLAM_HOME/jdk-25.tar.gz" "$JDK_URL"
    echo "$JDK_SHA  $HASLAM_HOME/jdk-25.tar.gz" | sha256sum -c - > /dev/null
    tar -xzf "$HASLAM_HOME/jdk-25.tar.gz" -C "$HASLAM_HOME/jdk-25" --strip-components=1
    rm -f "$HASLAM_HOME/jdk-25.tar.gz"
    export JAVA_HOME=$HASLAM_HOME/jdk-25
  fi
fi
# Maven Central and the Gradle/JDK downloads rate-limit shared egress (HTTP 429): retry with backoff, and try
# --offline once a cache exists (a failed attempt may have fetched everything already)
build() { (cd "$SRC" && ./gradlew -q "$@" executableJar); }
ok=0
for wait in ${FR_RETRY_WAITS:-30 90 240}; do
  if build; then ok=1; break; fi
  if [ -d "${GRADLE_USER_HOME:-$HOME/.gradle}/caches/modules-2" ] && build --offline; then ok=1; break; fi
  echo "gradle build failed (rate limit or network?): retrying in ${wait}s" >&2
  sleep "$wait"
done
if [ "$ok" = 0 ] && ! build; then
  echo "gradle build failed 4 times; see the output above" >&2
  exit 1
fi
JAR=$(ls "$SRC"/build/libs/*-executable.jar)
# jlink from a JDK 25: the toolchain gradle provisioned, else JAVA_HOME (gradle uses it when it is 25)
JDK=$( (ls -d "${GRADLE_USER_HOME:-$HOME/.gradle}"/jdks/*25*/ 2>/dev/null || true) | grep -v '\.tar' | head -1 || true)
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
