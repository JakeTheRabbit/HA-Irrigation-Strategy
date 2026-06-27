#!/usr/bin/env bash
# Publish the f2-control add-on from this monorepo to the dedicated HA add-on repo
# (JakeTheRabbit/f2-control) so users can one-click install it by URL. Run on a release,
# AFTER bumping addons/f2_control/config.yaml `version:` (the version drives HA's Update).
#
# Usage: scripts/publish_addon.sh [path-to-local-clone-of-f2-control]
#   default clone path: ../f2-control (sibling of this monorepo)
set -euo pipefail

MONO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$MONO/addons/f2_control"
ADDON_REPO="${1:-$MONO/../f2-control}"

[ -d "$SRC" ] || { echo "add-on source not found: $SRC"; exit 1; }
if [ ! -d "$ADDON_REPO/.git" ]; then
  echo "No clone of JakeTheRabbit/f2-control at: $ADDON_REPO"
  echo "  git clone https://github.com/JakeTheRabbit/f2-control \"$ADDON_REPO\""
  exit 1
fi

VER=$(grep -oE 'version:[[:space:]]*"[^"]+"' "$SRC/config.yaml" | grep -oE '[0-9][^"]*')
echo "Syncing f2_control v$VER  ->  $ADDON_REPO/f2_control"

rm -rf "$ADDON_REPO/f2_control"
cp -r "$SRC" "$ADDON_REPO/f2_control"

cd "$ADDON_REPO"
git add -A
if git diff --cached --quiet; then echo "No changes to publish."; exit 0; fi
git commit -m "f2-control add-on v$VER (synced from monorepo)"
git push origin main
echo "Published v$VER to https://github.com/JakeTheRabbit/f2-control"
