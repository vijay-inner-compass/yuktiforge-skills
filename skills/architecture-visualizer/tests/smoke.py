#!/usr/bin/env python3
"""Smoke test for the installed skill: builds the bundled example and checks the outputs. Run:  python3 tests/smoke.py
(uses <skill>/.venv automatically if it exists). Exit 0 = the skill works on this machine."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENTRY = SKILL / "scripts" / "yuktiforge_viz.py"


def run(*args):
    return subprocess.run([sys.executable, str(ENTRY), *args], capture_output=True, text=True, timeout=300)


def main() -> int:
    d = run("doctor")
    print(d.stdout.strip())
    if d.returncode != 0:
        print(d.stderr.strip() or "doctor reported a problem")
        return d.returncode
    with tempfile.TemporaryDirectory() as out:
        r = run("build", "--model", str(SKILL / "examples" / "clinic.model.yaml"), "--view", "layered", "--out", out)
        if r.returncode != 0:
            print("build failed:", r.stderr.strip() or r.stdout.strip())
            return 1
        names = {p.name for p in Path(out).iterdir()}
        need = {"architecture.json", "diagram.dot", "diagram.svg", "validation.json"}
        if not need <= names:
            print("missing outputs:", sorted(need - names))
            return 1
        v = json.loads((Path(out) / "validation.json").read_text())
        print("outputs:", ", ".join(sorted(names)))
        print("validation result:", v.get("result"))
        return 0 if v.get("result") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
