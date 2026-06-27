#!/bin/sh
# Citadel bootstrap installer.
#
# Ensures Python 3.10+ and pipx are present — offering to install Python if it
# isn't — then installs the `citadel` CLI from PyPI. Runs without Python (it is
# the thing that puts Python there), so it's the entry point for a fresh machine.
#
#   curl -fsSL https://raw.githubusercontent.com/masumi-network/Citadel-Archive/main/install.sh | sh
#   # skip prompts:  ... | sh -s -- -y
#   # preview only:   ... | sh -s -- --dry-run

set -eu

PKG="citadel-archive"
ASSUME_YES=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    -n|--dry-run) DRY_RUN=1 ;;
    -h|--help) printf 'Usage: install.sh [-y|--yes] [-n|--dry-run]\n'; exit 0 ;;
    *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

say()  { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }
# Only ever called with our own literal command strings (no external input).
run()  { if [ "$DRY_RUN" = 1 ]; then say "  [dry-run] $*"; else eval "$*"; fi; }

# Prompt y/n on the real terminal even when this script is piped via `curl | sh`
# (where stdin is the script, not the user). No tty -> default to "no".
ask() {
  [ "$ASSUME_YES" = 1 ] && return 0
  # Try to open the controlling terminal; if it can't be opened (CI, no tty),
  # decline silently rather than auto-installing.
  if { printf '%s [y/N] ' "$1" > /dev/tty; } 2>/dev/null; then
    IFS= read -r ans < /dev/tty 2>/dev/null || ans=""
    case "$ans" in [Yy]|[Yy][Ee][Ss]) return 0 ;; esac
  fi
  return 1
}

PYTHON=""
detect_python() {
  for py in python3 python; do
    if have "$py" && "$py" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON="$py"
      return 0
    fi
  done
  return 1
}

install_python() {
  os="$(uname -s)"
  case "$os" in
    Darwin)
      if have brew; then run "brew install python@3.12"
      else warn "Homebrew not found. Install it from https://brew.sh (or Python 3.10+ from https://python.org), then re-run."; return 1; fi ;;
    Linux)
      if have apt-get; then run "sudo apt-get update" && run "sudo apt-get install -y python3 python3-pip python3-venv"
      elif have dnf; then run "sudo dnf install -y python3 python3-pip"
      elif have pacman; then run "sudo pacman -S --noconfirm python python-pip"
      else warn "No supported package manager (apt/dnf/pacman). Install Python 3.10+ manually."; return 1; fi ;;
    *)
      warn "Unsupported OS '$os'. Install Python 3.10+ from https://python.org, then re-run."; return 1 ;;
  esac
}

say "Citadel installer"

if ! detect_python; then
  say "Python 3.10+ is required but was not found on this system."
  if ask "Install Python now?"; then
    install_python || { warn "Could not install Python automatically — see the message above."; exit 1; }
    if [ "$DRY_RUN" != 1 ] && ! detect_python; then
      warn "Python still not found after install. Open a new shell and re-run this installer."
      exit 1
    fi
  else
    say "Okay — install Python 3.10+ yourself, then re-run this installer."
    exit 1
  fi
fi
if [ -n "$PYTHON" ]; then say "Using $("$PYTHON" --version 2>&1)"; else say "Using the freshly installed Python"; fi

if have pipx; then
  PIPX="pipx"
else
  say "Installing pipx…"
  run "${PYTHON:-python3} -m pip install --user pipx"
  run "${PYTHON:-python3} -m pipx ensurepath"
  PIPX="${PYTHON:-python3} -m pipx"
fi

say "Installing ${PKG}…"
run "$PIPX install $PKG"

if [ "$DRY_RUN" = 1 ]; then
  say ""
  say "  [dry-run] would show the citadel home screen here"
  exit 0
fi

# End on the brand: show the home screen if `citadel` is reachable this session.
CITADEL_BIN="$(command -v citadel 2>/dev/null || true)"
if [ -z "$CITADEL_BIN" ] && [ -x "$HOME/.local/bin/citadel" ]; then
  CITADEL_BIN="$HOME/.local/bin/citadel"
fi

say ""
if [ -n "$CITADEL_BIN" ]; then
  "$CITADEL_BIN" || true
  say ""
  say "Next:  citadel onboard     # set up this repo (token · hooks · MCP · capture)"
else
  say "Done. Open a new shell so your PATH updates, then run:"
  say "  citadel             # the home screen"
  say "  citadel onboard     # set up this repo"
fi
