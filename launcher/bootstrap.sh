#!/usr/bin/env bash
# Clash Rekt Bot launcher for macOS and Linux.
#
# First run: downloads uv (Astral's portable Python manager), Python 3.12 and the libraries in
# requirements.txt into .crb/ next to this app, plus Google's adb if none is found. Nothing is
# installed system-wide. Later runs start the app right away.
#
#   ./Start\ Clash\ Rekt\ Bot.command [--autostart] [--classic] [--repair]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRB="$ROOT/.crb"
VENV="$CRB/venv"
PY="$VENV/bin/python"
REQ="$ROOT/requirements.txt"
STAMP="$CRB/setup.stamp"
TOOLS="$ROOT/runtime/Tools"

say() { printf '  %s\n' "$*"; }
fail() {
  printf '\n  \033[31mSetup failed: %s\033[0m\n' "$*"
  say 'Check your internet connection and start Clash Rekt Bot again (or run it with --repair).'
  say 'See Troubleshooting in README.md.'
  read -r -p '  Press Enter to close ' _ || true
  exit 1
}

REPAIR=0
NOLAUNCH=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --repair) REPAIR=1 ;;
    --no-launch) NOLAUNCH=1 ;;
    *) ARGS+=("$a") ;;
  esac
done

printf '\n  \033[1mCLASH \033[31mREKT \033[33mBOT\033[0m\n\n'

case "$(uname -s)" in
  Darwin) UV_OS=apple-darwin; PT_OS=darwin ;;
  Linux)  UV_OS=unknown-linux-gnu; PT_OS=linux ;;
  *) fail "unsupported system $(uname -s)" ;;
esac
case "$(uname -m)" in
  arm64|aarch64) UV_ARCH=aarch64 ;;
  *) UV_ARCH=x86_64 ;;
esac

sha() { if command -v shasum >/dev/null; then shasum -a 256 "$1"; else sha256sum "$1"; fi | cut -d' ' -f1; }
fetch() { curl -fL --retry 3 -o "$2" "$1" || fail "download failed: $1"; }

# ---------------------------------------------------------------- Python + libraries
HASH="$(sha "$REQ")|$ROOT"
NEED=$REPAIR
[ -x "$PY" ] || NEED=1
[ "$NEED" = 1 ] || [ "$(cat "$STAMP" 2>/dev/null)" = "$HASH" ] || NEED=1
if [ "$NEED" = 0 ]; then
  "$PY" -c "import PySide6.QtWidgets, cv2, uiautomator2" 2>/dev/null || NEED=1
fi
if [ "$NEED" = 1 ]; then
  say 'First-time setup: downloading Python and the bot libraries (one time, a few minutes)...'
  mkdir -p "$CRB"
  UV="$CRB/uv/uv"
  if [ ! -x "$UV" ]; then
    say "Downloading uv ($UV_ARCH-$UV_OS)..."
    fetch "https://github.com/astral-sh/uv/releases/latest/download/uv-$UV_ARCH-$UV_OS.tar.gz" "$CRB/uv.tgz"
    mkdir -p "$CRB/uv"
    tar -xzf "$CRB/uv.tgz" -C "$CRB/uv" --strip-components 1 || fail 'could not unpack uv'
    rm -f "$CRB/uv.tgz"
  fi
  export UV_PYTHON_INSTALL_DIR="$CRB/python" UV_CACHE_DIR="$CRB/cache"
  rm -rf "$VENV"
  say 'Installing Python 3.12...'
  "$UV" venv "$VENV" --python 3.12 --python-preference only-managed --quiet || fail 'could not set up Python 3.12'
  say 'Installing the bot libraries...'
  "$UV" pip install --python "$PY" -r "$REQ" --quiet || fail 'could not install the libraries'
  echo "$HASH" > "$STAMP"
  "$UV" cache clean --quiet 2>/dev/null || true    # downloads are not needed any more
  say 'Python ready.'
fi

# ---------------------------------------------------------------- adb
if [ ! -x "$TOOLS/platform-tools/adb" ] && [ ! -x "$TOOLS/adb/adb" ] && ! command -v adb >/dev/null; then
  say "Downloading Google's Android platform-tools (adb)..."
  fetch "https://dl.google.com/android/repository/platform-tools-latest-$PT_OS.zip" "$CRB/pt.zip"
  unzip -oq "$CRB/pt.zip" -d "$TOOLS" || fail 'could not unpack platform-tools'
  rm -f "$CRB/pt.zip"
  say 'adb ready.'
fi

# ---------------------------------------------------------------- start
if [ "$NOLAUNCH" = 1 ]; then say 'Setup complete.'; exit 0; fi
cd "$ROOT"
say 'Starting Clash Rekt Bot...'
nohup "$PY" runtime/run_bot.py ${ARGS[@]+"${ARGS[@]}"} >/dev/null 2>&1 &
sleep 2
