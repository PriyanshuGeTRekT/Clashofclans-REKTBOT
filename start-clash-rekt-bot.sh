#!/bin/bash
# Linux: run ./start-clash-rekt-bot.sh to start Clash Rekt Bot (first run sets everything up).
cd "$(dirname "$0")" && exec bash launcher/bootstrap.sh "$@"
