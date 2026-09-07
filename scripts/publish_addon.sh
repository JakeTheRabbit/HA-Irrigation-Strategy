#!/usr/bin/env bash
# Default: prepare a tracked-only artifact for review; destination remains unchanged.
# Usage: scripts/publish_addon.sh [dedicated-clone] [--output new-artifact-dir]
#        scripts/publish_addon.sh [dedicated-clone] --apply prepared-artifact-dir
#        scripts/publish_addon.sh [dedicated-clone] --publish prepared-artifact-dir
# The Python tool verifies the dedicated repository and only touches f2_control/.
set -euo pipefail
MONO="$(cd "$(dirname "$0")/.." && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$MONO/scripts/prepare_addon_release.py" "$@"
else
  exec python "$MONO/scripts/prepare_addon_release.py" "$@"
fi
