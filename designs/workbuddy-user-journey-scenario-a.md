# WorkBuddy × Patent MCP — 场景A用户旅程设计

> **前提假设**：WorkBuddy Skill Marketplace 支持 MCP 协议，Agent 具备自动发现→评估→安装能力。
> **目标用户**：律师、IP 经理、企业法务、投资分析师（非技术用户，不会也不该碰 JSON 配置）。
> **设计原则**：用户一句话触发，Agent 完成全部后端工作。零配置、零等待、零"技术感"。

---

## 一、用户视角：一个完整的故事

```
────────── 第一次使用 ──────────

李明是某律所的 IP 律师，上午 9:17 打开 WorkBuddy：

  李明：帮我查一下华为在 AI 芯片领域有哪些核心专利，
        特别是被其他公司大量引用的那些。

  WorkBuddy：好的，我先搜索华为在 AI 芯片领域的专利。
        这需要用到专利分析工具，我可以为你安装
        "Patent MCP Server"（免费，公开数据），
        要现在安装吗？[安装] [了解更多]

  李明点「安装」（第一个按钮）。

  WorkBuddy：已在安装。正在搜索中...

  （~8 秒后）

  WorkBuddy：找到 12 件华为 AI 芯片相关专利。
        最核心的 3 件：
        1. CN110286864A — 神经网络计算芯片架构
           被 47 件专利引用，含 Apple、三星
        2. CN108668027A — AI 芯片互联方法
           被 31 件引用
        3. CN111079911A — 稀疏神经网络加速器
           被 28 件引用
        
        要我生成竞争引证矩阵吗？
        这样可以看到谁在紧密跟踪华为这些技术。

  李明：好，生成。

  WorkBuddy：（~5 秒）[展示矩阵表格]

────────── 第二次使用（第二天） ──────────

  李明：分析一下中芯国际在 14nm 以下制程的专利
        布局。

  WorkBuddy：（Patent MCP 已安装，直接用）
        正在查询...
        
        [直接返回分析结果，不再询问安装]

────────── 第二天下午 ──────────

  李明：昨天华为 AI 芯片那几个核心专利，
        帮我看看法律状态有没有变化。

  WorkBuddy：查询中...
        CN110286864A — 状态：已授权 ✓（2024-03 授权）
        CN108668027A — 状态：实质审查中
        CN111079911A — 状态：已授权 ✓（2024-06 授权）
        
        近 6 个月内 2 件新获得授权，无驳回或撤回。
```

**关键体验**：
- 第一次：一句话 → 1 次确认（"要安装吗"）→ 出结果
- 第二次及以后：一句话 → 直接出结果
- 全程没有出现过 URL、JSON、SSE、BigQuery 这些词
- 用户不知道、也不需要知道后面跑的是 MCP

---

## 二、WorkBuddy 内部决策链（6 步）

### Step 1 — 意图识别

```
用户输入："帮我查一下华为在 AI 芯片领域有哪些核心专利"

WorkBuddy Agent 内部处理：
  → 分析任务类型：专利搜索 + 引证分析
  → 检查本地可用工具：无匹配
  → 判定：需要外部工具
```

**触发条件**：任何包含"专利"、"patent"、"知识产权"、"IP"、"prior art"、
"FTO"、"landscape" 等关键词 + 查询/分析意图的输入。

### Step 2 — Skill Marketplace 搜索

```
WorkBuddy Agent 向 Marketplace 发起搜索：
  query = "专利搜索 专利分析 patent"
  
Marketplace 返回候选：
  ┌─────────────────────────────────────────────┐
  │ Patent MCP Server  ★ 4.8 (127)              │
  │ 搜索和分析 1.4 亿+ 全球专利                  │
  │ 10 工具 · 免费 · 无认证 · MIT 协议           │
  │ deeparchi-ai/patent-mcp-server               │
  │ ⚡ 匹配度：95%（专利分析 + 竞争情报）         │
  └─────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────┐
  │ CNIPA Patent Search  ★ 3.2 (15)             │
  │ 中国国家知识产权局专利检索                    │
  │ 仅中国大陆专利 · 需要 API Key                │
  └─────────────────────────────────────────────┘
  ┌─────────────────────────────────────────────┐
  │ IPQWIKI  ★ 4.1 (43)                         │
  │ 知识产权百科查询                              │
  │ 信息查询 · 免费 · OAuth                       │
  └─────────────────────────────────────────────┘
```

**Agent 的自动决策逻辑**：

| 评估维度 | Patent MCP | CNIPA | IPQWIKI |
|---------|-----------|-------|---------|
| 任务匹配度 | 95%（搜索+分析+引证） | 40%（仅搜索） | 20%（百科非分析） |
| 安装门槛 | 零（无认证/免费） | 中（需 API Key） | 中（需 OAuth） |
| 数据覆盖 | 140M+ 全球 | 仅 CN | 不适用 |
| 评分 | 4.8 | 3.2 | 4.1 |
| **→ 决策** | ✅ **自动推荐** | ❌ | ❌ |

**关键设计**：Agent 优先推荐**零门槛工具**。Patent MCP 的 `auth: none` + `pricing: free` 
意味着 Agent 可以直接安装，不需要打断用户去填写 API Key 或付费。

### Step 3 — 自动评估与安装

```
WorkBuddy Agent 读取 agent-card.json：

  {
    "name": "Patent MCP Server",
    "use_cases": [
      "Competitor patent portfolio analysis",
      "Technology landscape mapping",
      ...
    ],
    "auth": "none",          ← 零门槛
    "pricing": "free",       ← 零成本
    "mcp_config": {
      "transport": "sse",
      "url": "..."
    },
    "limitations": [
      "BigQuery 1 TB/month free",
      "~200ms latency from Asia-Pacific",
      ...
    ]
  }

Agent 内部判定：
  ✓ 匹配用户任务（专利搜索+分析）
  ✓ 安装零风险（无认证、无费用、公开数据）
  ✓ 能力覆盖充分（10 工具覆盖搜索/详情/引证/法律状态）
  → 自动安装或征求一键确认（取决于用户偏好设置）
```

**确认策略**（用户可在 WorkBuddy 设置中调整）：
- **默认模式**（推荐）：首次安装需一键确认（"要安装 Patent MCP Server 吗？[安装]"）
- **自动模式**：评分 ≥4.5 + 免费 + 无认证的工具自动安装，无需确认
- **严格模式**：任何新工具安装都需确认

### Step 4 — 任务拆解与工具编排

```
用户任务："华为 AI 芯片核心专利 + 被引情况"

WorkBuddy Agent 拆解为工具调用链：

  search_patents(query="AI chip", assignee="HUAWEI")
  → 返回 12 件专利号

  batch_get_patents(["CN110286864A", "CN108668027A", ...])
  → 获取每件的标题、摘要、分类、日期

  batch_get_cited_by(["CN110286864A", "CN108668027A", ...])
  → 获取每件的被引次数和引用者

  competitor_citation_matrix(
    publication_numbers=["CN110286864A", ...],
    competitor_keywords=["Apple", "Samsung", "Qualcomm", "Intel"]
  )
  → 竞争者引证矩阵
```

**编排逻辑**：
1. 先并行搜索（多个查询变体）
2. 取 Top-N 结果，批量获取详情 + 被引信息（并行）
3. 可选：竞争引证矩阵
4. 汇总 → 自然语言呈现

### Step 5 — 结果渲染

```
WorkBuddy 收到结构化数据，渲染为：

┌──────────────────────────────────────────────────┐
│ 📊 华为 AI 芯片 — 核心专利分析                    │
│                                                    │
│ 共检索到 12 件相关专利，按被引次数排列：           │
│                                                    │
│ 🥇 CN110286864A                                    │
│    神经网络计算芯片架构                            │
│    ⏱ 2021-03 申请 · 2024-03 授权                  │
│    📎 被 47 件专利引用                             │
│    🏢 引用者：Apple (3), Samsung (2), Intel (2)   │
│                                                    │
│ 🥈 CN108668027A                                    │
│    AI 芯片互联方法                                 │
│    ⏱ 2020-09 申请 · 审查中                        │
│    📎 被 31 件引用                                 │
│    🏢 引用者：Qualcomm (4), TSMC (1)              │
│                                                    │
│ 🥉 CN111079911A                                    │
│    稀疏神经网络加速器                              │
│    ⏱ 2021-08 申请 · 2024-06 授权                  │
│    📎 被 28 件引用                                 │
│                                                    │
│ ─────────────────────────────────────              │
│ 📈 引证趋势：近 2 年加速增长                       │
│ ⚠️  3 件仍在审查中，存在授权不确定性               │
│ 🔗 完整竞争引证矩阵 → [查看]                       │
└──────────────────────────────────────────────────┘
```

### Step 6 — 状态持久化与会话记忆

```
WorkBuddy 自动记录：
  ✓ Patent MCP Server 已安装（下次直接用）
  ✓ 本次查询历史：华为 + AI 芯片
  ✓ 用户关注的核心专利号：[CN110286864A, ...]

下次用户说 "昨天华为那几个专利的法律状态"：
  → Agent 从会话记忆中恢复专利号列表
  → 直接调用 get_legal_status(["CN110286864A", ...])
  → 不需要重新搜索
```

---

## 三、异常路径设计

### 异常 1：工具调用超时

```
WorkBuddy：正在查询全球专利数据库...
         （8 秒后）
         ⚠️ 查询时间较长，可能是因为检索范围较大。
         要我缩小范围继续，还是等待完整结果？
         [缩小范围] [继续等待]
```

### 异常 2：BigQuery 配额耗尽

```
WorkBuddy：⚠️ 本月专利查询额度已用完（1 TB）。
         查询将于下月 1 日自动恢复。
         如需继续使用，可联系管理员升级配额。
         
         不过，我可以尝试通过 Google Patents 网页
         直接查询（速度较慢但不受配额限制），
         要我试试吗？[试试网页版] [等待下月]
```

### 异常 3：Google Patents 503

```
WorkBuddy：⚠️ 专利详情查询暂时遇到波动（Google Patents
         服务器繁忙），已自动重试 3 次仍未成功。
         
         搜索结果可用（来自 BigQuery），你可以先查看
         基本信息。详情和引证数据稍后重试。
         [先看搜索结果] [稍后重试]
```

### 异常 4：网络不可达

```
WorkBuddy：⚠️ 无法连接到 Patent MCP Server。
         请检查网络连接或联系 IT 管理员。
         
         错误详情：Connection timeout to
         patent-mcp-494814528402.us-central1.run.app
```

---

## 四、Agent-Card 需要补充的内容

当前 agent-card 对开发者友好，但对 **Agent 自动判断**还需要补充：

```json
{
  // ===== 现有字段（已足够）=====
  "name": "Patent MCP Server",
  "description": "...",
  "use_cases": [...],
  "mcp_config": {...},
  "auth": "none",
  "pricing": "free",
  "tools": 10,
  "limitations": [...],

  // ===== 新增字段（Agent 自动决策用）=====

  // 1. 触发词：Agent 判断"用户任务是否需要这个工具"
  "triggers": {
    "keywords": [
      "专利", "patent", "知识产权", "IP", "intellectual property",
      "prior art", "现有技术", "FTO", "freedom to operate",
      "patent landscape", "专利布局", "patent portfolio",
      "patent citation", "专利引用", "patent family", "同族专利",
      "legal status", "法律状态", "claims", "权利要求",
      "competitor patent", "竞争专利", "patent analysis"
    ],
    "intents": [
      "patent_search",
      "patent_analysis",
      "competitor_intelligence",
      "ip_due_diligence",
      "technology_landscape"
    ],
    "user_roles": [
      "patent_attorney",
      "ip_manager",
      "legal_counsel",
      "r_and_d_engineer",
      "investment_analyst",
      "m_and_a_advisor"
    ]
  },

  // 2. 能力矩阵：Agent 判断"这个工具有没有我需要的能力"
  "capabilities": {
    "search": {
      "scope": "global",
      "coverage": "140M+ patents",
      "jurisdictions": ["CN", "US", "EP", "JP", "KR", "WO", "..."],
      "search_modes": ["keyword", "assignee", "CPC_classification", "date_range"]
    },
    "detail": {
      "fields": ["title", "abstract", "claims", "classifications",
                 "citations", "inventors", "assignees", "family_id",
                 "filing_date", "grant_date", "priority_date"]
    },
    "analysis": {
      "citation_graph": true,
      "competitor_matrix": true,
      "family_analysis": true,
      "legal_status_tracking": true
    }
  },

  // 3. 性能声明：Agent 设定用户预期
  "performance": {
    "typical_latency_ms": 2000,
    "worst_case_latency_ms": 15000,
    "concurrent_limit": 10,
    "monthly_quota": "1 TB BigQuery sandbox"
  },

  // 4. 互操作性：Agent 判断兼容性
  "interop": {
    "mcp_version": "2024-11-05",
    "transport": ["sse"],
    "requires": [],
    "conflicts_with": []
  },

  // 5. 质量信号
  "quality": {
    "test_coverage": "10/10 tools verified",
    "uptime": "99.5%",
    "github_stars": 0,
    "last_updated": "2026-07-04"
  },

  // 6. 安装指令（Agent 可执行的）
  "install": {
    "type": "mcp_remote",
    "steps": [
      {
        "action": "add_mcp_server",
        "config": {
          "patent-mcp": {
            "url": "https://patent-mcp-494814528402.us-central1.run.app/sse/"
          }
        }
      }
    ],
    "verify": {
      "action": "list_tools",
      "expect": "10 tools available"
    }
  }
}
```

---

## 五、WorkBuddy Marketplace 需要的注册信息

如果 WorkBuddy 有自己的 Skill Marketplace 注册流程（类似 MCP.so 的 GitHub Issue 方式），需要提交：

```yaml
# WorkBuddy Skill Marketplace 注册表单（假设格式）

name: Patent MCP Server
name_zh: 专利 MCP 服务器
category: 企业服务 / 知识产权
icon_url: https://raw.githubusercontent.com/deeparchi-ai/patent-mcp-server/main/docs/icon.png

short_description: 搜索分析 1.4 亿+ 全球专利
short_description_zh: 搜索和分析 1.4 亿+ 全球专利数据

description: |
  基于 Google Patents BigQuery 的专利搜索与分析工具。
  - 全球专利搜索（关键词/公司/分类号）
  - 专利详情与权利要求查询
  - 法律状态追踪
  - 同族专利分析
  - 竞争引证矩阵
  - 双向引证图谱
  适合 IP 律师、企业法务、R&D 团队的专利分析需求。

tags:
  - 专利
  - 知识产权
  - 竞争情报
  - 法律科技
  - 研发

pricing: 免费
auth_required: false
privacy: 仅查询公开数据，不存储用户查询记录

mcp_endpoint: https://patent-mcp-494814528402.us-central1.run.app/sse/
agent_card: https://patent-mcp-494814528402.us-central1.run.app/.well-known/agent-card.json

support:
  github: https://github.com/deeparchi-ai/patent-mcp-server
  email: kuangmi@deeparchi.com.cn

# 兼容性声明
works_with:
  - claude_desktop
  - cursor
  - workbuddy        # ← 声明兼容
  - custom_mcp_client
```

---

## 六、从设计到落地的 GAP 分析

| 需要的东西 | 现状 | 差距 | 优先级 |
|-----------|------|------|--------|
| WorkBuddy Skill Marketplace 开放 MCP | 未确认 | 不确定何时开放 | ⚠️ 阻塞 |
| Agent-Card 补充字段（triggers/capabilities/install） | 未实现 | 需 patch server.py | P1 |
| WorkBuddy 飞书桥接（Plan B） | Hermes 已在线 | 需写触发规则 | P1 |
| 用户测试（找一位 IP 律师试走流程） | 无 | 需找人 | P2 |
| WorkBuddy Marketplace 注册 | 不适用（未开放） | 等开放 | P3 |

---

## 七、决策记录

| 决策 | 理由 |
|------|------|
| 首次安装需一键确认（非自动） | 企业用户对"自动安装"有安全顾虑；一键确认成本极低 |
| agent-card 增加 triggers 字段 | Agent 需要"触发词"来判断匹配度，不能仅靠 description |
| 保留飞书桥接为 Plan B | WorkBuddy MCP 开放时间不确定，飞书桥接今天就能跑 |
| 异常路径区分"可降级"和"硬失败" | BigQuery 满→可降级网页查询；503→可降级部分结果；网络不通→无法降级 |
