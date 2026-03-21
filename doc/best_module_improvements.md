# best 模块改进意见

> 基于对 `proxy/best/` 全部源码的详细审查，共发现 8 类问题，按优先级排序。

---

## 1. 双重网络请求（性能缺陷，高优先级）

**文件**: `proxy/best/collect.py`

**问题**: `_scan_all_repos` 先调用 `_fetch_url` 检查 URL 是否含代理链接，但只记录了 URL、没有保存内容。后续的 `_fetch_and_extract` 又对同一批 URL 重新发起 HTTP 请求。每个有效 URL **被下载了两次**，浪费带宽和时间。

```python
# 当前流程（简化）:
# 1. _scan_all_repos → _check_raw_url → _fetch_url(url)  # 只看内容是否包含协议前缀
# 2. collect → _fetch_and_extract → _fetch_url(url)      # 重新下载同一个 URL
```

**建议**: 让 `_check_raw_url` 返回内容本身，并在 `collect` 中直接用缓存内容，跳过第二次下载：

```python
def _check_raw_url(url: str, full_name: str) -> tuple[str, str, str] | None:
    """返回 (url, repo, content) 或 None。"""
    text = _fetch_url(url, timeout=4)
    if not text or len(text) < 10:
        return None
    decoded = _decode_content(text)
    if any(s in decoded for s in _KNOWN_SCHEMES):
        return (url, full_name, text)   # ← 顺带返回已下载的内容
    return None
```

预计可将 `collect` 阶段的网络请求量减少约 50%。

---

## 2. 跨模块代码重复（可维护性，高优先级）

### 2a. `_headers()` 重复定义

`discover.py:30` 和 `collect.py:47` 中各定义了完全相同的 `_headers()` 函数。

**建议**: 提取到公共模块（例如 `proxy/best/github.py` 或直接放入 `collect.py` 并在 `discover.py` 中 import）：

```python
# proxy/best/_github.py
def github_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {token}"
    return h
```

### 2b. `_health_key` 逻辑重复

`collect.py:61` 的 `_health_key(link)` 与 `checker.py:39` 的 `_health_key_from_link(link)` 实现完全相同。

**建议**: 统一放入 `state.py` 或新建 `proxy/best/utils.py`，供两处 import：

```python
# proxy/best/utils.py
def health_key(link: str) -> str:
    """计算代理链接的稳定身份标识 sha256(protocol:host:port)。"""
    from verify import parse_link
    proxy = parse_link(link)
    if proxy is None:
        return hashlib.sha256(link.encode()).hexdigest()
    return hashlib.sha256(f"{proxy.protocol}:{proxy.host}:{proxy.port}".encode()).hexdigest()
```

### 2c. 时间戳解析重复

`checker.py:69-77` 和 `maintain.py:49-57` 各自实现了相同的 `datetime.fromisoformat + tzinfo 补全` 逻辑。

**建议**: 提取为公共函数：

```python
def parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
```

---

## 3. 安全问题（安全，高优先级）

### 3a. SSL 验证被禁用

**文件**: `collect.py:106`

```python
_session.verify = False   # ← 禁用了所有 HTTPS 证书验证
```

这会使 `collect` 阶段的所有 HTTPS 请求易受中间人攻击。禁用 SSL 通常是为了绕过自签名证书，但对 GitHub raw 内容这样的公共 CDN 完全没有必要。

**建议**: 移除 `verify = False`，保持默认（`True`）。如果确实存在需要绕过 SSL 的特殊域名，改为按需处理，而非全局禁用。

### 3b. GeoIP 查询使用 HTTP

**文件**: `geo.py:16-17`

```python
_BATCH_URL = "http://ip-api.com/batch"    # ← 明文 HTTP
_SINGLE_URL = "http://ip-api.com/json/{}" # ← 明文 HTTP
```

ip-api.com 的免费 API 不支持 HTTPS（需付费），这是客观限制。但建议在代码中加注释说明原因，避免被误认为是遗漏：

```python
# ip-api.com 免费套餐不支持 HTTPS，需使用 HTTP
_BATCH_URL = "http://ip-api.com/batch"
```

---

## 4. 硬编码的配置项（可配置性，中优先级）

**文件**: `maintain.py:53`

```python
if age_days > 7:    # ← "7天" 硬编码，无法通过配置调整
    stale_keys.append(hk)
```

`max_consecutive_failures`、`repo_blacklist_after` 等类似的阈值都已正确放入 `Config`，唯独这个 stale 阈值没有。

**建议**: 在 `Config` 中添加：

```python
# proxy/best/config.py
class Config(BaseModel):
    ...
    stale_days: int = 7   # 超过此天数未验证的链接视为过期并移除
```

并在 `maintain.py` 中引用：

```python
if age_days > cfg.stale_days:
```

---

## 5. 死代码（可维护性，中优先级）

**文件**: `collect.py:124-129`

```python
def _list_repo_dir(owner: str, repo: str, path: str = "") -> list[dict]:
    url = f"{_API}/repos/{owner}/{repo}/contents/{path}"
    data = requests.get(url, headers=_headers(), timeout=15)
    if data.ok and isinstance(data.json(), list):
        return data.json()
    return []
```

此函数在整个模块中**从未被调用**（`_scan_all_repos` 采用的是直接探测 raw URL 的方式，不使用 GitHub Contents API）。

**建议**: 直接删除，或明确注释"保留备用"。额外注意：该函数在遇到网络异常时没有 try/except，与模块其他函数风格不一致，若未来需要启用需先补充异常处理。

---

## 6. GeoIP 单查询缺少速率限制（健壮性，中优先级）

**文件**: `geo.py:77-86`

批量查询（`/batch`）在批次间有 `time.sleep(4)` 的速率保护，但单查询回退路径（`_single_query`）完全没有：

```python
# 批量失败时循环调用 _single_query，没有任何 sleep：
for h in chunk:
    result[h] = _single_query(h)   # ← 可能在几秒内发出 100 个请求
```

ip-api.com 的免费单查询限制为 45 次/分钟。密集调用会导致 429 并返回大量 "XX"（未知地区）。

**建议**: 在单查询循环中加入速率控制：

```python
for i, h in enumerate(chunk):
    result[h] = _single_query(h)
    if i < len(chunk) - 1:
        time.sleep(1.5)  # ~40 req/min，低于 45/min 限制
```

或改用 `time.sleep` 在每次批次失败后等待再重试整个批次。

---

## 7. latency_history 使用列表切片（效率，低优先级）

**文件**: `checker.py:183-185`

```python
entry.latency_history.append(r.latency_ms)
if len(entry.latency_history) > 5:
    entry.latency_history = entry.latency_history[-5:]  # ← 每次都创建新列表
```

在大量链接的情况下，每次都创建新列表有额外开销。

**建议**: 使用 `collections.deque(maxlen=5)` 作为 `latency_history` 的内部类型，但由于 Pydantic 序列化需要 `list`，可在处理时进行转换，或直接保持现状（数量小时影响可忽略不计，当前实现简单清晰）。若链接量超过 10 万时再考虑优化。

---

## 8. 缺少单元测试（质量保障，低优先级）

整个 `best` 模块（约 3400 行）没有任何单元测试。以下逻辑尤其适合测试：

| 函数 | 测试重点 |
|------|----------|
| `_extract_links` | base64 内容解码、混合内容提取 |
| `_health_key` | 相同 host:port 不同参数生成相同 key |
| `_stale_health_items` | 边界时间条件 |
| `maintain` 的 blacklist 逻辑 | streak 计数、用户 repo 豁免 |
| `rank` 的合并小国逻辑 | OTHER 合并、XX 处理 |

**建议**: 创建 `proxy/best/tests/` 目录，使用 `pytest` 对纯函数编写参数化测试。对需要网络的函数用 `unittest.mock.patch` 隔离。

---

## 总结

| 优先级 | 问题 | 预计收益 |
|--------|------|----------|
| 🔴 高 | 双重网络请求 | 减少 ~50% collect 流量和时间 |
| 🔴 高 | 代码重复（3处） | 降低维护成本，减少 bug 面 |
| 🔴 高 | SSL verify=False | 消除中间人攻击风险 |
| 🟡 中 | stale_days 硬编码 | 提升可配置性 |
| 🟡 中 | 死代码 `_list_repo_dir` | 减少误导 |
| 🟡 中 | GeoIP 单查询无速率限制 | 避免被封，提高地区识别准确率 |
| 🟢 低 | latency_history 效率 | 微优化，量小时可忽略 |
| 🟢 低 | 缺少单元测试 | 长期质量保障 |
