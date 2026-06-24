# Patent MCP 搜索最佳实践

> 基于两轮全链路 Demo 实战 + v1.7.0 Firecrawl web fallback 更新。

## 一、核心原则

### 首选 CPC 分类号，关键词做辅助

| 搜索方式 | 耗时 | 命中率 | 示例 |
|---------|------|--------|------|
| CPC 分类号（无关键词） | 2-5s | **100%** | `cpc: H01L`, `cpc: G06F21/53` |
| 关键词 + country CN | 3-8s | **可用** | `query: "芯片" country: CN` |
| 关键词（无 CPC/无约束） | ❌ 拒绝 | — | 必须至少搭配一个过滤参数 |

### CN 关键词搜索已修复（v1.5.2+）

曾经 `query="芯片" + country=CN` 返回 0 结果（仅搜英文摘要）。现已修复——同时搜索中英文摘要：

```
✅ query="芯片" + country=CN            → 有结果
✅ query="neural network" + country=CN  → 有结果
```

但专利摘要用词仍偏法律化/分类导向。"预热执行上下文池"在专利里可能是 "uniform enclave interface"——说的不是同一套语言。关键词仍建议搭配 CPC 使用。

---

## 二、搜索工作流

### 推荐流程

```
Step 1: CPC 或关键词搜 → 拿到候选专利列表
        ↓
Step 2: 从结果中人工/Agent 筛选相关专利号
        ↓
Step 3: get_patent(publication_number) → 拿全文详情
        ↓
Step 4: 对照交底书特征逐条分析 → 输出查新简报
```

### CN 专利四种搜索路径（v1.7.0）

| 路径 | 示例 | 适用场景 |
|------|------|---------|
| **CPC + CN** | `cpc=H01L country=CN after=2023-01-01` | 已知技术分类，覆盖最广 |
| **关键词 + CN** | `query="芯片" country=CN` | 自然语言探索，搜中英文摘要 |
| **Assignee + CN** | `assignee="BOE" country=CN` | 企业/城市级专利图谱 |
| **Web fallback** | `cpc=H01L25/065 country=CN` → BigQuery 拒绝 → 自动 Firecrawl | 细粒度 CPC 无 BQ 覆盖时自动触发 |

### CPC 分类号速查

#### 软件/安全类
| 领域 | CPC | 说明 |
|------|-----|------|
| 沙箱安全 | `G06F21/53` | 监控用户/程序以维护平台完整性 |
| 虚拟化 | `G06F9/455` | 仿真/虚拟化 |
| 调度 | `G06F9/4881` | 任务调度 |
| 多程序 | `G06F9/46` | 多程序编排 |
| 数据保护 | `G06F21/62` | 通过平台保护数据访问 |

#### 硬件/封装类
| 领域 | CPC | 说明 |
|------|-----|------|
| 堆叠器件 | `H01L25/065` | 堆叠半导体器件（Chiplet 核心分类） |
| 芯片间互连 | `H01L23/538` | IC 芯片间互连 |
| 多器件组装 | `H01L25/00` | 多个半导体器件组装（父类，覆盖更广） |
| 互连结构 | `H01L23/48` | 互连结构（较宽泛） |
| 通孔互连 | `H01L21/768` | 垂直互连通孔 |

### 如何找到正确的 CPC

1. 搜索一件已知相关专利：`get_patent("US-XXXXXXXXX-X1")`
2. 查看返回的 `cpc_codes` 字段
3. 用该 CPC 做批量检索

---

## 三、中美数据差异（v1.7.0 更新）

| 维度 | US 专利 | CN 专利 |
|------|---------|---------|
| 英文摘要 | ✅ 完整 | ✅ 有（翻译） |
| 中文摘要检索 | N/A | ✅ 可用（v1.5.2 修复，搜中英双语） |
| CPC 分类覆盖 | ✅ 完整 | ⚠️ 部分（细粒度 CPC 可能 0 结果，父类可用） |
| 关键词匹配 | 需用专利语言 | 需用专利语言 + 中英双语 |
| Web fallback | ❌ 不需要 | ✅ Firecrawl 自动回退（v1.7.0） |

**Web fallback 触发条件：** BigQuery dry-run 估算 > 50 GB（例如 `H01L25/065 + CN` → 256 GB），自动走 Firecrawl 网页搜索 → Google Patents 富化。用户无感知。

---

## 四、性能数据（v1.7.0 实测）

| 操作 | 典型耗时 | 说明 |
|------|---------|------|
| `get_patent` (Web) | 0.7-0.9s | 从 patents.google.com 抓取 |
| `get_patent` (BigQuery) | 2.5-3s | 单行查询，稳定 |
| `get_patent_claims` (Web) | 0.5-1s | 从网页解析权利要求 |
| `search_patents` (CPC+CN) | 2-5s | 推荐方式 |
| `search_patents` (关键词+CN) | 3-8s | 双语言扫描 |
| `search_patents` (CN web fallback) | 30-45s | Firecrawl 搜索 + Google Patents 富化 × N条 |
| `search_patents` (纯关键词无约束) | ❌ 拒绝 | 至少需要一个过滤参数 |

---

## 五、CN CPC 覆盖缺口

BigQuery 的 CN CPC 分类不完整——这是 Google 数据层的问题，不是代码 bug。

**已知缺口：** `H01L25/065`（先进封装）→ 0 CN 结果（BigQuery + Google Patents 搜索均 0）

**应对策略：**
1. **父类 CPC** — `H01L` 替 `H01L25/065`，覆盖广但精度低
2. **Web fallback** — Firecrawl 网页搜索 "H01L25/065 芯片 封装 中国专利" → 提取专利号 → 富化
3. **Assignee** — 知道公司名直接 `assignee="TSMC" country=CN`，绕过 CPC 完全

详见 [`docs/cn-cpc-correction-table.md`](docs/cn-cpc-correction-table.md)。

---

## 六、Assignee 搜索：企业/城市级专利图谱（v1.5.1+）

### 典型用法

```
search_patents(assignee="BOE", country="CN", after="2014-01-01", limit=50)
```

### 应用场景

| 场景 | assignee 值 | 说明 |
|------|-----------|------|
| 单家企业专利全景 | `"BOE"`、`"HUAWEI"` | 模糊匹配，覆盖子公司 |
| 城市/区域专利地图 | `"HEFEI"`、`"SHENZHEN"` | 大城市 assignee 名里常见地名 |
| 行业专利对标 | 行业关键词 | 特定行业玩家覆盖 |
| 组合搜索 | `assignee:"BOE" cpc:"H01L25"` | 企业 × 技术领域交叉 |

**注意：** 模糊匹配 `LIKE %keyword%`，`"BOE"` 可能也匹配 `"BOEING"`——人工去噪。

---

## 七、已知限制

1. **CN 细粒度 CPC 覆盖不足** — BigQuery + Google Patents 层均无数据。Web fallback 弥补
2. **Web fallback 较慢** — Firecrawl + Google Patents 富化 30-45s，BigQuery 直接查 2-5s
3. **Firecrawl 消耗 credits** — 4 credits/次 CN 回退查询。Free tier 包含额度
4. **专利语言门槛** — Agent 需学习专利写作语言。CPC 优先策略规避此问题
5. **引用链不完整** — BigQuery citations 字段仅部分引用关系
6. **SearXNG CN 引擎全灭** — Baidu/Google/DDG/Startpage 均被验证码封。已切换 Firecrawl

---

## 八、预研工作流模板

参考 `demos/` 目录中的完整案例：

```
~/.hermes/demos/
├── pre-search-agent-sandbox/
│   ├── disclosure.md       # 结构化交底书
│   └── pre-search-brief.md # 查新简报
└── pre-search-chiplet/
    ├── disclosure.md
    └── pre-search-brief.md
```

### 交底书模板

```markdown
# 发明交底书：[技术方案名称]

## 技术领域
## 待解决的技术问题（3点）
## 技术方案（3-4个核心特征，每个有明确可检索的技术要素）
## 与现有技术的区别（逐一对比）
```

### 查新简报模板

```markdown
# 查新简报：[技术方案名称]

## 一、检索结果概览（特征-专利映射表）
## 二、逐特征详细分析（最接近专利的摘要+区别分析）
## 三、中美竞争态势（如有）
## 四、综合评估（新颖性/侵权风险/授权前景）
## 五、建议（权利要求策略 + 补充检索方向）
```
