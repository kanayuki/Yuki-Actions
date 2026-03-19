import json
from pathlib import Path

import clash
import hysteria
import mieru
import singbox
import xray
from util import get_hash
from verify import filter_valid_links, parse_link, verify_links

path = Path(".")
keyfile = path / "share_link_keys.txt"
link_file = path / "share_links.txt"
health_file = path / "proxy" / "share_link_health.json"


def _health_key(link: str) -> str:
    """Stable identity across remark/date changes: sha256(protocol:host:port).
    Falls back to sha256(url_without_fragment) for unparseable links."""
    proxy = parse_link(link)
    if proxy:
        return get_hash(f"{proxy.protocol}:{proxy.host}:{proxy.port}")
    return get_hash(link.split("#")[0])


def _load_health() -> dict[str, int]:
    if health_file.exists():
        try:
            return json.loads(health_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_health(health: dict[str, int]) -> None:
    health_file.write_text(json.dumps(health, indent=2), encoding="utf-8")


def get_all_links() -> dict[str, str]:
    links = []
    links.extend(xray.get_all_links())
    links.extend(clash.get_all_links())
    links.extend(hysteria.get_all_links())
    links.extend(mieru.get_all_links())
    links.extend(singbox.get_all_links())
    return {k: link for k, link in links}


def update() -> None:
    # 1. 从上游获取最新链接（含今日 remark）
    new_link_dict = get_all_links()
    print(f"从配置源获取：{len(new_link_dict)} 条")

    # 2. 读取现有链接
    existing_links = (
        [l for l in link_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if link_file.exists()
        else []
    )
    print(f"现有链接：{len(existing_links)} 条")

    # 3. 合并去重：以 health_key(protocol:host:port) 为单位
    #    新链接覆盖旧链接（刷新 remark），上游没有的继续保留
    merged: dict[str, str] = {}
    for link in existing_links:
        merged[_health_key(link)] = link
    for url in new_link_dict.values():
        merged[_health_key(url)] = url  # 新版本覆盖（更新 remark）

    all_links = list(merged.values())
    print(f"合并去重后：{len(all_links)} 条，开始全量验证…")

    # 4. 全量验证真实连通性
    results = verify_links(all_links, timeout=5.0, concurrency=64)
    result_map = {r.link: r for r in results}

    # 5. 更新连续失败计数，决定取舍
    health = _load_health()
    kept_valid: list = []    # 本次验证通过，按延迟排序
    kept_pending: list[str] = []  # 失败但未满 3 次，暂时保留
    removed_count = 0

    for result in results:
        hk = _health_key(result.link)
        if result.valid:
            health[hk] = 0
            kept_valid.append(result)
        else:
            count = health.get(hk, 0) + 1
            health[hk] = count
            if count < 3:
                kept_pending.append(result.link)
            else:
                removed_count += 1
                health.pop(hk, None)  # 清除已移除节点的记录

    kept_valid.sort(key=lambda r: r.latency_ms or float("inf"))

    print(
        f"有效：{len(kept_valid)} 条  "
        f"等待确认（失败未满3次）：{len(kept_pending)} 条  "
        f"移除（连续失败≥3次）：{removed_count} 条"
    )

    # 6. 覆写 share_links.txt：有效链接（按延迟）在前，待观察链接在后
    with open(link_file, "w", encoding="utf-8") as f:
        for r in kept_valid:
            f.write(r.link + "\n")
        for link in kept_pending:
            f.write(link + "\n")

    # 7. 同步重写 keyfile，只保留存活链接的 key
    #    上游链接用原始 key，纯旧链接用 health_key 代替
    new_url_to_key = {url: k for k, url in new_link_dict.items()}
    kept_all = [r.link for r in kept_valid] + kept_pending
    surviving_keys = [new_url_to_key.get(link, _health_key(link)) for link in kept_all]
    with open(keyfile, "w", encoding="utf-8") as f:
        f.write("\n".join(surviving_keys) + "\n")

    # 8. 持久化 health 数据
    _save_health(health)
    print(f"共保留 {len(kept_all)} 条链接")


def main() -> None:
    update()


if __name__ == "__main__":
    main()
