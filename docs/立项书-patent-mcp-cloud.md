# Patent MCP HTTP 云部署 — 立项书

> **项目代号**：patent-mcp-cloud
> **日期**：2026-07-04（修订版）
> **作者**：深度架构 · 邝谧
> **状态**：立项
> **版本**：v2 — 基于代码库实际状态校正

---

## 1. 项目概述

### 1.1 一句话目标

将 `deeparchi-patent-mcp`（v1.8.0，MIT 开源，PyPI 2,200+ 下载）从本地 pip install 模式升级为 HTTPS 云服务，并 PR 进 Anthropic 官方 `claude-for-legal`（8.6K stars），让全球律师在 Claude Code/Cowork 中零安装使用专利搜索。

### 1.2 背景

| 维度 | 现状 | 目标 |
|------|------|------|
| 部署方式 | 用户手动 `pip install` + 本地起进程 | HTTPS URL，零安装 |
| 传输协议 | stdio（默认） / HTTP（已支持 `--transport http`） | HTTP/SSE，云端 |
| 用户群 | 技术用户（开发者、有 Python 环境的律师） | 全体律师（Claude Cowork 插件一键连接） |
| 生态位 | PyPI 独立包 | Anthropic 官方 IP 法律插件内置 MCP |
| 竞品参考 | ip-legal 已有 Solve Intelligence 专利 MCP（HTTPS，商业） | 开源替代 — **唯一免费的全球专利搜索 MCP** |

### 1.3 产品定位

- **不做 SaaS 订阅**——保持 MIT 开源，云部署是**公共基础设施**，不是商业服务
- **只做 patent MCP 这一个点**——不扩展到 copyright/trademark（那是 ip-legal 插件其他部分的事）
- **对标 Solve Intelligence**——ip-legal 现有的专利 MCP 是商业 API，patent-mcp-server 是开源等价替代
- **ip-legal 的 CONNECTORS.md Wanted 清单**明确列出需要 USPTO/IP 管理系统 MCP 连接器，目前只有一个商业方案（Solve Intelligence）——我们是唯一免费的全球专利搜索 MCP，门槛为零

### 1.4 当前代码库状态

| 项目 | 值 |
|------|-----|
| 版本 | v1.8.0 |
| 工具数 | **10 个** MCP 工具 |
| 数据源 | BigQuery（primary）+ Google Patents 爬虫（web）+ SearXNG/Firecrawl（CN fallback） |
| 传输 | stdio + HTTP/SSE（Starlette + uvicorn，已实现） |
| 代理依赖 | Google Patents 爬虫**强制依赖本地 Clash 代理**（`PROXIES` 已硬编码，always on） |

---

## 2. 项目范围

### 2.1 云端能力分级

代码库的 10 个工具按云端可用性分为三档：

#### 第一档：BigQuery 原生（云端直接可用）
| 工具 | 数据源 | 云端状态 |
|------|--------|:---:|
| `search_patents` | BigQuery + SearXNG/Firecrawl fallback | ✅ 直接可用 |
| `get_patent` | BigQuery（web 失败时 fallback） | ✅ 直接可用 |
| `get_patent_family` | BigQuery only | ✅ 直接可用 |
| `batch_get_patents` | BigQuery（web 失败时 fallback） | ✅ 直接可用 |

#### 第二档：需要 BigQuery 降级适配（当前依赖代理，需改造）
| 工具 | 数据源 | 问题 | 改造方向 |
|------|--------|------|----------|
| `get_patent_claims` | Google Patents 爬虫 only | 强制代理，云端不可用 | 从 BigQuery `claims` 字段取（如有）；或移除该工具 |
| `get_legal_status` | Google Patents 爬虫 only | 强制代理，云端不可用 | 从 BigQuery `legal_status` 字段取（如有） |

#### 第三档：纯 Google Patents 爬虫（云端不可用，移除）
| 工具 | 原因 |
|------|------|
| `get_cited_by` | 爬 Google Patents cited-by 页面 — 无 BigQuery 等价替代 |
| `batch_get_cited_by` | 同上 |
| `competitor_citation_matrix` | 依赖 `get_cited_by` 链 |
| `bidirectional_citation_graph` | 依赖 Google Patents 搜索 + `get_cited_by` 链 |

### 2.2 范围内（In Scope）

| 序号 | 交付物 | 说明 |
|------|--------|------|
| D0 | **Google Patents 依赖解耦** | 重构 server.py：云端模式自动禁用 web 工具（第三档），Claims/Legal Status 增加 BigQuery fallback |
| D1 | **Dockerfile + 镜像** | 多阶段构建，bundle `gcp-key.json`，禁用代理环境变量 |
| D2 | **CloudBase Cloud Run 部署** | 环境 `qunling-001`，拿到稳定 HTTPS URL |
| D3 | **健康检查 & 成本监控** | BigQuery 免费额度（1TB/月）用量看板 + 告警 |
| D4 | **6 个核心工具云端可用** | 第一档（4 个）+ 第二档改造（2 个）= 6 个工具 |
| D5 | **PR to `anthropics/claude-for-legal`** | 修改 `ip-legal/.mcp.json`，新增 `patent-mcp` 条目 |
| D6 | **PR 描述 + 使用说明** | 英文 README 片段，解释这个 MCP 做什么、怎么验证 |

### 2.3 范围外（Out of Scope）

- ❌ **第三档 4 个工具（citation graph / competitor matrix）**——纯 Google Patents 爬虫，无 BigQuery 等价数据源，云端直接移除
- ❌ **用户认证 / API Key 管理**——公共基础设施，v1 不设鉴权
- ❌ **多租户隔离**
- ❌ **商业定价 / 付费墙**——MIT 开源
- ❌ **CI/CD 自动化部署**——手动部署，先跑通
- ❌ **SLA 承诺**——开源社区贡献，非商业服务

---

## 3. 关键约束与设计决策

### 3.1 Google Patents 爬虫 = 云端不可用（已确认，非风险）

这是**已确认约束**，不再是风险。证据：

1. `src/web/google_patents.py:42` — `PROXIES` 字典通过 `if os.environ.get("HTTPS_PROXY") or True` 强制启用，即使未设环境变量也会 fallback 到 `http://127.0.0.1:7897`（Clash Verge）
2. 代码注释第 37 行明确标注：`"Proxy for Google Patents (direct access blocked by CAPTCHA 2026-06-24)"`
3. Cloud Run 出口 IP 无法访问本地 Clash 代理，也无法保证不被 Google 限流

**设计决策**：
- 云端部署时通过环境变量 `PATENT_DEPLOY_MODE=cloud` 触发**精简模式**
- 精简模式下：第一档工具正常，第二档增加 BigQuery fallback，第三档不注册
- `get_patent` / `batch_get_patents` 的 "web first" 策略改为 "BigQuery only"（跳过 web fetch 尝试，避免超时）

### 3.2 GCP 凭证 bundle

- 文件名：`gcp-key.json`
- 方式：Docker build arg → 容器内 `/secrets/gcp-sa.json`
- 权限：只读 BigQuery 的受限 SA
- 不写入源码仓库

### 3.3 Firecrawl 作为 CN 搜索 fallback

- `FIRECRAWL_API_KEY` 已硬编码默认值在 `google_patents.py:33`
- 环境变量可覆盖
- Cloud Run 环境变量注入（不写在 Dockerfile）

### 3.4 BigQuery 免费额度守卫

```
免费额度：1 TB / 月
单次 search_patents 查询：2–10 GB（取决于 CPC 范围）
安全上限：~100 次搜索/月
已有保护：BigQueryClient 内置 dry-run 50GB 上限（代码中 BigQueryCostError）
追加保护：环境变量 GCP_PROJECT_ID 控制查询 project
监控：GCP Console → BigQuery → Monitoring
告警：800 GB（黄）/ 950 GB（红）
```

---

## 4. 技术方案

### 4.1 架构总览

```
Claude Code / Cowork (律师桌面)
        │
        ▼
anthropics/claude-for-legal / ip-legal 插件
        │  .mcp.json 中引用
        ▼
https://patent-mcp-xxx.ap-shanghai.run.app/sse   ← Cloud Run (CloudBase)
        │
        ├── GET /sse          → SSE 长连接
        ├── POST /messages    → MCP JSON-RPC
        └── GET /health       → 健康检查
        │
        ▼
Python MCP Server (starlette + uvicorn)
        │  PATENT_DEPLOY_MODE=cloud
        │
        ├── ✅ search_patents     ──→ BigQuery (GCP 凭证 bundle)
        ├── ✅ get_patent         ──→ BigQuery (直接，跳过 web)
        ├── ✅ get_patent_family  ──→ BigQuery
        ├── ✅ batch_get_patents  ──→ BigQuery (直接，跳过 web)
        ├── 🔧 get_patent_claims  ──→ BigQuery claims 字段（待改造）
        ├── 🔧 get_legal_status   ──→ BigQuery legal_status 字段（待改造）
        └── ❌ 4 个 citation/web 工具 ──→ 不注册
```

### 4.2 Cloud Run 配置预估

| 参数 | 预估值 | 备注 |
|------|--------|------|
| 内存 | 512MB | Python 轻量服务，BigQuery 客户端内存占用小 |
| CPU | 1 vCPU | BigQuery 查询 + JSON 序列化 |
| 最小实例 | 0 | 无请求时缩零，节省成本 |
| 最大实例 | 3 | 避免 BigQuery 并发过高 |
| 超时 | 120s | BigQuery 复杂查询 |
| 并发 | 10 | 适度并发 |
| 环境变量 | `PATENT_DEPLOY_MODE=cloud`, `GCP_PROJECT_ID`, `FIRECRAWL_API_KEY` | 精简模式 + BigQuery fallback |

### 4.3 Dockerfile 设计

```dockerfile
# Stage 1: Build
FROM python:3.11-slim AS builder
COPY . /app
RUN pip install --no-cache-dir /app

# Stage 2: Runtime
FROM python:3.11-slim
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# GCP credentials (build-time arg)
COPY gcp-key.json /secrets/gcp-sa.json

ENV GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-sa.json
ENV PATENT_DEPLOY_MODE=cloud
ENV HTTPS_PROXY=""
EXPOSE 8080
CMD ["python", "-m", "src.server", "--transport", "http", "--port", "8080", "--host", "0.0.0.0"]
```

---

## 5. 里程碑

| 里程碑 | 目标 | 验收标准 | 估时 |
|--------|------|----------|------|
| **M0：代码适配** | Google Patents 解耦 | ✅ `PATENT_DEPLOY_MODE=cloud` 下 6 个工具可注册<br>✅ Claims/Legal Status 有 BigQuery fallback<br>✅ 4 个 web 工具不注册<br>✅ 本地 `docker run` 测试通过（不挂代理） | 1d |
| **M1：Docker 化** | Dockerfile + 构建 | ✅ `docker build` 成功<br>✅ 镜像大小 < 300MB<br>✅ `gcp-key.json` 正确 bundle | 0.25d |
| **M2：云部署** | CloudBase Cloud Run 上线 | ✅ `tcb cloudrun deploy` 成功<br>✅ HTTPS URL 可访问 `/sse`<br>✅ 6 个工具全通<br>✅ `/health` 返回 200 | 0.25d |
| **M3：监控上线** | BigQuery 用量看板 | ✅ GCP Console 监控图表可用<br>✅ 告警规则配置 | 0.25d |
| **M4：PR 准备** | 撰写 PR + 端到端验证 | ✅ fork `anthropics/claude-for-legal`<br>✅ 本地 Claude Code 加载 ip-legal + patent-mcp<br>✅ 端到端测试：搜索 "近两年 TSMC 的芯片专利" | 0.25d |
| **M5：提交 PR** | 向 upstream 提交 | ✅ PR 描述完整<br>✅ 通过 CLA check<br>✅ 响应 reviewer 反馈 | 0.25d |

**总估时：2.25 个工作日**（含 M0 代码适配 1 天；不含 PR review 等待）

---

## 6. 风险矩阵

### 6.1 已确认约束（非风险）

| 约束 | 说明 |
|------|------|
| Google Patents 爬虫云端不可用 | 已确认。应对：云端精简模式，移除 4 个 web-only 工具，Claims/Legal Status 增加 BigQuery fallback |

### 6.2 剩余风险

| # | 风险 | 严重度 | 概率 | 影响 | 缓解措施 |
|---|------|:---:|:---:|------|----------|
| R1 | **BigQuery 免费额度超支**——被恶意调用或自身 bug | 🟡 中 | 低 | 1TB 用完后开始计费（$5/TB） | 已有 dry-run 50GB 上限；GCP 账单告警；考虑增加调用频率限制 |
| R2 | **Cloud Run 冷启动延迟**——缩零后首次请求 5-30s | 🟠 低 | 中 | 用户体验差，可能被 reviewer 质疑 | 设置 min-instance=1；优化镜像大小；文档说明 |
| R3 | **PR 被 Anthropic 拒绝** | 🟡 中 | 中 | 无法进入官方插件生态 | 先以 issue 探路；备选：作为独立 Claude Code plugin 分发；HTTPS URL 本身已降门槛 |
| R4 | **Claims/Legal Status BigQuery 数据不全**——BigQuery 的 claims 字段可能不如 Google Patents 页面完整 | 🔵 边界 | 中 | 两个工具输出质量下降 | M0 阶段验证 BigQuery schema；如果不可用，这两个工具也降级移除 |

### 6.3 风险应对优先级

```
关注顺序：R4 > R1 > R2 > R3
```

R4 需要在 M0 启动时就验证——如果 BigQuery 的 claims/legal_status 字段覆盖不足，第二档两个工具也直接移除，云端精简为 4 个核心工具。

---

## 7. 成功指标

### 7.1 技术指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| Cloud Run 可用性 | > 99%（观测值，非 SLA） | `/health` endpoint 定时探测 |
| `search_patents` 响应时间 | P95 < 15s | BigQuery 查询耗时 |
| `get_patent` 响应时间 | P95 < 3s | 服务端日志 |
| BigQuery 月用量 | < 500 GB（免费额度 50%） | GCP Monitoring |
| 镜像大小 | < 300MB | `docker images` |

### 7.2 社区指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| PR 被 merge | ✅ yes/no | GitHub |
| 日均调用量 | 先上线，后设 baseline | Cloud Run metrics |
| 外部反馈 | 至少一次外部 issue/star | GitHub |

### 7.3 不追求但欢迎的

- GitHub stars 增长
- 其他 MCP client（Cursor/Windsurf）主动适配
- 律师社区自发推荐

---

## 8. 附录

### 8.1 代码库工具全景

| # | 工具 | 数据源 | 云端可用性 |
|---|------|--------|:---:|
| 1 | `search_patents` | BigQuery + SearXNG/Firecrawl | ✅ 第一档 |
| 2 | `get_patent` | Web → BigQuery fallback | ✅ 第一档 |
| 3 | `get_patent_family` | BigQuery | ✅ 第一档 |
| 4 | `batch_get_patents` | Web → BigQuery fallback | ✅ 第一档 |
| 5 | `get_patent_claims` | Google Patents web only | 🔧 第二档 |
| 6 | `get_legal_status` | Google Patents web only | 🔧 第二档 |
| 7 | `get_cited_by` | Google Patents web only | ❌ 第三档 |
| 8 | `batch_get_cited_by` | Google Patents web only | ❌ 第三档 |
| 9 | `competitor_citation_matrix` | Google Patents web only | ❌ 第三档 |
| 10 | `bidirectional_citation_graph` | Google Patents web only | ❌ 第三档 |

### 8.2 竞品参考：ip-legal 现有专利 MCP

ip-legal 的 `.mcp.json` 已包含一个专利 MCP：

```json
"Solve Intelligence": {
  "type": "http",
  "url": "https://api.solveintelligence.com/mcp/",
  "title": "Solve Intelligence",
  "description": "Patent workflows — search patent and non-patent literature, legal texts, SEP technical standards, prior art, claim analysis."
}
```

**差异化**：Solve Intelligence 是商业 SaaS，patent-mcp-server 是开源 MIT，底层数据源是 Google Patents 公开数据集（BigQuery），不依赖第三方商业 API。ip-legal 的 CONNECTORS.md Wanted 清单明确需要更多选择。

### 8.3 PR 目标格式

```json
"Patent MCP (DeepArchi)": {
  "type": "http",
  "url": "https://patent-mcp-xxx.ap-shanghai.run.app/sse",
  "title": "Patent MCP (DeepArchi)",
  "description": "Open-source global patent search — 140M+ patents via Google Patents BigQuery. Search, retrieve, claims, legal status, and patent family. MIT licensed. Zero-cost, no API key required."
}
```

### 8.4 环境信息

| 项目 | 值 |
|------|-----|
| 代码库 | ~/patent-mcp-server（v1.8.0, 10 tools） |
| PyPI | deeparchi-patent-mcp v1.8.0 |
| CloudBase 环境 | qunling-001（体验版，Normal） |
| 区域 | ap-shanghai |
| GCP 凭证 | gcp-key.json |
| 依赖 | Python >=3.10, mcp, google-cloud-bigquery, starlette, uvicorn, requests, pydantic |
