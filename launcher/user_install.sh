#!/usr/bin/env bash
# Clash Rekt Bot: start from a read-only install (macOS .app, Linux .deb).
#
#   user_install.sh <payload dir> <user dir> [--no-launch] [bot options]
#
# The app writes its settings, logs and downloaded Python next to itself, which /Applications (and an
# app Gatekeeper runs from a random read-only path) or /opt cannot hold. So the app files are copied
# into a per-user folder and run from there. Copying happens again only when the installed version
# changes; the user's settings, logs and downloads are never touched by an update.
set -euo pipefail

PAYLOAD="$1"; shift
TARGET="$1"; shift

if [ "$(cat "$TARGET/VERSION" 2>/dev/null)" != "$(cat "$PAYLOAD/VERSION")" ]; then
  printf '  Installing Clash Rekt Bot %s into %s\n' "$(cat "$PAYLOAD/VERSION")" "$TARGET"
  mkdir -p "$TARGET"
  if command -v rsync >/dev/null; then
    rsync -a --delete \
      --exclude '/.crb/' --exclude '/runtime/profiles/' --exclude '/runtime/logs/' \
      --exclude '/runtime/bot.config' --exclude '/runtime/Tools/platform-tools/' \
      --exclude '/runtime/treasureloot/' \
      "$PAYLOAD/" "$TARGET/"
  else
    # no rsync: copy over the top (user data folders are not in the payload, so they survive)
    cp -R "$PAYLOAD/." "$TARGET/"
  fi
  chmod +x "$TARGET/launcher/"*.sh "$TARGET/start-clash-rekt-bot.sh" "$TARGET/Start Clash Rekt Bot.command" 2>/dev/null || true
fi

exec bash "$TARGET/launcher/bootstrap.sh" "$@"
