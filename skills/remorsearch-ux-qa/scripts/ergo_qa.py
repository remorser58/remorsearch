#!/usr/bin/env python3
"""Ergonomic persona-swarm UX QA command line (see docs/ergonomic-swarm-spec.md)."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 10):
    print("Python 3.10 or newer is required; found " + sys.version.split()[0], file=sys.stderr)
    raise SystemExit(2)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ergoqa.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
