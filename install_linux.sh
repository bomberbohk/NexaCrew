#!/bin/bash
# ============================================================
#  NexaCrew — Virtual Company AI Agent Platform
#  Fully automatic Linux installer: Python, Node.js/npm, Git,
#  VS Code, Codex CLI, Claude Code, permissions, firewall,
#  then launch.  Supports apt (Debian/Ubuntu), dnf (Fedora/RHEL),
#  pacman (Arch), zypper (openSUSE).  Zero manual steps.
#  Usage:  bash install_linux.sh
# ============================================================
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
LOG="$HERE/install_linux.log"
: > "$LOG"
say() { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[1;32m✔\033[0m %s\n' "$*"; }
run() { "$@" >>"$LOG" 2>&1; }

say "=============================================================="
say "  NexaCrew — fully automatic installation (Linux)"
say "  Log: $LOG"
say "=============================================================="

# ---- sudo keep-alive (one prompt max; none for root) ----
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
  if ! sudo -n true 2>/dev/null; then
    say "[auth] Administrator privileges are needed once for system setup…"
    sudo -v
  fi
  ( while true; do sudo -n true; sleep 50; done ) 2>/dev/null &
  SUDO_KEEPALIVE=$!
  trap 'kill $SUDO_KEEPALIVE 2>/dev/null' EXIT
fi

# ---- detect package manager ----
PM=""
for c in apt-get dnf pacman zypper; do command -v $c >/dev/null 2>&1 && PM=$c && break; done
[ -z "$PM" ] && { echo "No supported package manager (apt/dnf/pacman/zypper) found."; exit 1; }
say "[0/7] Package manager: $PM"

pkg_install() {  # install packages, non-interactive
  case "$PM" in
    apt-get) run $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf)     run $SUDO dnf install -y "$@" ;;
    pacman)  run $SUDO pacman -S --noconfirm --needed "$@" ;;
    zypper)  run $SUDO zypper --non-interactive install "$@" ;;
  esac
}

# ---- [1/7] refresh package index ----
say "[1/7] Updating package index…"
case "$PM" in
  apt-get) run $SUDO apt-get update -y ;;
  dnf)     run $SUDO dnf makecache ;;
  pacman)  run $SUDO pacman -Sy --noconfirm ;;
  zypper)  run $SUDO zypper --non-interactive refresh ;;
esac
ok "index updated"

# ---- [2/7] Python 3.12+ + venv + pip + build deps + camera/GL libs ----
say "[2/7] Python 3.12+ + system libraries…"
case "$PM" in
  apt-get) pkg_install python3 python3-venv python3-pip python3-dev curl git ca-certificates libgl1 libglib2.0-0t64 || pkg_install libglib2.0-0 ;;
  dnf)     pkg_install python3 python3-pip python3-devel curl git ca-certificates mesa-libGL glib2 ;;
  pacman)  pkg_install python python-pip curl git ca-certificates mesa glib2 ;;
  zypper)  pkg_install python3 python3-pip python3-devel curl git ca-certificates Mesa-libGL1 glib2 ;;
esac

# strict version gate: NEVER run the platform with anything below 3.12
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)' 2>/dev/null; }
PY=""
for c in python3 python3.13 python3.12; do
  command -v "$c" >/dev/null 2>&1 && py_ok "$(command -v $c)" && PY="$(command -v $c)" && break
done
if [ -z "$PY" ]; then
  say "  Python 3.12+ not found — installing automatically…"
  case "$PM" in
    apt-get)
      pkg_install python3.12 python3.12-venv python3.12-dev || true
      if ! command -v python3.12 >/dev/null 2>&1 && command -v lsb_release >/dev/null 2>&1 \
         && lsb_release -is 2>/dev/null | grep -qi ubuntu; then
        # Ubuntu with an older default python: deadsnakes PPA
        pkg_install software-properties-common
        run $SUDO add-apt-repository -y ppa:deadsnakes/ppa
        run $SUDO apt-get update -y
        pkg_install python3.12 python3.12-venv python3.12-dev
      fi ;;
    dnf)     pkg_install python3.12 python3.12-devel || pkg_install python3.12 ;;
    pacman)  pkg_install python ;;   # Arch's python is always current (>=3.12)
    zypper)  pkg_install python312 python312-pip python312-devel || pkg_install python312 ;;
  esac
  for c in python3.12 python3.13 python312 python3; do
    command -v "$c" >/dev/null 2>&1 && py_ok "$(command -v $c)" && PY="$(command -v $c)" && break
  done
fi
if [ -z "$PY" ]; then
  # last resort: Homebrew on Linux (works on any distro, no root needed)
  say "  Distro packages have no 3.12 — falling back to Homebrew…"
  if ! command -v brew >/dev/null 2>&1; then
    export NONINTERACTIVE=1
    run bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    [ -x /home/linuxbrew/.linuxbrew/bin/brew ] && eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
  fi
  run brew install python@3.12
  PY="$(brew --prefix 2>/dev/null)/opt/python@3.12/bin/python3.12"
  [ -x "$PY" ] || PY="$(command -v python3.12 || true)"
fi
[ -n "$PY" ] && py_ok "$PY" || { echo "ERROR: could not obtain Python 3.12+ — see $LOG"; exit 1; }
# make sure venv+pip work for the chosen interpreter
"$PY" -m ensurepip --upgrade >>"$LOG" 2>&1 || true
ok "$("$PY" --version) — $PY"

# ---- [3/7] Node.js LTS + npm (NodeSource for apt/dnf when repo too old) ----
say "[3/7] Node.js + npm…"
if ! command -v node >/dev/null 2>&1 || [ "$(node -e 'console.log(process.versions.node.split(".")[0])' 2>/dev/null || echo 0)" -lt 18 ]; then
  case "$PM" in
    apt-get)
      run bash -c "curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash -"
      pkg_install nodejs ;;
    dnf)
      run bash -c "curl -fsSL https://rpm.nodesource.com/setup_lts.x | $SUDO bash -"
      pkg_install nodejs ;;
    pacman)  pkg_install nodejs npm ;;
    zypper)  pkg_install nodejs20 npm20 || pkg_install nodejs npm ;;
  esac
fi
ok "node $(node --version 2>/dev/null) · npm $(npm --version 2>/dev/null)"

# ---- [4/7] Visual Studio Code ----
say "[4/7] Visual Studio Code…"
if ! command -v code >/dev/null 2>&1; then
  case "$PM" in
    apt-get)
      run bash -c "curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | $SUDO tee /usr/share/keyrings/ms-vscode.gpg >/dev/null"
      run bash -c "echo 'deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/ms-vscode.gpg] https://packages.microsoft.com/repos/code stable main' | $SUDO tee /etc/apt/sources.list.d/vscode.list"
      run $SUDO apt-get update -y
      pkg_install code ;;
    dnf)
      run $SUDO rpm --import https://packages.microsoft.com/keys/microsoft.asc
      run bash -c "printf '[code]\nname=VS Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\n' | $SUDO tee /etc/yum.repos.d/vscode.repo"
      pkg_install code ;;
    pacman)
      pkg_install code || run bash -c "command -v snap >/dev/null && $SUDO snap install code --classic" ;;
    zypper)
      run $SUDO rpm --import https://packages.microsoft.com/keys/microsoft.asc
      run $SUDO zypper --non-interactive addrepo -f https://packages.microsoft.com/yumrepos/vscode vscode || true
      pkg_install code ;;
  esac
fi
ok "VS Code: $(command -v code || echo 'installed')"

# ---- [5/7] AI CLIs: Codex + Claude Code (user-level npm, no sudo) ----
say "[5/7] Codex CLI + Claude Code CLI…"
NPM_PREFIX="$HOME/.npm-global"
mkdir -p "$NPM_PREFIX"
npm config set prefix "$NPM_PREFIX" >>"$LOG" 2>&1
export PATH="$NPM_PREFIX/bin:$PATH"
for RC in "$HOME/.bashrc" "$HOME/.profile"; do
  grep -q '.npm-global/bin' "$RC" 2>/dev/null || echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "$RC"
done
run npm install -g @openai/codex
run npm install -g @anthropic-ai/claude-code
ok "codex: $(command -v codex || echo installed) · claude: $(command -v claude || echo installed)"

# ---- [6/7] permissions & security policy — all automatic ----
say "[6/7] Permissions & firewall…"
run find "$HERE" -name '*.sh' -exec chmod +x {} +
run chmod +x "$HERE/start.py"
$SUDO chown -R "$(id -un):$(id -gn)" "$HERE" >>"$LOG" 2>&1 || true
mkdir -p "$HERE/platform/data" && chmod -R u+rwX "$HERE/platform"
# webcam permission for face capture (video group)
if getent group video >/dev/null 2>&1 && ! id -nG | grep -qw video; then
  run $SUDO usermod -aG video "$(id -un)" || true
fi
# open port 8600 on whichever firewall is active
if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q active; then
  run $SUDO ufw allow 8600/tcp
elif command -v firewall-cmd >/dev/null 2>&1 && $SUDO firewall-cmd --state >/dev/null 2>&1; then
  run $SUDO firewall-cmd --permanent --add-port=8600/tcp
  run $SUDO firewall-cmd --reload
fi
# SELinux: allow the app to bind/serve (Fedora/RHEL)
if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce 2>/dev/null)" = "Enforcing" ]; then
  run $SUDO setsebool -P httpd_can_network_connect 1 || true
fi
ok "exec bits · ownership · video group · firewall port 8600 · SELinux"

# ---- [7/7] launch with the verified Python 3.12+ interpreter ----
# Enterprise console wizard: SERVER/CLIENT role selection, automatic LAN
# server discovery, arrow-key block navigation. Hands over to start.py.
say "[7/7] Starting the deployment wizard…"
if [ -f "$HERE/install_wizard.py" ]; then
  exec "$PY" "$HERE/install_wizard.py"
fi
exec "$PY" "$HERE/start.py"
