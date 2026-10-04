#!/bin/sh
# Smoke-test an AlphaBrief dmg exactly as GUIDE S8-3 requires:
#   - mount the dmg read-only into a temporary directory,
#   - run the packaged backend with a throwaway data directory,
#   - trading_mode=off, no LaunchAgent installed, never touching the
#     operator's real data directory or OANDA trading rights,
#   - check --version, doctor, /health and the static dashboard.
#
# Usage: scripts/smoke_test_dmg.sh <path-to.dmg>
set -eu

DMG="${1:?usage: smoke_test_dmg.sh <path-to.dmg>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXPECTED_VERSION="$(python3 -c 'import tomllib; print(tomllib.load(open("'"$REPO_ROOT"'/pyproject.toml","rb"))["project"]["version"])')"

WORK="$(mktemp -d /tmp/alphabrief-smoke.XXXXXX)"
MOUNT="$WORK/volume"
HOME_TMP="$WORK/home"
mkdir -p "$HOME_TMP"
PORT="${SMOKE_PORT:-8933}"

cleanup() {
    [ -n "${SERVE_PID:-}" ] && kill "$SERVE_PID" 2>/dev/null || true
    hdiutil detach "$MOUNT" -quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
    echo "smoke_test_dmg: $*" >&2
    exit 1
}

echo "smoke: mounting $DMG at $MOUNT"
hdiutil attach "$DMG" -readonly -nobrowse -mountpoint "$MOUNT" >/dev/null \
    || fail "hdiutil attach failed"
APP_DIR="$(ls -d "$MOUNT"/*.app | head -1)"
[ -n "$APP_DIR" ] || fail "no .app bundle in dmg"
BACKEND="$APP_DIR/Contents/Resources/backend/alphabrief/alphabrief"
[ -x "$BACKEND" ] || fail "packaged backend missing at $BACKEND"

echo "smoke: --version"
GOT_VERSION="$(ALPHABRIEF_HOME="$HOME_TMP" "$BACKEND" --version)"
echo "$GOT_VERSION" | grep -qF "$EXPECTED_VERSION" \
    || fail "--version printed '$GOT_VERSION', expected $EXPECTED_VERSION"
echo "smoke: version OK ($GOT_VERSION)"

echo "smoke: doctor (temp data dir, trading off)"
# The doctor exits non-zero when any check FAILs. In a throwaway home the
# model channel is expected to FAIL (no OAuth secrets there). The doctor
# must still complete, produce JSON, and the real OANDA read-only check
# must PASS, proving the frozen binary can reach the practice API.
ALPHABRIEF_HOME="$HOME_TMP" ALPHABRIEF_TRADING_MODE=off "$BACKEND" doctor run \
    > "$WORK/doctor.json" 2> "$WORK/doctor.err" \
    || echo "smoke: note: doctor exited non-zero (expected FAIL items below)"
grep -q '"oanda_read_only"' "$WORK/doctor.json" || fail "doctor output missing oanda_read_only check"
grep -A2 '"check": "oanda_read_only"' "$WORK/doctor.json" | grep -q '"status": "PASS"' \
    || fail "oanda_read_only doctor check did not PASS; see $WORK/doctor.json"
echo "smoke: doctor OK (oanda_read_only PASS)"

echo "smoke: serve + static dashboard on port $PORT"
ALPHABRIEF_HOME="$HOME_TMP" ALPHABRIEF_TRADING_MODE=off \
    "$BACKEND" serve serve --host 127.0.0.1 --port "$PORT" \
    > "$WORK/serve.log" 2>&1 &
SERVE_PID=$!

HEALTH_OK=0
i=0
while [ $i -lt 40 ]; do
    if curl -sf "http://127.0.0.1:$PORT/health" > "$WORK/health.json" 2>/dev/null; then
        HEALTH_OK=1
        break
    fi
    i=$((i + 1))
    sleep 1
done
[ "$HEALTH_OK" = 1 ] || { cat "$WORK/serve.log" >&2; fail "backend /health never became 200"; }
grep -qF "$EXPECTED_VERSION" "$WORK/health.json" || fail "health version mismatch: $(cat "$WORK/health.json")"
echo "smoke: health OK ($(cat "$WORK/health.json"))"

curl -sf "http://127.0.0.1:$PORT/" | grep -qi "alphabrief" \
    || fail "static dashboard did not serve the index page"
echo "smoke: static dashboard OK"

curl -sf "http://127.0.0.1:$PORT/api/v1/review/reports" | grep -q '"reports"' \
    || fail "review reports API did not respond"
echo "smoke: review API OK"

kill "$SERVE_PID" 2>/dev/null || true
unset SERVE_PID
sleep 1

echo "smoke: ALL CHECKS PASSED (temp home $HOME_TMP was not installed as a LaunchAgent)"
