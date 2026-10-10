#!/usr/bin/env python3
"""Smoke test for the installed skill: scans the bundled example repository and checks the outputs against known facts. Run:  python3 tests/smoke.py
(uses <skill>/.venv automatically if it exists). Exit 0 = the skill works on this machine."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ENTRY = SKILL / "scripts" / "yuktiforge_docs.py"


def run(*args):
    return subprocess.run([sys.executable, str(ENTRY), *args], capture_output=True, text=True, timeout=300)


def main() -> int:
    d = run("doctor")
    print(d.stdout.strip())
    if d.returncode != 0:
        print(d.stderr.strip() or "doctor reported a problem")
        return d.returncode
    with tempfile.TemporaryDirectory() as out:
        r = run("scan", "--repo", str(SKILL / "examples" / "shop"), "--out", out)
        if r.returncode != 0:
            print("scan failed:", r.stderr.strip() or r.stdout.strip())
            return 1
        names = {p.name for p in Path(out).iterdir() if p.is_file()}
        need = {"repository-inventory.json", "symbol-index.json", "dependency-index.json", "coverage.json"}
        if not need <= names:
            print("missing outputs:", sorted(need - names))
            return 1
        routes = json.loads(run("query", "--scan", out, "--boundary", "http-route").stdout)
        got = sorted(row["name"] for row in routes["rows"])
        cov = json.loads((Path(out) / "coverage.json").read_text())
        print("routes:", got)
        print("unsupported languages:", [u["language"] for u in cov["unsupported_languages"]])
        ok = got == ["ANY /healthz", "GET /health", "POST /orders"] and [u["language"] for u in cov["unsupported_languages"]] == ["rust"] and cov["completeness"]["analysis"] == "complete"
        print("smoke:", "pass" if ok else "FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
