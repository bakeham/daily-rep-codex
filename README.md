# AI News Pusher PoC

一个 Python 3.11+ 轻量 PoC，用于定时采集 RSS / REST API 资讯源，统一标准化为 `NewsItem`，去重、规则初筛、OpenAI-compatible LLM 二次摘要与评分，生成 Markdown 人工审核稿，并在人工确认后推送到企业微信群机器人。

> 当前阶段不包含 Web UI、数据库服务或复杂后台；状态以本地 JSON 文件保存，便于后续替换为 SQLite。

## 核心流程

```text
RSS / REST API
  → 统一采集
  → 标准化 NewsItem
  → 去重
  → 规则初筛和 rule_score
  → DeepSeek v4 flash / OpenAI-compatible LLM 评分和摘要
  → final_score 排序
  → 生成 Markdown 人工审核稿
  → 人工确认后推送企业微信
```

`generate` 阶段只生成 `review/YYYYMMDD.md`，不会自动推送。只有 `send --file review/YYYYMMDD.md` 才会读取人工审核后的 Markdown 并推送。

## 文件结构

```text
.
├── README.md
├── requirements.txt
├── config.yaml
├── main.py
├── .env.example
├── .gitignore
├── data/      # 运行时自动创建，保存 state.json，默认不提交
└── review/    # 运行时自动创建，保存人工审核稿，默认不提交
```

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置密钥

复制 `.env.example`：

```bash
cp .env.example .env
```

然后只在本地 `.env` 中填写真实值：

```env
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=deepseek-v4-flash
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key_here
```

安全要求：

- 真实 API key 和企业微信 webhook **只能写在本地 `.env` 或环境变量中**。
- `.env` 已写入 `.gitignore`，不要提交。
- 不要把真实 key 写进 `README.md`、`config.yaml`、代码、日志或测试输出。
- 程序会隐藏 API key，并只以脱敏形式显示企业微信 webhook。

## 默认 Source

`config.yaml` 默认包含两个示例源：

1. RSS：`https://imjuya.github.io/juya-ai-daily/rss.xml`
2. REST：`https://aihot.virxact.com/api/public/items`

注意：AI HOT 的 `https://aihot.virxact.com/openapi.yaml` 是 OpenAPI schema 描述文件，不是实际资讯接口；实际采集应配置为 `/api/public/items` 或其他公开 endpoint。默认配置已使用 `/api/public/items`，并在配置注释中保留说明。

## 命令

### 1. 测试资讯源

```bash
python main.py test-sources
```

输出每个启用 source 的可访问性、解析条数和第一条样例。某个 source 失败不会影响其他 source 的测试。

### 2. 测试 LLM

```bash
python main.py test-llm
```

使用内置模拟资讯测试 OpenAI-compatible LLM 是否能返回 JSON。输出包括：

- LLM 连接是否成功
- 模型名
- 返回 JSON
- JSON 解析是否成功
- `qa_related` 是否为 true

不会打印 API key。

### 3. 生成 Markdown 人工审核稿

```bash
python main.py generate
```

生成类似：

```text
review/20260529.md
```

Markdown 包含：

- `## 本次筛选概览`
- `## 推荐推送内容`
- `rule_score` / `llm_score` / `final_score`
- `是否测试工程师相关 qa_related`
- `推荐理由`
- `摘要`
- `对我的参考价值`
- `## 被过滤但可人工恢复的内容`

如果没有强相关测试工程师内容，会显式写入：

```markdown
## 测试工程师相关内容缺失提醒
```

### 4. 人工审核

打开 `review/YYYYMMDD.md`：

- 删除不想推送的条目。
- 可以修改标题、摘要、推荐理由、参考价值。
- 如果想恢复被过滤文章，把文章块移动到 `## 推荐推送内容` 下。
- `send` 阶段只会把 `## 推荐推送内容` 下的文章解析为 News 图文卡片。
- `## 被过滤但可人工恢复的内容` 和 `## 测试工程师相关内容缺失提醒` 不会自动进入 News 图文卡片，除非人工移动到推荐区。

### 5. 推送企业微信

```bash
python main.py send --file review/20260529.md
```

默认 `markdown_plus_news`：

1. 先发送 Markdown 摘要。
2. 再发送 News 图文卡片，默认最多 3 篇。
3. 推送成功后更新 `data/state.json` 中对应文章的 `pushed_at`，避免后续重复推送。

### 6. 测试企业微信 webhook

```bash
python main.py test-wecom
```

发送一条最小 Markdown 连通性测试消息。不会打印完整 webhook URL。

## 企业微信推送模式

在 `config.yaml` 修改：

```yaml
wecom:
  mode: markdown_plus_news
```

支持三种模式：

- `markdown_only`：只发送 Markdown 摘要。
- `news_only`：只发送 News 图文卡片。
- `markdown_plus_news`：先发送 Markdown 摘要，再发送 News 图文卡片。

News 图文卡片数量由以下配置控制：

```yaml
wecom:
  news_top_n: 3
```

Markdown 超长时会按 `markdown_chunk_max_chars` 分片发送，并尽量按文章段落切分。

## 扩展新的 Source

### 新增 RSS

只需在 `config.yaml` 添加：

```yaml
sources:
  - name: my_rss
    type: rss
    enabled: true
    url: https://example.com/rss.xml
    description: 示例 RSS
```

RSS 通用字段映射：

- `title = entry.title`
- `url = entry.link`
- `summary = entry.summary 或 entry.description`
- `content = entry.content[0].value 或 summary`
- `published_at = entry.published 或 entry.updated`
- `image_url` 会从 media/enclosure/content HTML 第一张图片中尽量提取。

### 新增 REST API

```yaml
sources:
  - name: my_api
    type: rest
    enabled: true
    url: https://example.com/api/items
    method: GET
    headers:
      User-Agent: "Mozilla/5.0"
      Accept: "application/json"
    params:
      take: 50
```

REST 通用解析支持：

```json
[{"title": "...", "url": "..."}]
```

```json
{"items": [{"title": "...", "url": "..."}]}
```

```json
{"data": [{"title": "...", "url": "..."}]}
```

```json
{"data": {"items": [{"title": "...", "url": "..."}]}}
```

字段自动推断：

- title：`title / name / headline`
- url：`url / link / source_url / original_url`
- summary：`summary / description / desc / abstract`
- content：`content / text / body`
- published_at：`published_at / pubDate / created_at / updated_at / date`
- image_url：`image_url / image / cover / cover_url / thumbnail / picurl`

如果解析失败，`test-sources` 会输出可读错误。

## 评分逻辑

规则评分 `rule_score` 范围 1-10：

- 基础分：3
- AI Coding / Codex / Claude Code / opencode / Cursor / Kiro：+3
- Agent / MCP / tool calling / workflow / memory：+2
- DBT / DSL / data quality / 数据质量 / 大数据测试：+2
- testing / QA / 测试 / 测试用例 / 测试自动化 / 需求评审：+3
- 模型发布 / benchmark / 推理模型 / 多模态：+1
- 明显营销、融资、广告：-2
- 无链接或标题过短：-1

LLM 分数 `llm_score` 由 OpenAI-compatible API 返回。最终分：

```text
final_score = rule_score * 0.4 + llm_score * 0.6
```

如果 LLM 不可用或 JSON 解析失败，单条资讯会自动 fallback 到规则评分，不中断整体流程。

## 异常处理说明

PoC 对以下情况做了降级处理：

- 单个 source 请求失败：记录错误，继续处理其他 source。
- REST JSON 结构无法识别：在 `test-sources` 中输出可读错误。
- 单条 item 缺少标题或链接：跳过该条。
- LLM 调用失败或返回 JSON 无法解析：该条使用规则评分兜底。
- 状态文件不存在：自动使用空状态并在需要时创建。
- `review/` 或 `data/` 目录不存在：自动创建。
- 企业微信 Markdown 发送失败：返回失败，不更新 `pushed_at`。
- 企业微信 News 发送失败：`markdown_plus_news` 下只输出 warning，不重复发送 Markdown；`news_only` 下返回失败。

## 状态文件与去重

默认状态文件：

```text
data/state.json
```

记录结构：

```json
{
  "seen_items": {
    "hash": {
      "title": "...",
      "url": "...",
      "source": "...",
      "first_seen_at": "...",
      "pushed_at": "..."
    }
  }
}
```

`generate` 默认不展示已推送内容。未推送但已见过的内容可以再次展示，并在内存中标记为 seen。

## 手动验证流程

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 OPENAI_BASE_URL、OPENAI_API_KEY、OPENAI_MODEL、WECOM_WEBHOOK_URL
python main.py test-sources
python main.py test-llm
python main.py generate
# 打开 review/YYYYMMDD.md，人工删除或修改条目
python main.py send --file review/YYYYMMDD.md
python main.py test-wecom
```

验收重点：

- `generate` 只生成 Markdown，不推送。
- Markdown 有推荐区、被过滤区、三类分数和 `qa_related` 字段。
- 如果没有测试工程师相关内容，必须出现缺失提醒。
- News 图文卡片只来自人工审核后仍留在推荐区的文章。
- `.env`、`data/`、`review/` 运行产物不会提交。
