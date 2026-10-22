#!/usr/bin/env bash
# Local CI runner. Runs every Validate job (.github/workflows/ci-validate.yml) that can run on a
# developer machine, and says plainly which ones it did not run and why. Run from the repo root:
#
#   bash tests/run_ci.sh                 # everything that can run here; a skipped CI check fails the run
#   bash tests/run_ci.sh --allow-skip    # accept a run with skips; still reported as PARTIAL
#   bash tests/run_ci.sh --containers    # also build the controller image and run tests_container (~25 min)
#   bash tests/run_ci.sh --no-browser    # skip the dashboard browser scripts (they need Chrome or Chromium)
#
# Prereqs (one-off):  pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1 pytest requests pyyaml
# Dashboard and MCP checks need Node 24 and installed dependencies (frontend/ and mcp-server/
# node_modules), from any package manager: the checks call the installed tools directly.
# See docs/TESTING.md for what each check covers, and for the ones that only run in CI.
set -uo pipefail
cd "$(dirname "$0")/.."

allow_skip=0
containers=0
browser=1
for arg in "$@"; do
  case "$arg" in
    --allow-skip) allow_skip=1 ;;
    --containers) containers=1 ;;
    --no-browser) browser=0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

fail=0
skipped=()
run() { local name="$1"; shift; echo; echo "=== ${name} ==="; if "$@"; then echo "ok"; else echo "FAILED: $*"; fail=1; fi; }
# A check CI runs that could have run here but did not: the run is PARTIAL.
skip() { echo; echo "=== $1 ==="; echo "SKIPPED: $2"; skipped+=("$1 -- $2"); }

# The pure engine ships twice: the tested source package and the copy vendored INTO the
# add-on image (what actually runs). They must stay byte-identical, or the tested code is
# not the shipped code.
engine_in_sync() {
  diff -r --exclude=__pycache__ \
    crop-steering-engine/src/crop_steering_engine \
    addons/f2_control/f2_control/crop_steering_engine
}

# Shipped code dirs must never be git-ignored (else new files vanish from releases), and
# no bytecode/cache may be tracked.
repo_hygiene() {
  local bad=0
  for p in custom_components/crop_steering/__init__.py www addons/f2_control/config.yaml; do
    if git check-ignore -q "$p" 2>/dev/null; then echo "IGNORED shipped path: $p"; bad=1; fi
  done
  if git ls-files 2>/dev/null | grep -E '__pycache__|\.pyc$|\.pytest_cache|\.ruff_cache' | head -1; then
    echo "tracked cache/bytecode files (should be gitignored)"; bad=1
  fi
  return $bad
}

# Doctrine pack: current, true of the code, lint-clean. The private word list is a CI secret, so
# a local run checks the public patterns only (the same thing a fork pull request gets).
doctrine_check() {
  python doctrine/tools/build_doctrine.py --check \
    --core crop-steering-engine/src/crop_steering_engine/core.py \
    --jev addons/f2_control/f2_control/brain/doctrine.py \
    --private-skip "local run: the private word list is a CI secret"
}

run "ruff (lint)"             ruff check .
run "black (format check)"    black --check custom_components/ tests/
run "yamllint"                yamllint .
run "engine vendored-copy in sync" engine_in_sync
run "repo hygiene (no ignored shipped paths / tracked caches)" repo_hygiene
run "doctrine pack current and lint-clean" doctrine_check
run "pytest — integration + health + services + state + version" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
run "pytest — add-on controller (real engine)" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q
run "pytest — pure engine core"  env PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

# The real-Home-Assistant tier (fresh install, the controller hand-off, seeded in-place upgrades;
# see docs/TESTING.md). It needs a full Home Assistant, so it is kept out of the lean
# prerequisites above:   pip install -r requirements-test-ha.txt      (Python 3.14.2+)
# Set HA_PYTHON to run it from a separate virtualenv, e.g. HA_PYTHON=~/ha-venv/bin/python.
# Home Assistant needs Linux: on Windows or macOS run the tier in Docker (docs/TESTING.md).
real_home_assistant() {
  local py="${HA_PYTHON:-python}"
  "$py" -m pytest tests_ha -q
}
if "${HA_PYTHON:-python}" -c "import pytest_homeassistant_custom_component" 2>/dev/null; then
  run "pytest — integration inside a real Home Assistant (production leg)" real_home_assistant
else
  skip "pytest — integration inside a real Home Assistant (production leg)" \
    "pytest-homeassistant-custom-component is not installed for '${HA_PYTHON:-python}'. Install it (or set HA_PYTHON), or use the Docker route in docs/TESTING.md."
fi

# Node: the dashboard job and the MCP job. These are the commands in frontend/package.json and
# mcp-server/package.json ("test", "build"), called on the installed tools so that no package
# manager has to be present (and none writes a lockfile into the tree). node_modules/.bin is
# the one place every package manager puts the tools.
frontend_test() { (cd frontend && node_modules/.bin/vitest run); }
frontend_build() {
  (cd frontend && node_modules/.bin/tsc --noEmit && node_modules/.bin/vite build && node scripts/package.mjs)
}
mcp_test() { (cd mcp-server && node_modules/.bin/tsc -p tsconfig.json && node --test tests/*.test.mjs); }
node_ready() { command -v node >/dev/null 2>&1 && [ -d "$1/node_modules" ]; }

# `tsc && vite build && package.mjs` rewrites the three committed dashboard bundles. They must come
# out identical to what is committed, so compare against what was there before the build.
bundle_paths="www custom_components/crop_steering/www addons/f2_control/www"
dashboard_bundle() {
  local before after
  before="$(git status --porcelain -- $bundle_paths)"
  frontend_build || return 1
  after="$(git status --porcelain -- $bundle_paths)"
  if [ "$before" != "$after" ]; then
    echo "The committed dashboard differs from a fresh build of frontend/src. Commit the rebuilt bundle."
    git status --short -- $bundle_paths
    return 1
  fi
  echo "Committed dashboard matches a fresh build."
}
# The scripts rewrite some tracked screenshots in img/ as they run (CI throws that away); say so
# rather than leave a dirty tree unexplained.
dashboard_browser_scripts() {
  local s before after
  before="$(git status --porcelain -- img)"
  for s in dashboard live workspace steering-visuals recipe-library tank-status calibration ha-shell; do
    echo "--- verify-$s"; node "frontend/scripts/verify-$s.mjs" || return 1
  done
  after="$(git status --porcelain -- img)"
  [ "$before" = "$after" ] || echo "NOTE: the browser scripts rewrote files in img/. Discard that with: git checkout -- img"
}

if node_ready frontend; then
  run "dashboard — unit tests (vitest)" frontend_test
  run "dashboard — build, and committed bundles equal a fresh build" dashboard_bundle
  if [ "$browser" -eq 0 ]; then
    skip "dashboard — browser workflows (verify-*.mjs)" "--no-browser was given."
  elif [ -d frontend/node_modules/playwright ] || [ -d frontend/node_modules/playwright-core ]; then
    run "dashboard — browser workflows (verify-*.mjs)" dashboard_browser_scripts
  else
    skip "dashboard — browser workflows (verify-*.mjs)" "Playwright is not installed in frontend/node_modules."
  fi
else
  skip "dashboard — unit tests, build, bundle identity, browser workflows" \
    "needs Node and frontend/node_modules (install: npm ci --prefix frontend)."
fi
if node_ready mcp-server; then
  run "MCP server — build and protocol tests" mcp_test
else
  skip "MCP server — build and protocol tests" "needs Node and mcp-server/node_modules (install: npm ci --prefix mcp-server)."
fi

# The controller image: built, then both install modes run against a fake Home Assistant. About 25
# minutes with Docker Desktop, so it is opt-in. This also proves the add-on Dockerfile builds.
controller_container() {
  local image=crop-steering-controller:test
  docker build -t "$image" addons/f2_control || return 1
  CONTROLLER_IMAGE="$image" python -m pytest tests_container -q -rs
}
if [ "$containers" -eq 0 ]; then
  skip "controller image build and container smoke (tests_container)" "takes about 25 minutes; pass --containers to run it."
elif command -v docker >/dev/null 2>&1; then
  run "controller image build and container smoke (tests_container)" controller_container
else
  skip "controller image build and container smoke (tests_container)" "Docker is not installed."
fi

# A run with a skipped CI check has not checked everything, so it never ends "ALL LOCAL CHECKS PASSED".
echo
if [ "${fail}" -ne 0 ]; then echo "SOME CHECKS FAILED — see above"; fi
if [ "${#skipped[@]}" -gt 0 ]; then
  echo "PARTIAL: CI runs these and this run did not:"
  for s in "${skipped[@]}"; do echo "  - $s"; done
  [ "${allow_skip}" -eq 1 ] || fail=1
elif [ "${fail}" -eq 0 ]; then
  echo "ALL LOCAL CHECKS PASSED"
fi
echo
echo "NOT RUN HERE, CI only (nothing in this script checks them):"
echo "  - Hassfest and the HACS action (container actions; hassfest route without Docker: docs/TESTING.md)"
echo "  - Real Home Assistant, oldest supported leg (HA 2024.10.0; local Docker route: docs/TESTING.md)"
echo "  - Add-on image per architecture: aarch64 and armv7 need QEMU (the amd64 build is in --containers)"
echo "  - Dependency review (needs GitHub's dependency graph; advisory)"
echo "  - The doctrine private word list (a CI secret)"
echo "  - Academy browser suites (tests/academy*.browser.mjs): no workflow runs them"
exit "${fail}"
