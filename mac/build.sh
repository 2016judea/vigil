#!/bin/bash
# Build Vigil.app -- a real native menu bar app, no runtime dependencies.
#
#   ./mac/build.sh            -> builds to /Applications/Vigil.app
#   ./mac/build.sh ~/Applications
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-/Applications}"
APP="$DEST/Vigil.app"

# macOS files privacy grants, launchd jobs and Launch Services registration under
# this string, so it belongs to whoever installs -- not to whoever wrote it. The
# default squats no domain; override it with one you own if you ever sign or
# distribute the app.
BUNDLE_ID="${VIGIL_BUNDLE_ID:-local.vigil}"

# The app shells out to the daemon, so it needs a python that exists at runtime.
# Prefer a stable system-wide one over a project virtualenv, which can vanish.
PYTHON=""
for cand in /opt/homebrew/bin/python3 /usr/bin/python3 /usr/local/bin/python3; do
  if [ -x "$cand" ]; then PYTHON="$cand"; break; fi
done
[ -n "$PYTHON" ] || { echo "no python3 found" >&2; exit 1; }

echo "repo:   $ROOT"
echo "python: $PYTHON"
echo "dest:   $APP"
echo "id:     $BUNDLE_ID"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The .app is a signed, IMMUTABLE viewer -- no Python inside it.
#
# It used to carry the package, and Python wrote __pycache__/*.pyc into the
# bundle on first run, which broke the code signature ("a sealed resource is
# missing or invalid") and made Gatekeeper refuse to launch it from Finder.
# Nothing may write inside a signed bundle. The package lives in Application
# Support instead -- also outside TCC-protected ~/Desktop, which is the other
# reason it cannot live in the repo.
SUPPORT="$HOME/Library/Application Support/Vigil"

# the icon: without one the app is a generic blank in Spotlight and Launchpad
ICONSET="$(mktemp -d)/Vigil.iconset"
swiftc -O -swift-version 5 -framework AppKit \
  -o "$(dirname "$ICONSET")/makeicon" "$ROOT/mac/makeicon.swift"
"$(dirname "$ICONSET")/makeicon" "$ICONSET" >/dev/null
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Vigil.icns"

swiftc -O \
  -swift-version 5 \
  -target arm64-apple-macosx13.0 \
  -framework AppKit \
  -o "$APP/Contents/MacOS/Vigil" \
  "$ROOT/mac/Vigil.swift"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Vigil</string>
  <key>CFBundleDisplayName</key><string>Vigil</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>Vigil</string>
  <key>CFBundleIconFile</key><string>Vigil</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <!-- menu bar only: no Dock icon, no app switcher entry -->
  <key>LSUIElement</key><true/>
  <key>VigilRepoPath</key><string>$SUPPORT</string>
  <key>VigilPython</key><string>$PYTHON</string>
</dict>
</plist>
PLIST

# ad-hoc signature so Gatekeeper lets a locally built app run
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || \
  echo "  (codesign skipped -- app still runs locally)"

echo
echo "built. open it with:  open \"$APP\""
