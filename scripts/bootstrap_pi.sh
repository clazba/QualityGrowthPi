#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="${QUANT_GPT_RUNTIME_ROOT:-$PROJECT_ROOT}"
LOG_FILE="$PROJECT_ROOT/logs/bootstrap.log"

mkdir -p "$PROJECT_ROOT/logs" "$RUNTIME_ROOT/data" "$RUNTIME_ROOT/state" "$RUNTIME_ROOT/results"
touch "$LOG_FILE"

log() {
  printf '%s | %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" | tee -a "$LOG_FILE"
}

confirm() {
  local prompt="$1"
  read -r -p "$prompt [y/N]: " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

check_arch() {
  local arch
  arch="$(uname -m)"
  if [[ "$arch" != "aarch64" && "$arch" != "arm64" ]]; then
    log "Warning: expected ARM64 target, found $arch"
  else
    log "Architecture check passed: $arch"
  fi
}

check_disk_and_ram() {
  local free_kb free_gb mem_mb
  free_kb="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')"
  free_gb="$(( free_kb / 1024 / 1024 ))"
  if command -v free >/dev/null 2>&1; then
    mem_mb="$(free -m | awk '/^Mem:/ {print $2}')"
  else
    mem_mb="unknown"
  fi
  log "Free disk on project volume: ${free_gb}GB"
  log "Detected system RAM: ${mem_mb}MB"
}

install_system_packages() {
  local packages
  packages=(build-essential python3 python3-venv python3-pip pipx sqlite3 jq)
  if command -v apt-get >/dev/null 2>&1; then
    if confirm "Install required system packages with sudo apt-get?"; then
      sudo apt-get update
      sudo apt-get install -y "${packages[@]}"
    else
      log "Skipped apt-get package installation"
    fi
  else
    log "apt-get not found; install packages manually if needed: ${packages[*]}"
  fi
}

install_python_environment() {
  local python_bin
  python_bin="$(command -v python3)"
  if [[ -z "$python_bin" ]]; then
    log "python3 is required but not installed"
    exit 1
  fi

  if [[ ! -d "$PROJECT_ROOT/.venv" ]]; then
    log "Creating virtual environment under $PROJECT_ROOT/.venv"
    "$python_bin" -m venv "$PROJECT_ROOT/.venv"
  fi

  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.venv/bin/activate"
  python -m pip install --upgrade pip wheel
  python -m pip install -r "$PROJECT_ROOT/requirements.txt"
}

install_cli_tools() {
  if ! command -v pipx >/dev/null 2>&1; then
    if confirm "Install pipx for isolated CLI tooling?"; then
      python3 -m pip install --user pipx
      python3 -m pipx ensurepath
    else
      log "Skipped pipx installation"
      return
    fi
  fi

  if ! command -v lean >/dev/null 2>&1; then
    if confirm "Install LEAN CLI with pipx?"; then
      pipx install lean
    else
      log "Skipped LEAN CLI installation"
    fi
  else
    log "LEAN CLI already installed"
  fi
}

main() {
  log "Bootstrap starting for $PROJECT_ROOT"
  log "Runtime root: $RUNTIME_ROOT"
  check_arch
  check_disk_and_ram
  install_system_packages
  install_python_environment
  install_cli_tools
  log "Bootstrap completed successfully"
}

main "$@"
