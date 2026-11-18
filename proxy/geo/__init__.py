"""IP 地理位置模块。

Public API
----------
from geo.cache import load_cache, save_cache, resolve
from geo.resolver import get_country_code
"""

from __future__ import annotations

from .cache import load_cache, resolve, save_cache
from .resolver import get_country_code