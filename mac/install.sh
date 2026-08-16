#!/bin/bash
# Install Vigil properly on this Mac:
#   1. build Vigil.app          -> ~/Applications/Vigil.app  (menu bar)
#   2. install a LaunchAgent    -> daemon runs at login, exactly one, restarts
#   3. put `vigil` on PATH      -> ~/.local/bin/vigil
#
#   ./mac/install.sh            install everything
#   ./mac/install.sh --uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="dev.brickandmortar.vigil"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SHIM="$HOME/.local/bin/vigil"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$PLIST" "$SHIM"
  rm -rf "$HOME/Applications/Vigil.app"
  echo "vigil removed. (the repo and ~/.claude-archive are untouched)"
  exit 0
fi

PYTHON=""
for cand in /opt/homebrew/bin/python3 /usr/bin/python3 /usr/local/bin/python3; do
  [ -x "$cand" ] && { PYTHON="$cand"; break; }
done
[ -n "$PYTHON" ] || { echo "no python3 found" >&2; exit 1; }

echo "1/3  building the app"
"$ROOT/mac/build.sh" "$HOME/Applications" >/dev/null

RUNDIR="$HOME/Applications/Vigil.app/Contents/Resources"

echo "2/3  installing the LaunchAgent"
# launchd owns the daemon: one instance, restarted if it dies, started at login.
# Letting the app spawn it produced orphans that were alive but not listening.
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-u</string>
    <string>-m</string>
    <string>vigil</string>
  </array>
  <key>WorkingDirectory</key><string>$RUNDIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONPATH</key><string>$RUNDIR</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/vigil-daemon.log</string>
  <key>StandardErrorPath</key><string>/tmp/vigil-daemon.log</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
pkill -f "\-m vigil" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$UID" "$PLIST"

echo "3/3  putting \`vigil\` on PATH"
mkdir -p "$(dirname "$SHIM")"
cat > "$SHIM" <<SHIM_EOF
#!/bin/bash
exec "$PYTHON" -m vigil "\$@"
SHIM_EOF
chmod +x "$SHIM"
# the shim needs the package importable from anywhere, not just the repo
printf '%s\n' "PYTHONPATH=$ROOT" >/dev/null
sed -i '' "2i\\
export PYTHONPATH=\"$RUNDIR:\${PYTHONPATH:-}\"
" "$SHIM"

sleep 3
echo
if curl -s -m 4 http://127.0.0.1:7717/api/state >/dev/null 2>&1; then
  echo "  daemon      running  (launchd, restarts itself, starts at login)"
else
  echo "  daemon      NOT reachable -- check /tmp/vigil-daemon.log"
fi
echo "  the Face    http://127.0.0.1:7717"
echo "  menu bar    open ~/Applications/Vigil.app"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) echo "  terminal    vigil status" ;;
  *) echo "  terminal    vigil status   (add ~/.local/bin to PATH first)" ;;
esac
