# Patent MCP 搜索最佳实践

> 基于两轮全链路 Demo 实战经验（Agent 沙箱 + Chiplet 互连）总结。

## 一、核心原则

### 不要用自然语言关键词搜专利

专利摘要的用词习惯和日常技术讨论完全不同。两轮 Demo 证明：

| 搜索方式 | 耗时 | 命中率 | 示例 |
|---------|------|--------|------|
| 自然语言关键词 | 2-4s | **0%（两轮 16 次全空）** | "pre-warmed execution context pool" |
| CPC 分类号（无关键词） | 2-5s | **100%** | `cpc: G06F21/53` |
| CPC + 极窄关键词（1-2个词） | 3-8s | 中等 | `cpc: H01L25/065 query: chiplet` |

**结论：首选 CPC 分类号搜，关键词只做 CPC 搜出结果后的二次过滤。**

### 为什么关键词搜不到？

BigQuery 中的专利摘要（`abstract_localized`）使用以下语言：
- 法律化表述："A method comprising..."、"Apparatuses, systems, and techniques to..."
- 分类导向术语：TEE、enclave、interposer、routing layer
- 不包含日常讨论中的"预热池"、"自适应"、"沙箱"

你写的是 `pre-warmed execution context`，专利里写的是 `uniform enclave interface`——说的根本不是同一套语言。

---

## 二、搜索工作流

### 推荐流程

```
Step 1: CPC 分类号搜（无关键词）→ 拿到候选专利列表
        ↓
Step 2: 从结果中人工/Agent 筛选相关专利号
        ↓
Step 3: get_patent(publication_number) → 拿全文详情
        ↓
Step 4: 对照交底书特征逐条分析 → 输出查新简报
```

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
| 多器件组装 | `H01L25/00` | 多个半导体器件组装 |
| 互连结构 | `H01L23/48` | 互连结构（较宽泛） |
| 通孔互连 | `H01L21/768` | 垂直互连通孔 |

### 如何找到正确的 CPC

1. 搜索一件已知相关专利：`get_patent("US-XXXXXXXXX-X1")`
2. 查看返回的 `cpc_codes` 字段
3. 用该 CPC 做批量检索

---

## 三、中美数据差异

| 维度 | US 专利 | CN 专利 |
|------|---------|---------|
| 英文摘要 | ✅ 完整 | ✅ 有（翻译） |
| 中文摘要检索 | N/A | ⚠️ **不可靠** |
| CPC 分类覆盖 | ✅ 完整 | ⚠️ 部分 |
| 关键词匹配 | 需用专利语言 | ❌ 中文关键词基本搜不到 |
| 可用搜索方式 | CPC + 关键词 | **仅 CPC 无关键词搜** |

**对产品的影响**：BigQuery 对 CN 专利的可检索性存在显著缺口。如果目标市场包含中国，需要补充 CNIPA 或商业数据库（PatSnap、智慧芽）作为数据源。

---

## 四、性能数据

| 操作 | 典型耗时 | 说明 |
|------|---------|------|
| `get_patent` (Web) | 0.7-0.9s | 从 patents.google.com 抓取 ✓ |
| `get_patent` (BigQuery) | 2.5-3s | 单行查询，稳定 |
| `get_patent_claims` (Web) | 0.5-1s | 从网页解析权利要求 |
| `search_patents` (CPC无关键词) | 2-5s | **推荐方式** |
| `search_patents` (关键词+CPC) | 3-8s | 关键词可能降低召回 |
| `search_patents` (纯关键词) | 2-4s→**0结果** | 不推荐 |

**注意**：`search_patents` 的 BIGQUERY LIKE 查询扫描 208GB 表，必须搭配 CPC 或 country+date 约束。无约束的关键词搜索会被服务器拒绝。

---

## 五、预研工作流模板

参考 `demos/` 目录中的两个完整案例：

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

---

## 六、已知限制

1. **CN 专利覆盖不足**：中文关键词搜索不可用，CPC 分类覆盖不完整。需商业数据库补充
2. **LIKE 搜索昂贵**：208GB 全表扫描，查询优化依靠 CPC + 日期约束
3. **MCP 状态机**：Gateway 在连续失败后需要 `/restart` 重置
4. **专利语言门槛**：Agent 需要学习专利写作语言才能写出有效搜索词——CPC 优先策略规避了这个问题
5. **引用链不完整**：BigQuery 的 citations 字段只包含部分引用关系，完整引用树需要额外处理

---

## 七、Assignee 搜索：企业/城市级专利图谱

> v1.5.1 新增。底层一行 SQL `WHERE LOWER(name) LIKE LOWER(@assignee)`，解锁城市/公司维度的专利分析。

### 典型用法

```
search_patents(assignee="BOE", country="CN", after="2014-01-01", limit=50)
```

### 应用场景

| 场景 | assignee 值 | 说明 |
|------|-----------|------|
| 单家企业专利全景 | `"BOE"`、`"HUAWEI"` | 模糊匹配，覆盖子公司 |
| 城市/区域专利地图 | `"HEFEI"`、`"SHENZHEN"` | 大城市的 assignee 名里常见地名关键字 |
| 行业专利对标 | `"SEMICONDUCTOR"` | 特定行业玩家的专利覆盖 |
| 组合搜索 | `assignee:"BOE" cpc:"H01L25"` | 企业 × 技术领域交叉 |

### 注意

- 模糊匹配（LIKE `%keyword%`），`"BOE"` 可能也匹配 `"BOEING"`——确认结果时做人工去噪
- 建议搭配 `country` 或 `after` 缩小结果集
- assignee 本身可作为成本控制过滤器（无需额外搭配 country/cpc/after）
