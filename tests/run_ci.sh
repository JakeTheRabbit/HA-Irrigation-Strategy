#!/usr/bin/env bash
# Local CI runner — mirrors .github/workflows/ci-validate.yml so you can verify a change
# before pushing. Run from the repo root:
#
#   bash tests/run_ci.sh
#
# Prereqs (one-off):  pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1 pytest requests pyyaml
# See docs/TESTING.md for what each check covers.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
run() { local name="$1"; shift; echo; echo "=== ${name} ==="; if "$@"; then echo "ok"; else echo "FAILED: $*"; fail=1; fi; }

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

run "ruff (lint)"             ruff check .
run "black (format check)"    black --check custom_components/ tests/
run "yamllint"                yamllint .
run "engine vendored-copy in sync" engine_in_sync
run "repo hygiene (no ignored shipped paths / tracked caches)" repo_hygiene
run "pytest — integration + health + services + state + version" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
run "pytest — add-on controller (real engine)" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q
run "pytest — pure engine core"  env PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

echo
if [ "${fail}" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED — see above"; fi
exit "${fail}"
