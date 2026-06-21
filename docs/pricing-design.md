# Patent MCP 收费模式设计

> ⚠️ **STATUS: ON HOLD (2026-06-21)**
> 基于「上游模型吞噬」压力测试（详见 devils-advocate.md 挑战 9），Pro/Starter/Business 等订阅层级计划 **暂停**。
>
> **决策依据：**
> 1. 上游吞噬使 1-2 年内独立商业产品窗口不确定
> 2. Free→Paid 转化率接近零（DA #6）
> 3. PatSnap 免费 MCP 结构性压制（DA #8）
> 4. 开源 MIT MCP 的心智占领价值 > 月度订阅收入
>
> **替代策略：** 永久免费 MIT 开源 + 「心智占领」指标驱动。
> 收入来自上层应用（专利监控 bot、Alert 系统），而非 MCP 工具本身。

---

> 对标 Firecrawl Credit-Based 订阅制，结合专利场景三柱产品架构
> 设计时间：2026-06-19 · 暂停 2026-06-21

## 计费单元：PQC (Patent Query Credit) — 概念保留，暂不实施

| 操作 | PQC | 理由 |
|------|-----|------|
| `search_patents` | 1 | BigQuery ~15GB |
| `get_patent` (Web) | 0.1 | 零边际成本 |
| `get_patent` (BQ回退) | 0.5 | ~2.5GB |
| `get_patent_claims` (Web) | 0.1 | 零边际成本 |
| `get_patent_claims` (BQ回退) | 3 | ~35.7GB |

## 订阅层级 — ON HOLD

| 层级 | 价格/月 | PQC/月 | 状态 |
|------|---------|--------|------|
| Free | $0 | 50 | ✅ 自部署免费 |
| Starter | $19 | 200 | ❌ ON HOLD |
| Pro | $79 | 2,000 | ❌ ON HOLD |
| Business | $299 | 10,000 | ❌ ON HOLD |
| Scale | $549 | 50,000 | ❌ ON HOLD |
| Enterprise | 议价 | 自定义 | ⚠️ 搁置 |

---

## 替代策略：心智占领指标体系 (2026-06-21)

> 代替原「四阶段付费转化路线图」。心智占领 > 月度收入。

### 核心指标

| # | 指标 | 当前 | Q3 2026 目标 | 为什么重要 |
|---|------|------|-------------|-----------|
| 1 | **GitHub Stars** | ~0 | 100+ | 「专利 MCP」品类第一 |
| 2 | **MCP Registry 上线数** | 2 | 5 | 每个 registry = 独立分发渠道 |
| 3 | **Agent 集成案例** | 1 (Hermes) | 5+ | 用户自发集成 > 自家宣传 |
| 4 | **CPC 校正表引用** | 0 | 3+ 外部引用 | 验证「CN 最准确 MCP」定位 |
| 5 | **Community Contributions** | 0 | 2+ 外部 PR | 从一个人→社区项目 |

### 不做的事

| 原计划 | 新决策 | 理由 |
|--------|--------|------|
| Pro $79/月订阅 | ❌ 放弃 | 上游吞噬；Free→Paid 无场景差异 |
| Starter $19/月 | ❌ 放弃 | 同上 |
| Business/Scale | ❌ 放弃 | 同上 |
| 托管 MCP Endpoint | ⚠️ 搁置 | 维持自部署 MIT |
| 监控 bot / Alert 产品 | ✅ 保留 | 上层应用，MCP 获客→上层变现 |
| 项目制导航咨询 | ✅ 保留 | ¥5-30万/项目，独立于 MCP 工具 |

### 一句话新定位

> **Patent MCP 是「专利领域的 SQLite」——薄、免费、嵌入 Agent 工作流、不持有数据。心智占领优先于变现。收费在上一层，不在工具层。**
