"""Best proxy pipeline — staged collection, verification, and ranking."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure proxy/ and proxy/best/ are in sys.path so that bare imports
# like ``from verify import parse_link`` and ``from util import console``
# work regardless of the entry point (CLI, GitHub Actions, direct import).
_BEST_DIR = Path(__file__).resolve().parent
_PROXY_DIR = _BEST_DIR.parent

for _p in (_PROXY_DIR, _BEST_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
