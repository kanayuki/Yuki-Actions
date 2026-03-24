"""Shared core library for all proxy pipelines (pac, merge, best).

Public API
----------
from core.models  import ParsedProxy, VerifyResult
from core.parse   import parse_link, link_to_clash, link_to_xray_outbound, link_to_singbox_outbound, health_key
from core.verify  import verify_links, filter_valid_links
from core.geo     import resolve_batch
from core.binary  import ensure_binary, BIN_DIR, update_all
"""
