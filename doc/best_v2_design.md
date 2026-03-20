# Best V2 — 分阶段代理收集与验证系统

## 目标

持续累积、验证、分类全球免费代理节点。支持 Linux / Windows / macOS，分阶段分频率运行，避免每次从头执行。

---

## 1. 流水线总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Scheduler (cron / CI)                        │
│                                                                     │
│  Stage 1: discover    ──── 每 12h ──── GitHub 搜索 + 用户仓库       │
│  Stage 2: collect     ──── 每  2h ──── 从仓库提取订阅/分享链接      │
│  Stage 3: verify      ──── 每 10min ── 取 500 条待验证，真连接检测   │
│  Stage 4: rank        ──── verify 后 ─ 排序分国家 + 生成 best.txt   │
│  Stage 5: maintain    ──── 每 24h ──── 清理死链 + 评估仓库质量       │
└─────────────────────────────────────────────────────────────────────┘
```

每个 Stage **独立可运行**，通过文件系统交换数据，中间状态持久化到 JSON。
可以单独跑 `python -m best discover`，也可以 `python -m best run` 全量执行。

---

## 2. 文件结构

```
proxy/best/
├── __init__.py
├── __main__.py            # CLI 入口: python -m best discover|collect|verify|rank|maintain|run
├── config.yaml            # 统一配置
├── discover.py            # Stage 1: GitHub 仓库搜索
├── collect.py             # Stage 2: 链接提取
├── verify.py              # Stage 3: 真连接检测
├── rank.py                # Stage 4: 排序 + 国家分类
├── maintain.py            # Stage 5: 清理 + 仓库评估
├── engine/                # 检测引擎抽象
│   ├── __init__.py        # TestEngine ABC + auto_select()
│   ├── xray.py            # xray-core 引擎
│   ├── singbox.py         # sing-box 引擎
│   ├── mihomo.py          # mihomo 引擎 (改造自现有)
│   └── tcp.py             # TCP fallback (改造自现有 verify.py)
├── geo.py                 # GeoIP 批量查询 + 缓存
├── state.py               # 状态管理 (读写 JSON 持久化文件)
└── data/                  # 运行时持久化数据 (git-ignored)
    ├── repo_scores.json   # 仓库质量评分
    ├── link_health.json   # 链接健康状态
    └── verify_queue.json  # 待验证队列 (分批消费)

proxy/
├── repositories.txt       # Stage 1 输出: 发现的仓库列表
├── collections.txt        # Stage 2 输出: 提取的原始分享链接
├── available.txt          # Stage 3 输出: 验证通过的链接
├── best.txt               # Stage 4 输出: 精选 top N
├── country/               # Stage 4 输出: 按国家分类
│   ├── JP.txt
│   ├── US.txt
│   ├── KR.txt
│   ├── TW.txt
│   ├── SG.txt
│   ├── ...
│   └── OTHER.txt          # 数量 < min_country_size 的国家合并
└── logs/
    └── best.log           # 7 天滚动
```

---

## 3. 配置 (`config.yaml`)

```yaml
# ── 仓库来源 ──
user_repos:                          # 用户指定的仓库 (永不自动排除)
  - owner/repo-name
  - owner2/repo-name2

search_queries:                      # GitHub 搜索关键词
  - "v2ray free nodes subscribe"
  - "free vmess vless subscription stars:>50"
  - "clash free proxy nodes stars:>20"
  - "v2ray free subscribe pushed:>{recent_7d}"   # {recent_7d} 运行时替换

max_search_repos: 20                 # 自动搜索的最大仓库数

# ── 验证 ──
test_engine: auto                    # auto | xray | singbox | mihomo | tcp
  # auto 优先级: xray → singbox → mihomo → tcp
test_timeout_ms: 6000                # 单节点超时
test_concurrency: 50                 # 并发数
test_url: "http://www.gstatic.com/generate_204"
batch_size: 500                      # 每次验证批量大小

# ── 健康管理 ──
max_consecutive_failures: 3          # 连续失败 N 次后移除
health_recheck_interval_min: 60      # 已验证节点多久重新检查 (分钟)

# ── 仓库质量 ──
repo_min_valid_ratio: 0.05           # 有效率 < 5% 连续 3 次 → 自动排除
repo_blacklist_after: 3              # 连续低质量 N 次后加入黑名单

# ── 输出 ──
top_n: 100                           # best.txt 保留数量
country_pool_max: 100                # 每国家池上限
min_country_size: 10                 # 低于此数量的国家合并到 OTHER.txt

# ── 二进制路径 (可选, 不填则自动检测 PATH / 自动下载) ──
# xray_bin: /usr/local/bin/xray
# singbox_bin: /usr/local/bin/sing-box
# mihomo_bin: /tmp/mihomo-bin/mihomo

# ── 调度频率 (仅供 CI/cron 参考, 脚本本身不循环) ──
schedule:
  discover:  "0 */12 * * *"          # 每 12 小时
  collect:   "0 */2 * * *"           # 每 2 小时
  verify:    "*/10 * * * *"          # 每 10 分钟
  maintain:  "0 4 * * *"             # 每天凌晨 4 点
```

---

## 4. 各 Stage 详细设计

### Stage 1: Discover (每 12h)

**输入**: `config.yaml` (user_repos + search_queries)
**输出**: `repositories.txt`, `data/repo_scores.json`

```
1. 读取 user_repos → 固定列表
2. GitHub Search API 搜索仓库:
   - 按 stars 降序
   - 过滤: pushed > 7天前, stars > 20, 非 fork
   - 排除 repo_scores.json 中已 blacklisted 的仓库
3. 合并去重 → repositories.txt (格式: owner/repo 每行一个)
4. 为新发现的仓库初始化 repo_scores.json 条目
```

**repo_scores.json 结构**:
```json
{
  "owner/repo": {
    "source": "search",        // "user" | "search"
    "stars": 1200,
    "last_seen": "2026-03-19",
    "valid_ratio_history": [0.35, 0.28, 0.31],  // 最近 N 次有效率
    "low_quality_streak": 0,   // 连续低质量次数
    "blacklisted": false,
    "total_links_contributed": 450,
    "total_valid_contributed": 142
  }
}
```

### Stage 2: Collect (每 2h)

**输入**: `repositories.txt`
**输出**: `collections.txt`, `data/verify_queue.json`

```
1. 读取 repositories.txt 中所有仓库
2. 对每个仓库:
   a. Contents API 扫描根目录 + 常见子目录 (/, /sub, /node, /subscribe)
   b. 识别订阅文件: *.txt, *.yaml, *.yml, README.md 中的 raw 链接
   c. 也检查 GitHub Releases (有些仓库把订阅放在 release assets 里)
   d. 下载文件内容, base64 解码 (如需要), 提取分享链接
   e. 记录 link → repo 映射 (用于仓库质量追踪)
3. 与现有 collections.txt 合并, 按 health_key 去重
4. 新链接追加到 verify_queue.json (FIFO 队列)
```

**verify_queue.json 结构**:
```json
{
  "queue": [
    {
      "link": "vmess://...",
      "health_key": "sha256hex",
      "source_repo": "owner/repo",
      "enqueued_at": "2026-03-19T12:00:00Z",
      "priority": 1         // 1=新链接, 2=定期重检
    }
  ]
}
```

### Stage 3: Verify (每 10min, 批量 500)

**输入**: `data/verify_queue.json` + `data/link_health.json` (重检到期的)
**输出**: `available.txt`, 更新 `data/link_health.json`

```
1. 从 verify_queue.json 取最多 batch_size(500) 条:
   a. 优先取 priority=1 (新链接)
   b. 其次取 priority=2 (重检到期的旧链接)
   c. 如果队列为空, 从 link_health.json 中选
      last_verified 超过 health_recheck_interval 的存量链接加入
2. 选择检测引擎 (auto: xray → singbox → mihomo → tcp)
3. 批量真连接检测:
   a. 生成引擎配置 (所有 500 条)
   b. 启动引擎进程
   c. 逐个/并发测试延迟
   d. 收集结果
4. 更新 link_health.json:
   - 成功: fail_count=0, last_ok=now, 记录 latency
   - 失败: fail_count += 1
   - 首次成功的新链接: 查询 GeoIP → 记录 country
5. 从队列中移除已处理的条目
6. 重新生成 available.txt = link_health.json 中所有 fail_count=0 的链接
```

**link_health.json 结构**:
```json
{
  "sha256hex_of_proto:host:port": {
    "link": "vmess://...",
    "protocol": "vmess",
    "host": "1.2.3.4",
    "port": 443,
    "country": "JP",
    "source_repo": "owner/repo",
    "fail_count": 0,
    "last_verified": "2026-03-19T12:10:00Z",
    "last_ok": "2026-03-19T12:10:00Z",
    "latency_ms": 234,
    "latency_history": [234, 256, 221],   // 最近 5 次
    "first_seen": "2026-03-15T00:00:00Z"
  }
}
```

### Stage 4: Rank (verify 完成后自动触发)

**输入**: `data/link_health.json`
**输出**: `best.txt`, `country/*.txt`

```
1. 读取 link_health.json, 过滤 fail_count == 0
2. 按国家分组:
   a. 每个国家按 avg_latency 排序
   b. 每国保留 country_pool_max (100) 条
   c. 国家节点数 < min_country_size (10) → 合并到 OTHER
3. 写入 country/*.txt (每个文件: 分享链接, 按延迟排序)
4. 从所有国家池中, 按延迟全局 top_n → best.txt
5. 输出 rich 汇总面板:
   - 各国家节点数
   - 平均延迟
   - 新增/移除数量
```

### Stage 5: Maintain (每 24h)

**输入**: `data/link_health.json`, `data/repo_scores.json`
**输出**: 清理后的 JSON

```
1. 链接清理:
   - fail_count >= max_consecutive_failures → 从 link_health.json 删除
   - last_verified 超过 7 天未更新 → 标记待重检或删除
2. 仓库质量评估:
   - 统计每个仓库贡献的链接: 有效数 / 总数 = valid_ratio
   - valid_ratio < repo_min_valid_ratio → low_quality_streak += 1
   - low_quality_streak >= repo_blacklist_after → blacklisted = true
   - user_repos 中的仓库: 只警告, 不 blacklist
3. 国家池瘦身:
   - 每国超出 country_pool_max 的部分, 按延迟最差的淘汰
4. 日志汇总: 打印清理统计
```

---

## 5. 检测引擎设计

### 抽象接口

```python
class TestEngine(ABC):
    """代理真连接检测引擎"""

    @classmethod
    @abstractmethod
    def name(cls) -> str: ...

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """检查二进制文件是否存在 (PATH / 配置路径 / 可自动下载)"""

    @abstractmethod
    def test_batch(
        self,
        links: list[str],
        timeout_ms: int,
        concurrency: int,
        on_done: Callable | None = None,
    ) -> dict[str, TestResult]:
        """批量测试, 返回 {link: TestResult}"""
```

### 引擎优先级: xray → singbox → mihomo → tcp

| 引擎 | 检测方式 | 平台 | 并发策略 |
|---|---|---|---|
| **xray** | 启动 xray 进程, 配置 SOCKS inbound, HTTP 请求经代理 | Win/Linux/Mac | 多端口并发 (每批 N 个端口) |
| **singbox** | 启动 sing-box, 类似 xray, 配置 inbound + outbound | Win/Linux/Mac | 多端口并发 |
| **mihomo** | REST API `/proxies/{name}/delay` | Win/Linux/Mac | API 并发 (最优) |
| **tcp** | asyncio TCP 握手 (退化, 不验证真实代理能力) | 全平台 | asyncio semaphore |

### 各引擎并发实现

**xray / singbox 多端口并发方案**:
```
1. 将 500 条链接分成 concurrency(50) 个一组
2. 为每组生成配置:
   - N 个 inbound (SOCKS port 20001~20050)
   - N 个对应 outbound (各代理节点)
   - routing 规则: inbound_tag → outbound_tag 一一映射
3. 启动 1 个引擎进程 (单进程多端口)
4. 并发通过各 SOCKS 端口发 HTTP 请求 (asyncio / aiohttp)
5. 测量延迟, 超时标记失败
6. 停止进程, 处理下一组
```

这样每组只需启动 1 个进程, 比逐个测试快 50 倍。

**mihomo 方案** (最简单):
```
1. 将所有 500 条转为 Clash proxy 格式 (现有 converter.py)
2. 生成 mihomo 配置, 启动 1 个 mihomo 进程
3. 调用 REST API /proxies/{name}/delay 并发测试
4. 收集结果, 停止进程
```

### 二进制自动管理

```python
def auto_select_engine(config: Config) -> TestEngine:
    """按优先级自动选择可用引擎"""
    if config.test_engine != "auto":
        return _ENGINES[config.test_engine]()

    for engine_cls in [XrayEngine, SingboxEngine, MihomoEngine, TcpEngine]:
        if engine_cls.is_available():
            return engine_cls()
    return TcpEngine()  # 终极 fallback
```

二进制查找顺序:
1. `config.yaml` 中指定的路径
2. 系统 PATH (`shutil.which("xray")`)
3. 本地缓存目录 (`~/.cache/best-proxy/bin/`)
4. 自动从 GitHub Releases 下载 (仅 mihomo, xray, sing-box 官方发布)

**自动下载矩阵**:

| 工具 | 来源 | 支持架构 |
|---|---|---|
| xray | github.com/XTLS/Xray-core/releases | linux-64, win-64, darwin-64, darwin-arm64 |
| sing-box | github.com/SagerNet/sing-box/releases | linux-64, win-64, darwin-64, darwin-arm64 |
| mihomo | github.com/MetaCubeX/mihomo/releases | linux-64, win-64, darwin-64, darwin-arm64 |

---

## 6. GeoIP 查询

```python
class GeoResolver:
    """批量 GeoIP 查询, 带持久化缓存"""

    def resolve_batch(self, hosts: list[str]) -> dict[str, str]:
        """返回 {host: country_code}"""
        # 1. 先查本地缓存 (link_health.json 中已有 country 的)
        # 2. 未命中的批量查 ip-api.com/batch (100 个/请求, 免费无 key)
        # 3. 备用: ip-api.com 单个查询 (有 45/min 限制)
        # 4. 全部失败 → "XX"
```

缓存策略: GeoIP 结果存入 `link_health.json` 的 `country` 字段, 只查一次。IP 不变则国家不变。

---

## 7. CLI 接口

```bash
# 单独运行各 Stage
python -m best discover              # Stage 1
python -m best collect               # Stage 2
python -m best verify                # Stage 3 (处理一批)
python -m best verify --all          # Stage 3 (处理全部, 不限 batch_size)
python -m best rank                  # Stage 4
python -m best maintain              # Stage 5

# 全量运行 (所有 Stage 顺序执行)
python -m best run
python -m best run --top 200         # 覆盖 top_n

# 查看状态
python -m best status                # 显示各国家池大小、待验证队列长度、引擎信息

# 指定引擎
python -m best verify --engine xray
python -m best verify --engine mihomo

# 指定配置
python -m best run --config custom_config.yaml
```

---

## 8. GitHub Actions 集成

```yaml
# .github/workflows/best.yml
name: Best Proxy

on:
  schedule:
    # Stage 1+2: 每 12 小时全量刷新
    - cron: '0 */12 * * *'
  workflow_dispatch:
    inputs:
      stage:
        description: 'Stage to run'
        default: 'run'
        type: choice
        options: [discover, collect, verify, rank, maintain, run]

jobs:
  best:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install deps
        run: pip install -r requirements.txt

      - name: Restore state
        # 从 data 分支或 artifact 恢复 link_health.json 等
        run: |
          git fetch origin data --depth=1 || true
          git checkout origin/data -- proxy/best/data/ 2>/dev/null || true

      - name: Run
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          cd proxy
          python -m best ${{ github.event.inputs.stage || 'run' }}

      - name: Commit results
        run: |
          git add proxy/repositories.txt proxy/collections.txt \
                  proxy/available.txt proxy/best.txt proxy/country/
          git diff --cached --quiet || git commit -m "update best proxies"
          git push

      - name: Save state to data branch
        run: |
          # 持久化 JSON 状态到 data 分支 (不污染 main)
          git stash
          git checkout data || git checkout --orphan data
          cp -r proxy/best/data/ .
          git add data/
          git commit -m "update state" || true
          git push origin data
```

对于高频 verify (每 10 分钟), 可以用独立 workflow:
```yaml
on:
  schedule:
    - cron: '*/10 * * * *'   # 注意: GitHub Actions 最小粒度 5 分钟
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      # ... (restore state, run verify + rank, save state)
      - run: cd proxy && python -m best verify && python -m best rank
```

---

## 9. 数据流图

```
                    ┌─────────────┐
                    │ config.yaml │
                    │ (用户仓库+  │
                    │  搜索配置)  │
                    └──────┬──────┘
                           │
          ┌────────────────▼────────────────┐
          │  Stage 1: discover (每 12h)     │
          │  GitHub API → repositories.txt  │
          │  评估 repo_scores.json          │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  Stage 2: collect (每 2h)       │
          │  Fetch repos → collections.txt  │
          │  新链接 → verify_queue.json     │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  Stage 3: verify (每 10min)     │
          │  取 500 条 → 引擎检测           │
          │  ┌──────────────────────┐       │
          │  │ xray → singbox →     │       │
          │  │ mihomo → tcp         │       │
          │  └──────────────────────┘       │
          │  更新 link_health.json          │
          │  → available.txt                │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  Stage 4: rank (verify 后)      │
          │  按延迟排序, GeoIP 分国家       │
          │  → country/*.txt                │
          │  → best.txt (top N)             │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  Stage 5: maintain (每 24h)     │
          │  清理死链 (fail >= 3)           │
          │  评估仓库质量 → blacklist       │
          │  国家池瘦身 (> pool_max)        │
          └─────────────────────────────────┘
```

---

## 10. 关键设计决策

### Q: 为什么分 5 个 Stage 而不是一个脚本?

**独立性**: 每个 Stage 读文件 → 处理 → 写文件, 无运行时依赖。崩溃不影响其他 Stage。
**频率解耦**: GitHub 搜索不需要每 10 分钟跑, verify 不需要等 12h。
**可调试性**: 可以单独重跑任何一步。
**CI 友好**: 不同 Stage 可以用不同的 cron job, 甚至不同的 runner。

### Q: 为什么 xray 优先?

用户使用 v2rayN (基于 xray-core), xray 配置格式与用户本地一致, 检测结果最贴近实际使用体验。且 xray 支持所有主流协议 (vmess/vless/trojan/ss/reality)。

### Q: 为什么不用数据库?

JSON 文件足够 (预计 < 50k 条目 ≈ 几十 MB), 无需额外依赖, CI 环境天然支持, git-friendly 可追踪变化。

### Q: 数据量级预估

| 指标 | 预估值 |
|---|---|
| 仓库数 | 20~50 |
| 原始链接 (collections) | 5,000~20,000 |
| 可用链接 (available) | 500~3,000 |
| best.txt | 100 |
| 每国家池 | 10~100 |
| link_health.json 大小 | 1~10 MB |
| 单次 verify 耗时 (500条) | 2~5 min |

---

## 11. 依赖

```
# requirements.txt 新增
pyyaml          # 配置解析
aiohttp         # 引擎 HTTP 测试 (异步, 替代 requests 用于并发测试)
```

现有依赖保持: `requests`, `rich`, `urllib3`

---

## 12. 实现优先级

| 优先级 | 模块 | 说明 |
|---|---|---|
| P0 | `config.yaml` + `state.py` | 配置和状态管理是一切基础 |
| P0 | `engine/mihomo.py` | 改造现有, 最快可用 |
| P0 | `verify.py` + `rank.py` | 核心流程 |
| P1 | `discover.py` + `collect.py` | 改造现有 github.py |
| P1 | `engine/xray.py` | 用户首选引擎 |
| P1 | `geo.py` | 国家分类 |
| P1 | `maintain.py` | 累积运行后必需 |
| P2 | `engine/singbox.py` | 第二选择引擎 |
| P2 | `__main__.py` CLI | 用户友好 |
| P2 | GitHub Actions workflow | CI 集成 |
