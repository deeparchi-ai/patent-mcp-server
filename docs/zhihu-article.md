# 为什么你的 AI Agent 搜不到中国专利？一份 CPC 校正表背后的故事

> 深度架构 · 邝谧

---

如果你把 `search_patents(cpc="H01L25/065", country="CN")` 发给 Agent，它会告诉你：**0 条结果。**

但 H01L25/065 是「先进封装/3D 堆叠」。中国是全球最大的先进封装市场。长电科技、通富微电、华天科技——每家都有数百件相关专利。几千条专利，BigQuery 说一条都没有。

这不是你的问题。是 BigQuery 的 CN CPC 映射有系统性偏差。

---

## 问题出在哪

BigQuery 的专利公开数据集（`patents-public-data.patents.publications`）是全球最大的免费专利数据源：1.4 亿条，CC-BY-4.0 协议，1TB/月免费查询。但 CPC 分类覆盖对 US/EP/WO 专利准确，对中国专利不完整。

具体来说：

- 精细 CPC 码（如 `H01L25/065`）对 CN 专利返回 0 条
- 关键词搜索也是废的。实测 `query="华为 芯片" + country=CN` → 0 条。`query="neural network" + country=CN` → 0 条
- **唯一的可靠搜索路径：用 CPC 大类，放弃精细子类**

这不是 BigQuery 的 bug。Google 的索引策略对英文专利做了深度分类，中文专利的 CPC 映射没有同步到同等精度。他们有 1.4 亿条数据，维护 CN 专利的几个百分点的偏差不是优先级。

但对于做中国专利搜索的人来说，这个「几个百分点的偏差」意味着你搜不到东西。

---

## CPC 大类速查：哪些码对中国专利有效

| CPC 大类 | 技术领域 | CN 覆盖 |
|----------|---------|---------|
| `H01L` | 半导体器件 | ✅ |
| `G06F` | 电子数字数据处理 | ✅ |
| `G06N` | AI 模型计算系统 | ✅ |
| `A61K` | 医用配制品 | ✅ |
| `C12N` | 微生物/酶/遗传工程 | ✅ |
| `B60W` | 混合动力车辆控制 | ✅ |

**正确用法：**

```
# 搜 2024 年以来中国 AI 专利
search_patents(cpc="G06N", country="CN", after="2024-01-01", limit=10)

# 搜中国半导体器件专利
search_patents(cpc="H01L", country="CN", after="2023-01-01")
```

---

## 我们做了一个开源工具来解决这个问题

Patent MCP Server——一个 MIT 协议的开源 MCP 服务器，让 AI Agent 直接查询全球专利。

三个工具：
- `get_patent` — 查专利详情（$0，走 Google Patents Web 抓取）
- `get_patent_claims` — 获取权利要求全文（$0）
- `search_patents` — 搜索 1.4 亿条专利（BigQuery 免费额度）

把上面那些 CPC 校正经验编码进了文档和工具描述里。发布了一份公开的 [CN 专利 CPC 校正表](https://github.com/deeparchi-ai/patent-mcp-server/blob/master/docs/cn-cpc-correction-table.md)，标记了哪些路径有效、哪些无效。

安装：

```bash
pip install deeparchi-patent-mcp
```

Agent 配置里加一行：

```yaml
mcp_servers:
  patent-mcp:
    command: "python"
    args: ["-m", "src.server"]
```

不需要 API Key。不需要注册。数据不出自己的机器。

---

## 几点诚实的说明

1. **中国专利的法律状态查不到。** CNIPA 没有提供可编程的免费 API。这是数据源头的问题，工具解决不了。
2. **中文原件权利要求不可得。** Google Patents 提供的是机器翻译的英文版本。
3. **这不是 PatSnap 替代品。** 如果你需要诉讼数据、专利价值评分、法律状态跟踪——你需要商业平台。Patent MCP 是基础设施，不是企业级分析工具。

---

GitHub: [deeparchi-ai/patent-mcp-server](https://github.com/deeparchi-ai/patent-mcp-server)
PyPI: `pip install deeparchi-patent-mcp`
