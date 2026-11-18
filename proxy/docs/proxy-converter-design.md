# proxy/converter/ 模块设计方案

## Context

`proxy/pac/` 现承载两件事:解析 9 种上游配置格式 (xray / clash / singbox / hysteria{1,2} / mieru / juicity / naive / shadowquic) 生成 `Node` 池,以及把这些节点渲染为 v2rayN 分享链接 + Clash/mihomo YAML。

当前痛点 (与 subconverter-ng 的差距):

1. **IR 偏薄**:`pac/nodes.py` 的 `Node` 只有 `protocol / host / port / credential / link / clash_proxy`,transport / security / TLS / reality / mux 等信息全部塞进 `link` 字符串或被丢弃。
2. **link ↔ dict 往返解析**:`pac/render_clash.py` 当节点无 `clash_proxy` 时,经 `core.parse.link_to_clash(link)` 重新解析分享链接 → mihomo proxy dict。这是一次有损的 round-trip,且转换器与 pac/parser 各维护一份。
3. **协议支持矩阵硬编码**:`V2RAYN_PROTOCOLS` / `CLASH_PROTOCOLS` 在 `pac/nodes.py` 中是写死的 set,扩展协议需改多处;generator 不是独立可注册单元,而是 renderer 里的 if-else 分支。
4. **职责混杂**:每个 `pac/*.py` 解析器同时承担"配置 → Node"和"Node → 分享链接"两件事,难以独立测试/替换。

目标:参照 subconverter-ng,引入 `proxy/converter/` 独立模块,提供

- 富 IR `Node` (一次性完整描述代理节点)
- 解析器 `parser/`:源配置文本 → `list[Node]`
- 生成器 `generator/Node → 目标格式` (本轮仅 `clash`)
- `compat.py` 桥接新旧 IR,实现"先并行、后切换"渐进迁移,**本轮不改任何 `pac/` 与 `core/parse.py` 现有文件**。

## 目标 & 非目标

**目标 (本轮 Phase 1)**
- 建立 `proxy/converter/` 完整骨架,可独立 import
- Node 富 IR,包含未来 v2rayN / xray / singbox generator 所需全部字段
- 9 个源格式 parser + 分享链接 parser (`parse_share_link`)
- Clash/mihomo proxy dict generator (`generate(node, "clash")`)
- `compat.py` 双向桥接(本轮只实现 `from_pac_node`,`to_pac_node` 在 Phase 2 一起做)

**非目标 (后续 Phase)**
- v2rayN / xray / singbox generator → 留 Phase 3
- `pac/render_clash.py` 切换到新 generator → 留 Phase 2
- 替换 `core/parse.py` 的 link→clash 转换器 → 留 Phase 3
- 删除旧 `pac/nodes.py` `Node` / `NodePool` → 留 Phase 4

## 模块布局

```
proxy/converter/
├── __init__.py            # 公共 API: parse, generate, from_pac_node, Node
├── models.py              # Node dataclass (rich IR) + normalize_protocol
├── parser/
│   ├── _base.py           # Parser 协议
│   ├── __init__.py        # registry + parse_config(text, ptype, source) -> list[Node]
│   ├── xray.py            # xray outbounds (json)
│   ├── clash.py           # clash/mihomo proxies (yaml)
│   ├── singbox.py         # sing-box outbounds (json)
│   ├── hysteria.py        # hysteria2 client config (json)
│   ├── hysteria1.py       # hysteria v1 client config (json)
│   ├── mieru.py           # mieru profile (json)
│   ├── juicity.py         # juicity client config (json)
│   ├── naive.py           # naive proxy url (json)
│   ├── shadowquic.py      # shadowquic client.yaml
│   └── share_link.py      # parse_share_link(link) -> Node (vmess/vless/ss/trojan/hy2/tuic/anytls)
├── generator/
│   ├── _base.py           # Generator 协议
│   ├── __init__.py        # registry + generate(node, target) -> dict | str | None
│   └── clash.py           # Node → mihomo proxy dict
└── compat.py              # from_pac_node(pac.nodes.Node) -> Node (thin→rich 桥)
```

**为何 share_link 与 9 个源 parser 分开**:9 个源 parser 接受"完整配置文件文本"(可能含多节点),`share_link` 接受"单条分享链接"。输入形态不同、失败模式不同,接口上分 `parse_config` / `parse_share_link` 两函数,内部用同一套 share-link 子解析器。

## Node IR (rich)

`proxy/converter/models.py`:

```python
@dataclass
class Node:
    # ── Identity ──
    name: str = ""
    protocol: str = ""        # 归一化后小写 (vmess/vless/ss/trojan/hysteria2/tuic/anytls/hysteria1/mieru/juicity/naive/shadowquic)
    host: str = ""
    port: int = 0

    # ── Credentials ──
    uuid: str = ""            # vmess/vless/tuic/juicity
    password: str = ""        # ss/trojan/tuic/juicity/anytls/hysteria2/naive
    alter_id: int = 0         # vmess
    cipher: str = ""          # vmess (scy) / ss (method)
    cipher_2022: bool = False # ss-2022 标识
    auth_str: str = ""        # hysteria1
    username: str = ""        # mieru/shadowquic/naive

    # ── Transport ──
    transport: str = "tcp"    # tcp/ws/grpc/http/httpupgrade/splithttp/xhttp
    path: str = ""            # ws/grpc/h2/xhttp/splithttp/httpupgrade
    host_headers: list[str] = field(default_factory=list)  # ws Host / h2 host[]
    service_name: str = ""    # grpc
    transport_mode: str = ""  # xhttp/splithttp 模式
    header_type: str = ""     # vmess tcp headerType (http)

    # ── TLS ──
    tls: bool = False
    sni: str = ""
    alpn: list[str] = field(default_factory=list)
    fingerprint: str = ""
    skip_cert_verify: bool = False
    ech: bool = False
    ech_config: str = ""

    # ── Reality ──
    reality: bool = False
    reality_public_key: str = ""
    reality_short_id: str = ""

    # ── Flow / Mux ──
    flow: str = ""            # vless xtls-rprx-vision
    mux: dict = field(default_factory=dict)  # xray/sing-box multiplex (free-form)

    # ── Hysteria2 ──
    obfs: str = ""
    obfs_password: str = ""

    # ── TUIC / Juicity ──
    congestion_controller: str = "bbr"

    # ── Mieru ──
    multiplexing: str = "MULTIPLEXING_LOW"
    port_range: str = ""

    # ── Hysteria1 ──
    hy1_protocol: str = "udp"
    up_mbps: int = 30
    down_mbps: int = 30

    # ── ShadowQUIC ──
    zero_rtt: bool = False

    # ── Chained / Misc ──
    dialer_proxy: str = ""
    extra_params: dict = field(default_factory=dict)  # 透传无法建模的字段

    # ── Compatibility / Metadata ──
    raw_link: str = ""        # 来源若是分享链接,保存原始字符串
    source: str = ""          # URL 或 store label
    schema_version: int = 1
```

**字段取舍说明** (回应 Plan agent 反馈):
- **保留 flat 形态**:虽然子 dataclass (`TlsCfg` / `RealityCfg`) 利于编辑器分组,但本轮 Clash generator 不需要这种分组;v2rayN/xray generator 加入时再行 refactor。代价是字段多,但收益是 `node.sni` / `node.transport` 这类直白访问。
- **覆盖未来 generator 字段**:`flow` / `host_headers` / `transport_mode` / `header_type` / `cipher_2022` / `ech` / `dialer_proxy` / `mux` / `extra_params` 一并加入,避免 Phase 3 时改 dataclass 破坏所有已落盘的 IR。
- `extra_params: dict` 作为兜底,透传无法建模的字段(预留扩展,生成器按需读取)。
- `schema_version: int = 1`:为未来 IR 演化做版本标记(不写迁移逻辑,仅占位)。

**协议归一化** (`models.py` 同文件,内嵌函数):

```python
PROTOCOL_ALIASES = {
    "shadowsocks": "ss",
    "hysteria": "hysteria1",
    "hy2": "hysteria2",
}

def normalize_protocol(name: str) -> str:
    return PROTOCOL_ALIASES.get(name.lower(), name.lower())
```

注意:`pac/nodes.py` 现有的 `V2RAYN_PROTOCOLS` / `CLASH_PROTOCOLS` 集合与归一化映射继续保留在 `pac/` 侧(因 `pac/` 仍用旧 IR)。Phase 4 收尾时再合并。

## Parser 接口

`proxy/converter/parser/_base.py`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Parser(Protocol):
    ptype: str  # e.g. "xray" / "clash" / "singbox"
    def parse_config(self, text: str, source: str = "") -> list[Node]: ...
```

`proxy/converter/parser/__init__.py` (registry 模式,与 `proxy/sources/__init__.py` 一致):

```python
PARSERS: dict[str, Parser] = {}  # 由各模块装饰器注册
def parse_config(text: str, ptype: str, source: str = "") -> list[Node]:
    p = PARSERS.get(ptype)
    if p is None:
        raise ValueError(f"Unknown ptype: {ptype!r}")
    return p.parse_config(text, source=source)
```

**单条分享链接 parser** (`parser/share_link.py`) 独立函数签名:

```python
def parse_share_link(link: str, source: str = "") -> Node | None:
    """vmess:// / vless:// / ss:// / trojan:// / hysteria2:// / tuic:// / anytls:// → Node"""
```

实现要点:
- vmess 解析:base64 解码 JSON,提取 `add/port/id/aid/scy/net/host/path/tls/sni/fp`
- vless 解析:`urllib.parse.urlparse` 取 `username/hostname/port`,query 解析 `type/host/path/security/sni/fp/pbk/sid/flow/alpn`
- ss 解析:同时支持 `ss://BASE64(method:password)@host:port` 与 `ss://BASE64(method:password@host:port)`
- trojan/hysteria2/tuic/anytls:urlparse,query 参数 `sni/insecure/obfs/allowInsecure/congestion_control/alpn`

## Generator 接口

`proxy/converter/generator/_base.py`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Generator(Protocol):
    target: str  # e.g. "clash" / 未来 "v2rayn" / "xray" / "singbox"
    def generate(self, node: Node) -> dict | str | None: ...
    def supported(self, node: Node) -> bool: ...  # 该协议该 generator 是否能渲染
```

`proxy/converter/generator/__init__.py`:

```python
GENERATORS: dict[str, Generator] = {"clash": ClashGenerator()}

def generate(node: Node, target: str = "clash") -> dict | str | None:
    g = GENERATORS.get(target)
    if g is None:
        raise ValueError(f"Unknown target: {target!r}")
    if not g.supported(node):
        return None
    try:
        return g.generate(node)
    except Exception:
        return None
```

**本轮唯一 generator**: `proxy/converter/generator/clash.py` → `ClashGenerator`,实现 `Node → mihomo proxy dict`。

要点:
- 按 `node.protocol` 分支 (`vmess/vless/ss/trojan/hysteria2/tuic/anytls/hysteria1/mieru/juicity/naive/shadowquic`)
- 字段映射尽量复用 `core/parse.py:_CLASH_CONVERTERS` 的语义,但**直接消费富 IR**:
  - `tls` + `reality` 同时只能一个为真;两者都假则不输出 `tls: true`
  - `transport=ws/grpc/http/httpupgrade` 时输出对应 `*-opts` 块
  - `host_headers` 列表 → `ws-opts.headers.Host` (单元素) 或 `h2-opts.host` (数组)
  - `flow` → vless 的 `flow` 字段
  - `obfs/obfs_password` → hysteria2 的 `obfs/obfs-password`
  - `multiplexing/port_range` → mieru 的 `transport/port-range`
  - `congestion_controller` → tuic/juicity 的 `congestion-controller`
- **返回 `None` 情形**:`protocol` 不在 mihomo 支持集(`V2RAYN_PROTOCOLS - CLASH_PROTOCOLS` 之外的子集),或关键字段缺失

**与现有 `core/parse.link_to_clash` 的关系**:本轮不删不改。Phase 2 在 `pac/render_clash.py` 加分支:有 `clash_proxy` 用旧的,否则用 `converter.generate(node, "clash")`,直到 `clash_proxy` 来源全部被替换后再移除。

## compat.py

`proxy/converter/compat.py` — **thin→rich 桥**(本轮唯一方向):

```python
def from_pac_node(old: "pac.nodes.Node") -> Node:
    """pac.nodes.Node (thin IR) → converter.Node (rich IR)。

    升级策略:
    1. 若 old.clash_proxy 不为空,经 mihomo dict 反解析填齐 transport / tls / reality
       / flow / obfs 等所有字段(优先保证字段最完整)
    2. 否则仅填 protocol / host / port / credential(粗略)
    3. raw_link / source 透传
    """
```

`to_pac_node` (rich→thin) 在 Phase 2 一并实现,本轮只在 compat.py 留 stub + 文档:

```python
def to_pac_node(new: Node) -> "pac.nodes.Node":
    """converter.Node → pac.nodes.Node。

    Phase 2 任务:对 rich 节点重新生成 clash_proxy (经 generator) + 分享链接
    (经 share_link.build),凑齐 pac.Node 期望的两条信息通道。
    本轮 raise NotImplementedError。
    """
    raise NotImplementedError("Phase 2 任务")
```

## Phase 1 实施步骤(本轮实际产出)

按以下顺序写文件,每步可独立验证:

1. **`proxy/converter/__init__.py`** — 暴露 `Node`, `parse_config`, `parse_share_link`, `generate`, `from_pac_node`
2. **`proxy/converter/models.py`** — `Node` dataclass + `normalize_protocol` + `PROTOCOL_ALIASES`
3. **`proxy/converter/parser/_base.py`** — `Parser` Protocol
4. **`proxy/converter/parser/share_link.py`** — 7 种分享链接解析(`vmess/vless/ss/trojan/hysteria2/tuic/anytls`)。**这是本轮 unit 验证最容易跑通的部分**(纯输入输出,无 IO)
5. **`proxy/converter/parser/__init__.py`** — registry + `parse_config` 入口
6. **9 个源 parser** (`xray.py` `clash.py` `singbox.py` `hysteria.py` `hysteria1.py` `mieru.py` `juicity.py` `naive.py` `shadowquic.py`):
   - 每个文件顶部 `PARSERS_REGISTRY = {ptype: self}` 装饰器注册,或由 `__init__.py` 集中 import 后填入 `PARSERS` 字典
   - 每个文件内 `parse_config(text, source) -> list[Node]` 严格填充富 IR
   - 实现要点从现有 `pac/*.py` 移植:`pac/clash.py:parse_config` → `converter/parser/clash.py:parse_config`,把 `Node` 字段按本设计填齐
7. **`proxy/converter/generator/_base.py`** — `Generator` Protocol
8. **`proxy/converter/generator/clash.py`** — `ClashGenerator` 实现(参照 `core/parse._CLASH_CONVERTERS` 的语义,但消费富 IR)
9. **`proxy/converter/generator/__init__.py`** — registry + `generate` 入口
10. **`proxy/converter/compat.py`** — `from_pac_node` 实现 + `to_pac_node` stub

## 关键文件复用参考

- `proxy/core/parse.py:_b64decode` (行 30-35) → 复制到 `converter/models.py` 或 `converter/util.py` 作为内部 helper(避免跨模块依赖)
- `proxy/core/parse.py:_CLASH_CONVERTERS` (行 380-384) + `_clash_*` (行 168-378) → `generator/clash.py` 的字段映射直接参考其字段命名,**但不调用它**(避免循环依赖)
- `proxy/sources/_base.py` `Source` Protocol + `proxy/sources/__init__.py` registry → 套用同样模式
- `proxy/pac/util.py:console` (Rich, `highlight=False`) → 错误日志统一使用
- `proxy/pac/nodes.py:_b64decode` (行 59-63) → vmess/mieru 解析仍需要

## 未来阶段(概要,本轮不动)

**Phase 2**: `pac/render_clash.py` 中 `link_to_clash(node.link, node.name)` 回退路径改为 `converter.generate(converter.from_pac_node(node), "clash")`,运行 `python -m proxy pac`,与原产物 `clash.yaml` diff(应当为空或仅字段顺序差异)。同时实现 `to_pac_node`。

**Phase 3**: 9 个 `pac/*.py` parser 切到 `converter/parser/*`(删 `parse_config` 中 `link` 字段填充,改为 `pac/render_v2rayn.py` 用 `converter.parse_share_link` 重建链接);`core/parse.link_to_clash` 标记 deprecated。

**Phase 4**: 删 `pac/nodes.py` 与 `core/parse.py` 中被替代的部分;`converter/protocols.py` 接管 `V2RAYN_PROTOCOLS` / `CLASH_PROTOCOLS`。

## 验证

项目无测试基础设施(`**/test_*.py` / `conftest.py` 均不存在)。Phase 1 验证手段:

1. **导入冒烟测试**:
   ```bash
   cd d:\Code\Python\Yuki-Actions\proxy
   python -c "from converter import Node, parse_config, generate, from_pac_node; print('OK')"
   ```
2. **share_link parser 单元用例**(`python -c` 即可):
   - 7 种协议的示例链接各一条,断言 `parse_share_link` 返回的 `Node` 字段非空且语义正确
3. **Clash generator round-trip**:
   - 手工构造一个 `Node(protocol='vless', transport='ws', tls=True, sni='example.com', ...)`
   - `generate(node, 'clash')` 返回 dict,断言 `type='vless'`、`tls=True`、`ws-opts.path` 等关键字段
4. **源 parser 端到端**:
   - 取 `proxy/pac/clash_config_links.txt` 中任一 URL,下载后 `parse_config(text, 'clash', source=url)`
   - 断言节点数 > 0、首节点 `protocol` ∈ `{vmess, vless, ss, trojan, hysteria2, tuic, anytls, hysteria1, mieru, shadowquic, juicity, naive}` 之一
5. **compat bridge**:
   - 手工构造一个 `pac.nodes.Node(protocol='vless', host='1.2.3.4', port=443, credential='uuid', clash_proxy={...})`
   - `from_pac_node(old)` 返回的 `Node.tls` / `Node.transport` 等字段反映 `clash_proxy` 中的设置
6. **回归保护**:
   - 跑 `python -m proxy pac` 完整管线,确认 `proxy/subscribe/clash.yaml` 产物与改动前一致(本轮不动 pac/,理论上应当 byte-identical)

**CI 集成**:现有 `proxy.yml` 工作流无须改动;后续 Phase 2-3 时再加入"converter vs pac 产物 diff" 步骤。
