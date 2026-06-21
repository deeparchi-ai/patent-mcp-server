# Patent MCP Server：给 AI Agent 一双能读专利的眼睛

> 深度架构 · 邝谧 | 2026-06-21

---

如果你让 AI Agent "查一下这个专利"，它能做什么？

搜索网页、点开链接、读 HTML、从混乱的排版里猜哪个是标题哪个是发明人——最后还可能找错。不是因为模型不够聪明，是因为专利网页不是给机器读的。

**Patent MCP Server 解决的就是这个问题。** 它是一个 MCP（Model Context Protocol）服务器，让 AI Agent 直接查询全球专利数据库——结构化输出、零损耗消费、本地自部署。不需要 API Key，不需要付费订阅。

---

## 三个工具

| 工具 | 做什么 | 成本 |
|------|--------|------|
| `get_patent` | 查专利详情：分类号、引用（含 X/Y/A/D 现有技术标记）、发明人、权利人、同族 | $0（Web 路径） |
| `get_patent_claims` | 获取权利要求全文——专利保护的法律边界 | $0（Web 路径） |
| `search_patents` | 按技术领域、国家、时间范围搜索 1.4 亿条专利 | BigQuery 免费额度 |

Agent 拿到的是结构化数据，不是 HTML。不需要解析字段、不需要处理编码——直接进入推理链路。

**示例：**

```
Agent: get_patent("US-7650331-B1")
→ 返回：标题、发明人、分类号、16 条权利要求、X/Y/A/D 引用标记
→ Agent 直接分析：US-7650331-B1 被引用了 47 次，其中 3 次标记为 X（单独即可破坏新颖性）
```

---

## 中国专利：我们多做了一点

中国专利有 5400 万条。但 BigQuery 的 CPC 分类覆盖对 CN 专利存在系统性偏差。精细编码如 `H01L25/065`（先进封装）对 CN 专利返回 0 条结果——实际上中国有数千件。关键词搜索也不行（中文文本索引稀疏）。

Patent MCP 发布了一份公开的 [**CN 专利 CPC 校正表**](https://github.com/deeparchi-ai/patent-mcp-server/blob/master/docs/cn-cpc-correction-table.md)，记录了已知的 CPC 编码偏差和经过验证的替代路径。如果你在中国做技术研发，这份表会帮你少走很多弯路。

---

## 快速开始

```bash
git clone https://github.com/deeparchi-ai/patent-mcp-server.git
cd patent-mcp-server
pip install -e .
```

在 Agent 配置里加一行：

```yaml
# Claude Desktop / Cursor / Hermes Agent
mcp_servers:
  patent-mcp:
    command: "python"
    args: ["-m", "src.server"]
```

80% 的场景——查专利详情和权利要求——走 Google Patents Web 路径。零成本，零配置，不需要任何密钥。

---

## BigQuery 搜索配置（可选）

如果需要 `search_patents`（按技术领域、国家、时间范围搜索 1.4 亿条专利），需要一个 Google Cloud 项目：

**1. 创建 GCP 项目并启用 BigQuery**

前往 [Google Cloud Console](https://console.cloud.google.com/)，创建一个项目（免费），在 API 和服务中启用 BigQuery API。

**2. 创建服务账号并下载密钥**

IAM 与管理 → 服务账号 → 创建服务账号。分配 BigQuery User 角色。创建 JSON 密钥，下载到本地。

**3. 配置环境变量**

复制项目中的 `run.sh.example` 为 `run.sh`，填入你的项目 ID 和密钥路径：

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your-key.json"
export GCP_PROJECT_ID="your-project-id"
```

**4. 验证**

```bash
# 搜索 2024 年以来中国 AI 领域的专利
search_patents(cpc="G06N", country="CN", after="2024-01-01", limit=10)
```

BigQuery 提供 **1TB/月免费查询额度**。`get_patent` 和 `get_patent_claims` 不消耗这个额度（走 Web 路径）。个人使用基本上永远免费。

---

## 谁在用

- **AI 开发者**——Agent 需要可靠专利数据。PyPI 直接安装，`pip install deeparchi-patent-mcp`。
- **R&D 工程师**——提交发明交底书前先查一下有没有类似专利。比手动翻 Google Patents 快一个数量级。
- **独立发明人**——自部署、免费、数据不出自己的机器。
- **小型 IP 团队**——需要专利检索，但不需要 $10,000/年的企业级平台。

---

## 架构

```
AI Agent → Patent MCP Server → Google Patents（查详情，Web 抓取）
                               → BigQuery（搜索 1.4 亿条，可选）
```

MIT 协议。永远免费。

---

> **Patent MCP Server** — 让 AI Agent 能读专利。
>
> GitHub: [deeparchi-ai/patent-mcp-server](https://github.com/deeparchi-ai/patent-mcp-server)
> PyPI: `pip install deeparchi-patent-mcp`
