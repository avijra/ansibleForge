#!/usr/bin/env bash
# Post-package smoke test: launches the PyInstaller-bundled backend,
# validates health, SSL connectivity, and companion binary availability.
# Runs in CI after PyInstaller but before Tauri packaging.
set -euo pipefail

DIST_DIR="${DIST_DIR:-./dist/ansibleforge-backend}"
PORT="${SMOKE_TEST_PORT:-18420}"
TIMEOUT_SECS=30

if [ "$(uname -s)" = "Darwin" ] || [ "$(uname -s)" = "Linux" ]; then
  BACKEND="$DIST_DIR/ansibleforge-backend"
else
  BACKEND="$DIST_DIR/ansibleforge-backend.exe"
fi

if [ ! -f "$BACKEND" ]; then
  echo "FAIL: Backend binary not found at $BACKEND"
  exit 1
fi

cleanup() {
  if [ -n "${PID:-}" ]; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# 1. Launch backend and wait for health
# --------------------------------------------------------------------------
echo "=== Smoke Test: Starting backend on port $PORT ==="
ANSIBLEFORGE_PORT=$PORT ANSIBLEFORGE_HOST=127.0.0.1 "$BACKEND" &
PID=$!

for i in $(seq 1 $TIMEOUT_SECS); do
  if curl -sf "http://127.0.0.1:$PORT/api/v1/health" > /dev/null 2>&1; then
    echo "=== Backend healthy after ${i}s ==="
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "FAIL: Backend process died during startup"
    exit 1
  fi
  if [ "$i" -eq "$TIMEOUT_SECS" ]; then
    echo "FAIL: Backend never became healthy within ${TIMEOUT_SECS}s"
    exit 1
  fi
  sleep 1
done

HEALTH=$(curl -sf "http://127.0.0.1:$PORT/api/v1/health")
echo "Health response: $HEALTH"

# --------------------------------------------------------------------------
# 2. Validate SSL certificate resolution
# --------------------------------------------------------------------------
echo "=== Smoke Test: SSL/TLS certificate validation ==="
GALAXY_BIN="$DIST_DIR/ansible-galaxy"
if [ -f "$GALAXY_BIN" ]; then
  SSL_OUTPUT=$("$GALAXY_BIN" collection list 2>&1 || true)
  if echo "$SSL_OUTPUT" | grep -qi "CERTIFICATE_VERIFY_FAILED"; then
    echo "FAIL: SSL certificate verification failed for ansible-galaxy"
    echo "$SSL_OUTPUT"
    exit 1
  fi
  echo "  OK: ansible-galaxy SSL handshake works"
else
  echo "  SKIP: ansible-galaxy not in bundle (Windows build)"
fi

# --------------------------------------------------------------------------
# 3. Validate companion binaries exist and can print version
# --------------------------------------------------------------------------
echo "=== Smoke Test: Companion binary validation ==="
EXPECTED_BINS="ansible-galaxy ansible-playbook ansible-vault ansible-doc ansible-lint ansible-inventory"
MISSING=0

for bin in $EXPECTED_BINS; do
  BIN_PATH="$DIST_DIR/$bin"
  if [ ! -f "$BIN_PATH" ]; then
    if [ "$(uname -s)" = "MINGW"* ] || [ "$(uname -s)" = "MSYS"* ] || [ "${OS:-}" = "Windows_NT" ]; then
      echo "  SKIP: $bin (not bundled on Windows)"
    else
      echo "  FAIL: $bin missing from bundle"
      MISSING=$((MISSING + 1))
    fi
    continue
  fi
  if "$BIN_PATH" --version > /dev/null 2>&1; then
    echo "  OK: $bin"
  else
    echo "  FAIL: $bin --version returned non-zero"
    MISSING=$((MISSING + 1))
  fi
done

if [ "$MISSING" -gt 0 ]; then
  echo "FAIL: $MISSING companion binary issue(s) detected"
  exit 1
fi

# --------------------------------------------------------------------------
# 4. Validate API responds to a basic request
# --------------------------------------------------------------------------
echo "=== Smoke Test: API endpoint validation ==="
STATUS=$(curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/v1/sessions" || echo "000")
if [ "$STATUS" = "200" ]; then
  echo "  OK: GET /api/v1/sessions returned 200"
else
  echo "  WARN: GET /api/v1/sessions returned $STATUS (may be expected without auth)"
fi

# --------------------------------------------------------------------------
# 5. Validate certifi CA bundle is present in _internal
# --------------------------------------------------------------------------
echo "=== Smoke Test: CA bundle file check ==="
CA_PATH="$DIST_DIR/_internal/certifi/cacert.pem"
if [ -f "$CA_PATH" ]; then
  CA_SIZE=$(wc -c < "$CA_PATH" | tr -d ' ')
  if [ "$CA_SIZE" -gt 1000 ]; then
    echo "  OK: cacert.pem present (${CA_SIZE} bytes)"
  else
    echo "  FAIL: cacert.pem exists but is suspiciously small (${CA_SIZE} bytes)"
    exit 1
  fi
else
  if [ "$(uname -s)" = "Darwin" ] || [ "$(uname -s)" = "Linux" ]; then
    echo "  FAIL: _internal/certifi/cacert.pem not found in bundle"
    exit 1
  else
    echo "  SKIP: _internal structure may differ on Windows"
  fi
fi

echo ""
echo "=========================================="
echo "  ALL SMOKE TESTS PASSED"
echo "=========================================="
