#!/usr/bin/env bash
set -euo pipefail

AUTO_YES=0
CODEX_METHOD="auto"
INSTALL_DIR="${CODEX_INSTALL_DIR:-$HOME/.local/bin}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Installs missing local dependencies required by ai_supervisor.

Options:
  --yes                 Non-interactive; approve install prompts.
  --codex-method MODE   MODE is one of: auto, binary, npm, skip.
  --install-dir DIR     Install Codex binary into DIR (default: ~/.local/bin).
  --help                Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      AUTO_YES=1
      shift
      ;;
    --codex-method)
      [[ $# -ge 2 ]] || { echo "missing value for --codex-method" >&2; exit 2; }
      CODEX_METHOD="$2"
      shift 2
      ;;
    --install-dir)
      [[ $# -ge 2 ]] || { echo "missing value for --install-dir" >&2; exit 2; }
      INSTALL_DIR="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

confirm() {
  local prompt="$1"
  if [[ "$AUTO_YES" -eq 1 ]]; then
    return 0
  fi
  while true; do
    read -r -p "$prompt [Y/n]: " reply
    reply="${reply,,}"
    case "$reply" in
      ""|y|yes) return 0 ;;
      n|no) return 1 ;;
      *) echo "Please answer yes or no." ;;
    esac
  done
}

platform() {
  uname -s | tr '[:upper:]' '[:lower:]'
}

architecture() {
  case "$(uname -m)" in
    x86_64|amd64) echo "x86_64" ;;
    aarch64|arm64) echo "aarch64" ;;
    *) return 1 ;;
  esac
}

need_cmd=()
for tool in git python3 codex; do
  if ! command_exists "$tool"; then
    need_cmd+=("$tool")
  fi
done

if [[ ${#need_cmd[@]} -eq 0 ]]; then
  echo "All required commands are already available: git, python3, codex"
  exit 0
fi

echo "Missing required commands: ${need_cmd[*]}"

if ! confirm "Install missing dependencies now?"; then
  echo "Skipping dependency installation." >&2
  exit 1
fi

detect_package_manager() {
  for pm in apt-get dnf yum pacman zypper apk brew; do
    if command_exists "$pm"; then
      echo "$pm"
      return 0
    fi
  done
  return 1
}

PACKAGE_MANAGER="$(detect_package_manager || true)"

as_root=()
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  if command_exists sudo; then
    as_root=(sudo)
  fi
fi

APT_UPDATED=0
install_os_packages() {
  local packages=("$@")
  if [[ ${#packages[@]} -eq 0 ]]; then
    return 0
  fi
  if [[ -z "$PACKAGE_MANAGER" ]]; then
    echo "No supported package manager was found on PATH." >&2
    return 1
  fi
  case "$PACKAGE_MANAGER" in
    apt-get)
      if [[ "$APT_UPDATED" -eq 0 ]]; then
        "${as_root[@]}" apt-get update
        APT_UPDATED=1
      fi
      "${as_root[@]}" apt-get install -y "${packages[@]}"
      ;;
    dnf)
      "${as_root[@]}" dnf install -y "${packages[@]}"
      ;;
    yum)
      "${as_root[@]}" yum install -y "${packages[@]}"
      ;;
    pacman)
      "${as_root[@]}" pacman -Sy --noconfirm "${packages[@]}"
      ;;
    zypper)
      "${as_root[@]}" zypper --non-interactive install --no-confirm "${packages[@]}"
      ;;
    apk)
      "${as_root[@]}" apk add --no-cache "${packages[@]}"
      ;;
    brew)
      brew install "${packages[@]}"
      ;;
    *)
      echo "Unsupported package manager: $PACKAGE_MANAGER" >&2
      return 1
      ;;
  esac
}

pkg_name_git() { echo "git"; }
pkg_name_python3() { echo "python3"; }
pkg_name_curl() { echo "curl"; }
pkg_name_tar() { echo "tar"; }
pkg_name_wget() { echo "wget"; }

pkg_names_node_npm() {
  case "$PACKAGE_MANAGER" in
    apt-get|yum|dnf|zypper) echo "nodejs npm" ;;
    pacman) echo "nodejs npm" ;;
    apk) echo "nodejs npm" ;;
    brew) echo "node" ;;
    *) echo "nodejs npm" ;;
  esac
}

ensure_base_tools() {
  local packages=()
  if ! command_exists git; then
    packages+=("$(pkg_name_git)")
  fi
  if ! command_exists python3; then
    packages+=("$(pkg_name_python3)")
  fi
  if [[ ${#packages[@]} -gt 0 ]]; then
    install_os_packages "${packages[@]}"
  fi
}

ensure_download_tools() {
  local packages=()
  if ! command_exists tar; then
    packages+=("$(pkg_name_tar)")
  fi
  if ! command_exists curl && ! command_exists wget; then
    packages+=("$(pkg_name_curl)")
  fi
  if [[ ${#packages[@]} -gt 0 ]]; then
    install_os_packages "${packages[@]}"
  fi
}

install_codex_binary() {
  [[ "$(platform)" == "linux" ]] || {
    echo "Binary install is only scripted for Linux right now." >&2
    return 1
  }

  local arch
  arch="$(architecture)" || {
    echo "Unsupported CPU architecture for automatic Codex binary install: $(uname -m)" >&2
    return 1
  }

  ensure_download_tools

  local asset="codex-${arch}-unknown-linux-musl.tar.gz"
  local url="https://github.com/openai/codex/releases/latest/download/${asset}"
  local tmpdir
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' RETURN

  echo "Downloading Codex CLI binary from ${url}"
  if command_exists curl; then
    curl -L "$url" -o "$tmpdir/$asset"
  else
    wget -O "$tmpdir/$asset" "$url"
  fi

  tar -xzf "$tmpdir/$asset" -C "$tmpdir"
  local extracted
  extracted="$(find "$tmpdir" -maxdepth 1 -type f -name 'codex*' ! -name '*.tar.gz' | head -n 1)"
  [[ -n "$extracted" ]] || {
    echo "Failed to locate extracted Codex binary." >&2
    return 1
  }

  mkdir -p "$INSTALL_DIR"
  cp "$extracted" "$INSTALL_DIR/codex"
  chmod +x "$INSTALL_DIR/codex"
  export PATH="$INSTALL_DIR:$PATH"
  echo "Installed Codex CLI to $INSTALL_DIR/codex"

  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
      echo "NOTICE: $INSTALL_DIR is not currently on PATH." >&2
      echo "Add this to your shell profile if needed:" >&2
      echo "  export PATH=\"$INSTALL_DIR:\$PATH\"" >&2
      ;;
  esac
}

install_codex_npm() {
  if ! command_exists npm; then
    read -r -a node_pkgs <<< "$(pkg_names_node_npm)"
    install_os_packages "${node_pkgs[@]}"
  fi
  command_exists npm || {
    echo "npm is still unavailable after attempted installation." >&2
    return 1
  }
  npm install -g @openai/codex
  local npm_prefix
  npm_prefix="$(npm prefix -g 2>/dev/null || true)"
  if [[ -n "$npm_prefix" && -d "$npm_prefix/bin" ]]; then
    export PATH="$npm_prefix/bin:$PATH"
  fi
}

choose_codex_method() {
  case "$CODEX_METHOD" in
    auto)
      if command_exists npm; then
        echo "binary"
      else
        echo "binary"
      fi
      ;;
    binary|npm|skip)
      echo "$CODEX_METHOD"
      ;;
    *)
      echo "Invalid --codex-method value: $CODEX_METHOD" >&2
      exit 2
      ;;
  esac
}

ensure_base_tools

if ! command_exists git || ! command_exists python3; then
  echo "Failed to install required base tools (git/python3)." >&2
  exit 1
fi

if ! command_exists codex; then
  method="$(choose_codex_method)"
  case "$method" in
    skip)
      echo "Skipping Codex installation by request." >&2
      ;;
    binary)
      install_codex_binary || {
        echo "Automatic Codex binary install failed." >&2
        exit 1
      }
      ;;
    npm)
      install_codex_npm || {
        echo "Automatic Codex npm install failed." >&2
        exit 1
      }
      ;;
  esac
fi

missing_after=()
for tool in git python3 codex; do
  if ! command_exists "$tool"; then
    missing_after+=("$tool")
  fi
done

if [[ ${#missing_after[@]} -gt 0 ]]; then
  echo "Still missing required commands after install attempt: ${missing_after[*]}" >&2
  exit 1
fi

echo "Dependencies satisfied."
