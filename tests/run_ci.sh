#!/usr/bin/env bash
# Local CI runner — mirrors .github/workflows/ci-validate.yml so you can verify a change
# before pushing. Run from the repo root:
#
#   bash tests/run_ci.sh
#
# Prereqs (one-off):  pip install ruff==0.5.5 black==24.4.2 yamllint==1.35.1 pytest
# See TESTING.md for what each check covers.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
run() { local name="$1"; shift; echo; echo "=== ${name} ==="; if "$@"; then echo "ok"; else echo "FAILED: $*"; fail=1; fi; }

run "ruff (lint)"             ruff check .
run "black (format check)"    black --check custom_components/ tests/
run "yamllint"                yamllint .
run "pytest — integration + add-on state + version" env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
run "pytest — pure engine core"  env PYTHONPATH=crop-steering-engine/src python -m pytest crop-steering-engine/tests -q

echo
if [ "${fail}" -eq 0 ]; then echo "ALL CHECKS PASSED"; else echo "SOME CHECKS FAILED — see above"; fi
exit "${fail}"
