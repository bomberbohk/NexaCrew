#!/bin/bash
# ============================================================
#  NexaCrew — Virtual Company AI Agent Platform
#  Fully automatic macOS installer: Xcode CLT, Homebrew,
#  Python, Node.js/npm, Git, VS Code, Codex CLI, Claude Code,
#  permissions (quarantine/executable), then launch.
#  Zero manual steps. Idempotent — safe to re-run.
#  Usage:  bash install_macos.sh
# ============================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
LOG="$HERE/install_macos.log"
: > "$LOG"
say() { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
run() { "$@" >>"$LOG" 2>&1; }

say "=============================================================="
say "  NexaCrew — fully automatic installation (macOS)"
say "  Log: $LOG"
say "=============================================================="

# ---- keep sudo alive for the whole run (single password prompt max;
#      none at all when the user has passwordless sudo / is admin) ----
if sudo -n true 2>/dev/null; then :; else
  say "[auth] Administrator privileges are needed once for system setup…"
  sudo -v
fi
( while true; do sudo -n true; sleep 50; done ) 2>/dev/null &
SUDO_KEEPALIVE=$!
trap 'kill $SUDO_KEEPALIVE 2>/dev/null' EXIT

# ---- [1/8] Xcode Command Line Tools (required by Homebrew) ----
say "[1/8] Xcode Command Line Tools…"
if ! xcode-select -p >/dev/null 2>&1; then
  # headless CLT install: create the trigger file and install the label
  touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
  CLT_LABEL=$(softwareupdate -l 2>/dev/null | grep -o 'Command Line Tools for Xcode-[0-9.]*' | tail -1)
  if [ -n "${CLT_LABEL:-}" ]; then
    run sudo softwareupdate -i "$CLT_LABEL" --verbose
  fi
  rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
fi
ok "Command Line Tools ready"

# ---- [2/8] Homebrew ----
say "[2/8] Homebrew…"
if ! command -v brew >/dev/null 2>&1; then
  export NONINTERACTIVE=1
  run /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
# put brew on PATH for this session AND permanently (Apple Silicon + Intel)
for BP in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$BP" ] && eval "$("$BP" shellenv)" && BREW="$BP" && break
done
for RC in "$HOME/.zprofile" "$HOME/.bash_profile"; do
  grep -q 'brew shellenv' "$RC" 2>/dev/null || echo "eval \"\$($BREW shellenv)\"" >> "$RC"
done
ok "Homebrew $(brew --version | head -1)"

# ---- [3/8] Python 3.12+ (strict: older versions are never used) ----
say "[3/8] Python 3.12+…"
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)' 2>/dev/null; then
  PY="$(command -v python3)"
elif command -v python3.12 >/dev/null 2>&1; then
  PY="$(command -v python3.12)"
fi
if [ -z "$PY" ]; then
  say "  Python 3.12+ not found — installing via Homebrew…"
  run brew install python@3.12
  run brew link --overwrite python@3.12 || true
  PY="$(brew --prefix)/opt/python@3.12/bin/python3.12"
  [ -x "$PY" ] || PY="$(command -v python3.12 || command -v python3)"
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)' || {
  echo "ERROR: could not obtain Python 3.12+ — see $LOG"; exit 1; }
ok "$("$PY" --version) — $PY"

# ---- [4/8] Node.js LTS + npm, Git ----
say "[4/8] Node.js + npm + Git…"
command -v node >/dev/null 2>&1 || run brew install node
command -v git  >/dev/null 2>&1 || run brew install git
ok "node $(node --version 2>/dev/null) · npm $(npm --version 2>/dev/null) · git $(git --version 2>/dev/null | cut -d' ' -f3)"

# ---- [5/8] Visual Studio Code ----
say "[5/8] Visual Studio Code…"
if ! command -v code >/dev/null 2>&1 && [ ! -d "/Applications/Visual Studio Code.app" ]; then
  run brew install --cask visual-studio-code
fi
# 'code' shell command on PATH
if ! command -v code >/dev/null 2>&1; then
  CODEBIN="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
  [ -x "$CODEBIN" ] && run sudo ln -sf "$CODEBIN" /usr/local/bin/code
fi
ok "VS Code ready"

# ---- [6/8] AI CLIs: Codex + Claude Code ----
say "[6/8] Codex CLI + Claude Code CLI…"
# global npm prefix in the user's home — no sudo needed for npm -g, ever
NPM_PREFIX="$HOME/.npm-global"
mkdir -p "$NPM_PREFIX"
npm config set prefix "$NPM_PREFIX" >>"$LOG" 2>&1
export PATH="$NPM_PREFIX/bin:$PATH"
for RC in "$HOME/.zprofile" "$HOME/.bash_profile"; do
  grep -q '.npm-global/bin' "$RC" 2>/dev/null || echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$RC"
done
run npm install -g @openai/codex
run npm install -g @anthropic-ai/claude-code
ok "codex: $(command -v codex || echo installed) · claude: $(command -v claude || echo installed)"

# ---- [7/8] permissions & security policy — all automatic ----
say "[7/8] Permissions & security policy…"
# 1. remove the quarantine attribute Gatekeeper puts on downloaded files
run xattr -dr com.apple.quarantine "$HERE" || true
# 2. every script in the program is executable
run find "$HERE" -name '*.sh' -exec chmod +x {} +
run chmod +x "$HERE/start.py"
# 3. user owns the whole tree (fixes copies made with sudo/AirDrop)
run sudo chown -R "$(id -un):$(id -gn)" "$HERE"
# 4. data dir writable
mkdir -p "$HERE/platform/data" && chmod -R u+rwX "$HERE/platform"
# 5. pre-authorize the application firewall for python (no popup later)
PYBIN="$PY"
FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
if [ -x "$FW" ] && [ -n "$PYBIN" ]; then
  run sudo "$FW" --add "$PYBIN" || true
  run sudo "$FW" --unblockapp "$PYBIN" || true
fi
ok "quarantine cleared · exec bits set · ownership fixed · firewall pre-authorized"

# ---- [8/8] launch with the verified Python 3.12+ interpreter ----
# Enterprise console wizard: SERVER/CLIENT role selection, automatic LAN
# server discovery, arrow-key block navigation. Hands over to start.py.
say "[8/8] Starting the deployment wizard…"
if [ -f "$HERE/install_wizard.py" ]; then
  exec "$PY" "$HERE/install_wizard.py"
fi
exec "$PY" "$HERE/start.py"
