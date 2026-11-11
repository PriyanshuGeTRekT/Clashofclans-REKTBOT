#!/bin/bash
# Double-click (macOS) to start Clash Rekt Bot. The first run sets everything up by itself.
cd "$(dirname "$0")" && exec bash launcher/bootstrap.sh "$@"
