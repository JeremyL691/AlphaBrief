#!/bin/sh
# Build the AlphaBrief release: PyInstaller backend -> electron-builder dmg
# -> SHA256SUMS.txt. Artifacts land in dist/ at the repository root.
#
# Usage: scripts/build_release.sh
#
# The version must agree across pyproject.toml, alphabrief_core/version.py,
# and electron/package.json; the script refuses to build otherwise.
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PY="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
ELECTRON_DIR="$REPO_ROOT/electron"

fail() {
    echo "build_release: $*" >&2
    exit 1
}

[ -x "$PY" ] || fail "python not found at $PY (set PYTHON=... to override)"
command -v npx >/dev/null 2>&1 || fail "npx is required for electron-builder"

# --- version consistency ------------------------------------------------
PYPROJECT_VERSION="$("$PY" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
CORE_VERSION="$("$PY" -c 'from alphabrief_core.version import __version__; print(__version__)')"
ELECTRON_VERSION="$("$PY" -c 'import json; print(json.load(open("electron/package.json"))["version"])')"

echo "build_release: pyproject=$PYPROJECT_VERSION core=$CORE_VERSION electron=$ELECTRON_VERSION"
if [ "$PYPROJECT_VERSION" != "$CORE_VERSION" ] || [ "$PYPROJECT_VERSION" != "$ELECTRON_VERSION" ]; then
    fail "version mismatch across pyproject.toml / alphabrief_core/version.py / electron/package.json"
fi

# --- 1. backend (PyInstaller, onedir) ------------------------------------
echo "build_release: building backend with PyInstaller..."
rm -rf "$ELECTRON_DIR/backend-dist" /tmp/alphabrief-pyinstaller-work
PKG_PATHS=""
for d in apps/cli/src apps/api/src packages/*/src; do
    PKG_PATHS="$PKG_PATHS --paths $d"
done
# shellcheck disable=SC2086
"$PY" -m PyInstaller \
    --name alphabrief \
    --onedir \
    --noconfirm \
    --clean \
    --copy-metadata alphabrief \
    $PKG_PATHS \
    --add-data "apps/api/src/alphabrief_api/static:alphabrief_api/static" \
    --add-data "config:config" \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import pytz \
    apps/cli/src/alphabrief_cli/__main__.py \
    --distpath "$ELECTRON_DIR/backend-dist" \
    --workpath /tmp/alphabrief-pyinstaller-work \
    >/tmp/alphabrief-pyinstaller-build.log 2>&1 \
    || fail "PyInstaller backend build failed; see /tmp/alphabrief-pyinstaller-build.log"

# Frozen CLI must report the release version.
BUILT_VERSION="$("$PY" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
ALPHABRIEF_HOME="$(mktemp -d)/home" "$ELECTRON_DIR/backend-dist/alphabrief/alphabrief" --version \
    | grep -qF "$BUILT_VERSION" \
    || fail "packaged backend --version output mismatch"

echo "build_release: backend built."

# --- 2. desktop (electron-builder dmg, arm64, unsigned) ------------------
echo "build_release: building dmg with electron-builder..."
(cd "$ELECTRON_DIR" && npx electron-builder --mac dmg --arm64) \
    >/tmp/alphabrief-electron-builder.log 2>&1 \
    || fail "electron-builder failed; see /tmp/alphabrief-electron-builder.log"

DMG="$ELECTRON_DIR/dist/AlphaBrief-$PYPROJECT_VERSION-arm64.dmg"
[ -f "$DMG" ] || fail "expected dmg not found at $DMG"

# --- 3. checksums ---------------------------------------------------------
OUT_DIR="$REPO_ROOT/dist"
mkdir -p "$OUT_DIR"
cp "$DMG" "$OUT_DIR/"
(
    cd "$OUT_DIR"
    shasum -a 256 "$(basename "$DMG")" > SHA256SUMS.txt
)
echo "build_release: artifacts in $OUT_DIR:"
ls -la "$OUT_DIR"
cat "$OUT_DIR/SHA256SUMS.txt"
echo "build_release: done."
