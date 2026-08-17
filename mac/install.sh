#!/bin/bash
# Install Vigil properly on this Mac:
#   1. build Vigil.app          -> /Applications/Vigil.app  (menu bar)
#   2. install a LaunchAgent    -> daemon runs at login, exactly one, restarts
#   3. put `vigil` on PATH      -> ~/.local/bin/vigil
#
#   ./mac/install.sh            install everything
#   ./mac/install.sh --uninstall
#
# VIGIL_ROOTS in this shell is baked into the LaunchAgent, because the daemon is
# what reads it -- exporting it in your own shell does nothing once the daemon is
# up, since the CLI just asks the daemon:
#   VIGIL_ROOTS=~/code:~/work ./mac/install.sh
#
# VIGIL_BUNDLE_ID sets the app identity and the launchd label. Use a domain you
# own if you sign or distribute; the default squats nothing:
#   VIGIL_BUNDLE_ID=dev.example.vigil ./mac/install.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export VIGIL_BUNDLE_ID="${VIGIL_BUNDLE_ID:-local.vigil}"   # build.sh reads this too
LABEL="$VIGIL_BUNDLE_ID"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SHIM="$HOME/.local/bin/vigil"

# Every LaunchAgent that runs this daemon, whatever it happens to be labelled.
# The bundle id is configurable, so a rename would otherwise leave the old job
# running beside the new one -- two pollers racing for one port, which is the
# failure the daemon's own already_running() check exists to prevent. Match on
# what a job DOES, not on what it is called.
sweep_agents() {
  local p base
  for p in "$HOME"/Library/LaunchAgents/*.plist; do
    [ -f "$p" ] || continue
    grep -q -- '<string>-m</string>' "$p" 2>/dev/null \
      && grep -q -- '<string>vigil</string>' "$p" 2>/dev/null || continue
    base="$(basename "$p" .plist)"
    launchctl bootout "gui/$UID/$base" 2>/dev/null || true
    rm -f "$p"
  done
}

if [ "${1:-}" = "--uninstall" ]; then
  sweep_agents
  rm -f "$PLIST" "$SHIM"
  rm -rf "$HOME/Library/Application Support/Vigil" "$HOME/Library/Caches/vigil"
  rm -rf /Applications/Vigil.app "$HOME/Applications/Vigil.app"
  echo "vigil removed. (the repo and ~/.claude-archive are untouched)"
  exit 0
fi

PYTHON=""
for cand in /opt/homebrew/bin/python3 /usr/bin/python3 /usr/local/bin/python3; do
  [ -x "$cand" ] && { PYTHON="$cand"; break; }
done
[ -n "$PYTHON" ] || { echo "no python3 found" >&2; exit 1; }

SUPPORT="$HOME/Library/Application Support/Vigil"

echo "1/4  staging the daemon outside the app bundle"
# Not in the .app (writing there breaks its signature) and not in ~/Desktop
# (TCC-protected, so a LaunchAgent hangs in interpreter startup).
mkdir -p "$SUPPORT"
rm -rf "$SUPPORT/vigil"
cp -R "$ROOT/vigil" "$SUPPORT/vigil"
rm -rf "$SUPPORT/vigil/__pycache__"

echo "2/4  building the app"
"$ROOT/mac/build.sh" /Applications >/dev/null

# Without this the app is invisible to Spotlight and Launchpad even though it
# sits in /Applications -- a freshly written bundle is not registered until asked.
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[ -x "$LSREG" ] && "$LSREG" -f /Applications/Vigil.app 2>/dev/null || true
mdimport /Applications/Vigil.app 2>/dev/null || true

RUNDIR="$SUPPORT"

# only emit the key when set, so a plain re-install does not pin the roots to
# whatever happened to be exported the last time
ROOTS_ENTRY=""
if [ -n "${VIGIL_ROOTS:-}" ]; then
  ROOTS_ENTRY="    <key>VIGIL_ROOTS</key><string>$VIGIL_ROOTS</string>"
fi

echo "3/4  installing the LaunchAgent"
# launchd owns the daemon: one instance, restarted if it dies, started at login.
# Letting the app spawn it produced orphans that were alive but not listening.
mkdir -p "$HOME/Library/LaunchAgents"
# Before writing ours, not after -- the sweep matches any agent running `-m vigil`,
# which includes the plist below the moment it exists.
sweep_agents
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
  <dict>
    <key>PYTHONPATH</key><string>$RUNDIR</string>
    <!-- keep bytecode out of anything signed or version-controlled -->
    <key>PYTHONPYCACHEPREFIX</key><string>$HOME/Library/Caches/vigil</string>
$ROOTS_ENTRY
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/vigil-daemon.log</string>
  <key>StandardErrorPath</key><string>/tmp/vigil-daemon.log</string>
</dict>
</plist>
PLIST_EOF

pkill -f "\-m vigil" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$UID" "$PLIST"

echo "4/4  putting \`vigil\` on PATH"
mkdir -p "$(dirname "$SHIM")"
cat > "$SHIM" <<SHIM_EOF
#!/bin/bash
exec "$PYTHON" -m vigil "\$@"
SHIM_EOF
chmod +x "$SHIM"
# the shim needs the package importable from anywhere, not just the repo
printf '%s\n' "PYTHONPATH=$ROOT" >/dev/null
sed -i '' "2i\\
export PYTHONPATH=\"$RUNDIR:\${PYTHONPATH:-}\"; export PYTHONPYCACHEPREFIX=\"$HOME/Library/Caches/vigil\"
" "$SHIM"

sleep 3
echo
if curl -s -m 4 http://127.0.0.1:7717/api/state >/dev/null 2>&1; then
  echo "  daemon      running  (launchd, restarts itself, starts at login)"
else
  echo "  daemon      NOT reachable -- check /tmp/vigil-daemon.log"
fi
echo "  the Face    http://127.0.0.1:7717"
echo "  menu bar    open -a Vigil          (/Applications/Vigil.app)"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) echo "  terminal    vigil status" ;;
  *) echo "  terminal    vigil status   (add ~/.local/bin to PATH first)" ;;
esac
