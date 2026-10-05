"""Rebuild the single Priest sim canvas. New specs are added to the same file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_spec_canvas import write_all

if __name__ == "__main__":
    write_all()
