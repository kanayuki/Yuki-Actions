import re
import sys
import requests
import base64
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

# Allow importing from proxy/ (parent directory)
_PROXY_DIR = BASE_DIR.parent
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))

from verify import filter_valid_links  # noqa: E402


def fetch_v2ray_links(sub_url: str) -> list[str]:
    """Fetch share links from a subscription URL (plain-text or base64)."""
    try:
        resp = requests.get(sub_url, timeout=15)
        resp.raise_for_status()

        text = resp.text.strip()
        # Detect base64-encoded content
        if re.match(r"^[a-zA-Z0-9+/=\n]+$", text):
            try:
                text = base64.b64decode(text).decode("utf-8")
            except Exception:
                pass

        return [line.strip() for line in text.splitlines() if line.strip()]

    except Exception as e:
        logger.warning("获取订阅失败 %s: %s", sub_url, e)
        return []


def main():
    subscribe_file = BASE_DIR / "subscribe_links.txt"
    if not subscribe_file.exists():
        subscribe_file.touch()

    merge_file = BASE_DIR / "merge_share_links_filter.txt"
    if not merge_file.exists():
        merge_file.touch()

    # Fetch links from all subscription URLs
    v2ray_links: list[str] = []
    for line in subscribe_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        v2ray_links.extend(fetch_v2ray_links(line))

    # Merge with existing cached links and deduplicate
    existing = [
        l for l in merge_file.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    all_links = list(dict.fromkeys(v2ray_links + existing))  # preserve order, deduplicate
    logger.info("去重后共 %d 条链接，开始验证…", len(all_links))
    print(f"去重后共 {len(all_links)} 条链接，开始验证连接…")

    # Verify real connectivity
    valid_links, results = filter_valid_links(all_links, timeout=5.0, concurrency=64)

    failed_count = len(all_links) - len(valid_links)
    print(f"验证完成：有效 {len(valid_links)} 条，失败/超时 {failed_count} 条")
    logger.info("验证完成：有效 %d 条，失败/超时 %d 条", len(valid_links), failed_count)

    # Save valid links sorted by latency
    valid_results = sorted(
        [r for r in results if r.valid],
        key=lambda r: r.latency_ms or float("inf"),
    )

    with open(merge_file, "w", encoding="utf-8") as f:
        for r in valid_results:
            f.write(r.link + "\n")

    logger.info("已保存 %d 条可用链接到 %s", len(valid_links), merge_file)
    print(f"已保存 {len(valid_links)} 条可用链接到 {merge_file}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
