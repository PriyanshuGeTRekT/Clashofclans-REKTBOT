#!/usr/bin/env bash
# Clash Rekt Bot: start from a read-only install (macOS .app, Linux .deb).
#
#   user_install.sh <payload dir> <user dir> [--no-launch] [bot options]
#
# The app writes its settings, logs and downloaded Python next to itself, which /Applications (and an
# app Gatekeeper runs from a random read-only path) or /opt cannot hold. So the app files are copied
# into a per-user folder and run from there. They are copied again only when a different .app/.deb
# was installed: the app also updates itself inside the user folder (source/updates), and the older
# bundle it was first installed from must not undo that. The user's settings, logs, downloads, own
# attack scripts and re-learned button pictures are never touched.
set -euo pipefail

PAYLOAD="$1"; shift
TARGET="$1"; shift

PV="$(cat "$PAYLOAD/VERSION")"
SYNCED="$(cat "$TARGET/.crb/payload_version" 2>/dev/null || true)"

if [ ! -f "$TARGET/VERSION" ] || [ "$SYNCED" != "$PV" ]; then
  printf '  Installing Clash Rekt Bot %s into %s\n' "$PV" "$TARGET"
  mkdir -p "$TARGET"
  PY="$TARGET/.crb/venv/bin/python"
  done_by_engine=0
  if [ -x "$PY" ] && [ -f "$TARGET/app_manifest.json" ] && [ -f "$PAYLOAD/app_manifest.json" ]; then
    # an update over an installed copy: keep what this computer changed (see source/updates/engine.py)
    if "$PY" -I "$PAYLOAD/source/updates/engine.py" install-dir --source "$PAYLOAD" --root "$TARGET"; then
      done_by_engine=1
    fi
  fi
  if [ "$done_by_engine" = 0 ]; then
    if command -v rsync >/dev/null; then
      rsync -a --delete \
        --exclude '/.crb/' --exclude '/runtime/profiles/' --exclude '/runtime/logs/' \
        --exclude '/runtime/bot.config' --exclude '/runtime/Tools/platform-tools/' \
        --exclude '/runtime/treasureloot/' --exclude '/runtime/instances/' \
        --filter 'P /runtime/CSV/**' --filter 'P /runtime/templates/**' \
        "$PAYLOAD/" "$TARGET/"
    else
      # no rsync: copy over the top (user data folders are not in the payload, so they survive)
      cp -R "$PAYLOAD/." "$TARGET/"
    fi
  fi
  chmod +x "$TARGET/launcher/"*.sh "$TARGET/start-clash-rekt-bot.sh" "$TARGET/Start Clash Rekt Bot.command" 2>/dev/null || true
  mkdir -p "$TARGET/.crb"
  printf '%s\n' "$PV" > "$TARGET/.crb/payload_version"
fi

exec bash "$TARGET/launcher/bootstrap.sh" "$@"
