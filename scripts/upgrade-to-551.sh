#!/usr/bin/env bash
set -euo pipefail

TAG="v5.5.1"
REPO="avijra/ansibleForge"
LOG="/tmp/tuyere-upgrade-551.log"
APP_NAME="Tuyere"
DMG_PATTERN="arm64.dmg"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Tuyere upgrade to $TAG ==="

# --- 1. Wait for CI build ---
log "Waiting for CI build to finish..."
RUN_ID=$(gh run list --repo "$REPO" --branch "$TAG" --limit 1 --json databaseId --jq '.[0].databaseId')
if [ -z "$RUN_ID" ]; then
  log "ERROR: Could not find CI run for $TAG"
  exit 1
fi
log "Watching run $RUN_ID"

while true; do
  STATUS=$(gh run view "$RUN_ID" --repo "$REPO" --json status --jq '.status')
  if [ "$STATUS" = "completed" ]; then
    CONCLUSION=$(gh run view "$RUN_ID" --repo "$REPO" --json conclusion --jq '.conclusion')
    log "CI finished with conclusion: $CONCLUSION"
    break
  fi
  log "  status=$STATUS — sleeping 30s..."
  sleep 30
done

# Check if mac build succeeded (we don't care about windows)
MAC_STATUS=$(gh run view "$RUN_ID" --repo "$REPO" --json jobs --jq '[.jobs[] | select(.name == "build-mac-arm64")][0].conclusion')
if [ "$MAC_STATUS" != "success" ]; then
  log "ERROR: build-mac-arm64 did not succeed (got: $MAC_STATUS). Aborting."
  exit 1
fi
log "Mac ARM64 build succeeded."

# --- 2. Wait for release to appear ---
log "Waiting for GitHub release $TAG..."
for i in $(seq 1 20); do
  if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
    log "Release $TAG found."
    break
  fi
  if [ "$i" -eq 20 ]; then
    log "ERROR: Release $TAG not found after 10 minutes. Aborting."
    exit 1
  fi
  sleep 30
done

# --- 3. Kill running Tuyere ---
log "Killing any running Tuyere processes..."
pkill -f "Tuyere" 2>/dev/null || true
pkill -f "tuyere" 2>/dev/null || true
pkill -f "ansible_forge" 2>/dev/null || true
sleep 2
pkill -9 -f "Tuyere" 2>/dev/null || true
pkill -9 -f "tuyere" 2>/dev/null || true
log "Processes killed."

# --- 4. Unmount any existing DMGs ---
log "Unmounting any Tuyere DMGs..."
for vol in /Volumes/Tuyere*; do
  [ -d "$vol" ] && hdiutil detach "$vol" -force 2>/dev/null || true
done
log "DMGs unmounted."

# --- 5. Remove existing app and ALL data ---
log "Removing existing app and data..."
rm -rf "/Applications/$APP_NAME.app"
rm -rf "$HOME/Library/Application Support/com.tuyere.app"
rm -rf "$HOME/Library/Application Support/Tuyere"
rm -rf "$HOME/Library/Caches/com.tuyere.app"
rm -rf "$HOME/Library/Caches/Tuyere"
rm -rf "$HOME/Library/Preferences/com.tuyere.app.plist"
rm -rf "$HOME/Library/Saved Application State/com.tuyere.app.savedState"
rm -rf "$HOME/Library/Logs/Tuyere"
rm -rf "$HOME/Library/WebKit/com.tuyere.app"
rm -rf "$HOME/.tuyere"
rm -rf /tmp/tuyere-*
rm -rf /tmp/Tuyere-*
log "Clean slate achieved."

# --- 6. Download DMG ---
log "Downloading $TAG DMG..."
DL_DIR="/tmp/tuyere-upgrade"
rm -rf "$DL_DIR"
mkdir -p "$DL_DIR"
gh release download "$TAG" --repo "$REPO" --pattern "*${DMG_PATTERN}" --dir "$DL_DIR"
DMG_FILE=$(ls "$DL_DIR"/*${DMG_PATTERN} 2>/dev/null | head -1)
if [ -z "$DMG_FILE" ]; then
  log "ERROR: No DMG found matching *${DMG_PATTERN}"
  exit 1
fi
log "Downloaded: $DMG_FILE"

# --- 7. Mount and install ---
log "Mounting DMG..."
MOUNT_POINT=$(hdiutil attach "$DMG_FILE" -nobrowse -noverify 2>/dev/null | grep '/Volumes/' | awk -F'\t' '{print $NF}')
if [ -z "$MOUNT_POINT" ]; then
  log "ERROR: Failed to mount DMG"
  exit 1
fi
log "Mounted at: $MOUNT_POINT"

APP_IN_DMG=$(ls -d "$MOUNT_POINT"/*.app 2>/dev/null | head -1)
if [ -z "$APP_IN_DMG" ]; then
  log "ERROR: No .app found in DMG"
  hdiutil detach "$MOUNT_POINT" -force 2>/dev/null || true
  exit 1
fi

log "Copying to /Applications..."
cp -R "$APP_IN_DMG" /Applications/
log "Unmounting..."
hdiutil detach "$MOUNT_POINT" -force 2>/dev/null || true

# --- 8. Clear quarantine and launch ---
log "Clearing quarantine..."
xattr -cr "/Applications/$APP_NAME.app" 2>/dev/null || true

log "Launching Tuyere $TAG..."
open "/Applications/$APP_NAME.app"

log "=== DONE === Tuyere $TAG is installed and launched."
log "Upgrade log saved to $LOG"
