#!/usr/bin/env python3
"""Create <skill>/.venv and install the pinned packages from requirements.lock. This is the ONLY step that downloads anything,
and it only runs when you run it. Uses `uv` if present, otherwise `python -m venv` + `pip`."""
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VENV = SKILL / ".venv"
LOCK = SKILL / "requirements.lock"


def run(cmd):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def main() -> int:
    if sys.version_info < (3, 12):
        sys.exit("Python 3.12 or newer is required (found %d.%d)" % sys.version_info[:2])
    if not LOCK.is_file():
        sys.exit("requirements.lock not found next to this skill")
    uv = shutil.which("uv")
    if uv:
        run([uv, "venv", "--python", sys.executable, str(VENV)])
        run([uv, "pip", "install", "--python", str(VENV / "bin" / "python"), "-r", str(LOCK)])
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
        run([str(VENV / "bin" / "python"), "-m", "pip", "install", "-r", str(LOCK)])
    run([str(VENV / "bin" / "python"), str(SKILL / "scripts" / "yuktiforge_viz.py"), "doctor"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
