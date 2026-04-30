#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "==> Building UI..."
(cd ui && npm ci && npm run build)

echo "==> Installing Python dependencies..."
pip install --quiet . pyinstaller

echo "==> Running PyInstaller..."
pyinstaller --clean --noconfirm ansibleforge.spec

echo "==> Copying backend bundle to electron/resources/backend/..."
BACKEND_OUT="$PROJECT_ROOT/dist/ansibleforge-backend"
ELECTRON_RES="$PROJECT_ROOT/electron/resources/backend"

rm -rf "$ELECTRON_RES"
mkdir -p "$ELECTRON_RES"
cp -R "$BACKEND_OUT"/* "$ELECTRON_RES/"

echo "==> Backend build complete."
echo "    Output: $ELECTRON_RES"
echo "    Size: $(du -sh "$ELECTRON_RES" | cut -f1)"
