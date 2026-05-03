#!/bin/bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
step()  { echo -e "\n${GREEN}===${NC} $1 ${GREEN}===${NC}"; }

APP_NAME="Tuyere"
APP_PATH="/Applications/${APP_NAME}.app"
DATA_DIR="$HOME/.ansibleforge"
ELECTRON_DIR="$HOME/Library/Application Support/tuyere-desktop"
DOWNLOAD_DIR="$HOME/Downloads"

step "Stopping all ${APP_NAME} processes"
pkill -f "${APP_NAME}" 2>/dev/null && info "Killed app processes" || info "No app processes running"
pkill -f "ansibleforge-backend" 2>/dev/null && info "Killed backend" || info "No backend running"
sleep 2

REMAINING=$(ps aux | grep -iE "tuyere|ansibleforge-backend" | grep -v grep | grep -v "Cursor Helper" | wc -l | tr -d ' ')
if [ "$REMAINING" -gt 0 ]; then
    warn "Force-killing $REMAINING stubborn processes"
    ps aux | grep -iE "tuyere|ansibleforge-backend" | grep -v grep | grep -v "Cursor Helper" | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    sleep 1
fi
info "All processes stopped"

step "Removing installed app"
if [ -d "$APP_PATH" ]; then
    rm -rf "$APP_PATH"
    info "Removed $APP_PATH"
else
    info "No app installed"
fi

step "Ejecting mounted DMGs"
for vol in /Volumes/${APP_NAME}*; do
    if [ -d "$vol" ]; then
        hdiutil detach "$vol" -force 2>/dev/null && info "Ejected $vol" || warn "Failed to eject $vol"
    fi
done
info "All volumes ejected"

step "Deleting old DMGs from Downloads"
FOUND=0
for dmg in "$DOWNLOAD_DIR"/${APP_NAME}*.dmg "$DOWNLOAD_DIR"/tuyere*.dmg; do
    if [ -f "$dmg" ]; then
        rm -f "$dmg"
        info "Deleted $dmg"
        FOUND=$((FOUND + 1))
    fi
done
[ "$FOUND" -eq 0 ] && info "No old DMGs found"

step "Wiping backend data"
if [ -d "$DATA_DIR" ]; then
    rm -rf "$DATA_DIR"
    info "Removed $DATA_DIR"
else
    info "No backend data"
fi

step "Wiping Electron state"
if [ -d "$ELECTRON_DIR" ]; then
    rm -rf "$ELECTRON_DIR"
    info "Removed $ELECTRON_DIR"
else
    info "No Electron state"
fi

step "Verification"
[ ! -d "$APP_PATH" ]      && info "App: clean"         || warn "App still exists!"
[ ! -d "$DATA_DIR" ]      && info "Backend data: clean" || warn "Backend data still exists!"
[ ! -d "$ELECTRON_DIR" ]  && info "Electron state: clean" || warn "Electron state still exists!"

PROCS=$(ps aux | grep -iE "tuyere|ansibleforge-backend" | grep -v grep | grep -v "Cursor Helper" | wc -l | tr -d ' ')
[ "$PROCS" -eq 0 ] && info "Processes: clean" || warn "$PROCS processes still running!"

echo ""
info "Fresh user state achieved. Download the latest release:"
echo -e "  ${YELLOW}https://github.com/avijra/ansibleForge/releases/latest${NC}"
echo ""
echo "  After downloading:"
echo "    1. Open the DMG and drag to Applications"
echo "    2. xattr -cr /Applications/${APP_NAME}.app"
echo "    3. Launch ${APP_NAME}"
