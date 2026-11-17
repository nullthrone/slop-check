"""Run the bundled slop-check engine: python scripts/slopcheck.py audit FILE."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slopcheck.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
