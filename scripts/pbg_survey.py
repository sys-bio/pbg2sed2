#!/usr/bin/env python3
"""Run the corpus survey (phase R1).  See `pbg2sed2.survey` for the options."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pbg2sed2.survey import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
