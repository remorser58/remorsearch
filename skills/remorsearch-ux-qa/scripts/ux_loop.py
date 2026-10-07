#!/usr/bin/env python3
"""Run the repository-local UX composition CLI without installing a package."""
from pathlib import Path
import sys

if sys.version_info < (3, 10):
    print("Python 3.10 or newer is required; found " + sys.version.split()[0], file=sys.stderr)
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uxloop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
