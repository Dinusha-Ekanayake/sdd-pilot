"""Entry script for the launcher: puts the plugin root on sys.path, then runs the CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdd_pilot.__main__ import main  # noqa: E402

sys.exit(main())
