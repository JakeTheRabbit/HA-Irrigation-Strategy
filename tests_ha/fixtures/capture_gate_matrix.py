"""Write gate_matrix_12c6d1a.json: the kill switch every seeded room ended up with on 12c6d1a.

tests_ha/test_gate_matrix.py compares this code with that table. The table is recorded, never
hand-written: this script exports the 12c6d1a tree (the controller and the integration as they were
before the gate had one rule per layer), lays this checkout's tests_ha/ over it (the test file, the
harness and the seeded rooms), and runs the matrix there in record mode, where the test reads the
gate the old way (`room.enable_flag` after the first setup pass; health._kill_switch).

    python tests_ha/fixtures/capture_gate_matrix.py              # from the repository root
    python tests_ha/fixtures/capture_gate_matrix.py --old-tree DIR   # DIR already holds 12c6d1a

It needs what tests_ha needs (requirements-test-ha.txt) and, without --old-tree, git.
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE = Path(__file__).resolve().parent / "gate_matrix_12c6d1a.json"
REF = "12c6d1a"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old-tree", help=f"a tree already holding {REF}")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as scratch:
        old = Path(args.old_tree) if args.old_tree else Path(scratch) / "old"
        if not args.old_tree:
            archive = subprocess.run(["git", "archive", REF], cwd=ROOT, check=True, capture_output=True).stdout
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(old, filter="data")
        work = Path(scratch) / "work"
        shutil.copytree(old, work, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "tests_ha", work / "tests_ha", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        out = Path(scratch) / "table.json"
        env = dict(os.environ, GATE_MATRIX_RECORD=str(out))
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "tests_ha/test_gate_matrix.py", "-q", "-p", "no:cacheprovider"],
            cwd=work, env=env,
        )
        if done.returncode:
            return done.returncode
        TABLE.write_text(out.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print(f"wrote {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
