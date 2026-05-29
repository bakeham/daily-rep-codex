# AI News Pusher PoC

一个 Python 3.11+ 轻量 PoC，用于定时采集 RSS / REST API 资讯，统一标准化为 `NewsItem`，去重、规则筛选、OpenAI-compatible LLM 二次摘要/评分，生成 Markdown 人工审核稿，并在人工确认后推送到企业微信机器人。

> 当前版本不包含 Web UI、后台服务或数据库服务；本地状态使用 JSON 文件，后续可替换为 SQLite。

## 功能范围

- 读取 `config.yaml` 与本地 `.env`。
- 通用 RSS source：基于 `feedparser` 解析 RSS/Atom。
- 通用 REST source：支持 `method`、`headers`、`params` 与常见 JSON list 自动推断。
- 统一数据模型：`NewsItem` 与 `RankedNewsItem`。
- 本地 JSON 状态：记录已见资讯与已推送资讯，避免重复推送。
- 规则评分：关键词加分、营销/缺失字段惩罚，输出 `rule_score`。
- LLM 评分：OpenAI-compatible Chat Completions，支持 DeepSeek v4 flash 或其他兼容模型。
- LLM 异常兜底：模型不可用或 JSON 解析失败时自动使用规则分。
- 人工审核：`generate` 只生成 `review/YYYYMMDD.md`，不会推送。
- 企业微信推送：`send` 支持 `markdown_only`、`news_only`、`markdown_plus_news`。
- Markdown 超长分片：按文章分隔符优先切分。
- News 图文卡片：默认取人工审核后推荐区前 3 篇。
- 测试工程师内容保障：推荐区尽量保留 QA/testing 相关内容；缺失时显式生成提醒区。

## 安全注意事项

1. 真实 LLM API key 和企业微信 webhook 只应该写入本地 `.env`。
2. `.env` 已加入 `.gitignore`，不要提交。
3. 不要把真实 key 写入 `README.md`、`config.yaml`、代码、日志或测试输出。
4. 程序输出会对企业微信 webhook 做脱敏展示，不会打印完整 webhook URL。
5. `config.yaml` 只保留 `${OPENAI_API_KEY}` / `${WECOM_WEBHOOK_URL}` 形式的环境变量占位符。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

复制示例环境变量文件：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```env
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=deepseek-v4-flash
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key_here
```

`config.yaml` 默认包含两个样例源：

- `https://imjuya.github.io/juya-ai-daily/rss.xml`：RSS 源。
- `https://aihot.virxact.com/api/public/items`：REST 资讯接口。

注意：`https://aihot.virxact.com/openapi.yaml` 是 OpenAPI schema，不是实际资讯数据接口；实际采集接口应配置为 `/api/public/items` 或其他公开 endpoint。默认配置中已在 source description 保留说明。

## 命令

### 1. 测试 source 可访问性

```bash
python main.py test-sources
```

输出每个启用 source 是否成功、解析到多少条资讯。如果某个 REST 返回结构无法识别，会输出可读错误，但不会影响其他 source 测试。

### 2. 测试 LLM JSON 评分

```bash
python main.py test-llm
```

该命令使用内置模拟资讯“LLM 自动生成测试用例的新方法”测试模型是否返回可解析 JSON。输出包括：

- LLM 连接是否成功。
- 模型名。
- 脱敏后的解析结果 JSON。
- 解析是否成功。
- `qa_related` 是否为 true。

不会打印 API key。

### 3. 生成 Markdown 人工审核稿

```bash
python main.py generate
```

生成文件示例：

```text
review/20260529.md
```

`generate` 阶段只做采集、去重、规则评分、LLM 评分和 Markdown 生成，绝不会推送企业微信。

### 4. 人工审核

打开 `review/YYYYMMDD.md`，在 `## 推荐推送内容` 下人工处理：

- 删除不想推送的条目。
- 修改标题、摘要、推荐理由或参考价值。
- 如果希望恢复某条被过滤内容，可将它从 `## 被过滤但可人工恢复的内容` 移动到 `## 推荐推送内容`。
- 建议保留至少 1 条“测试工程师 / QA / 测试自动化 / 数据质量”相关内容。

`send` 阶段只解析 `## 推荐推送内容` 下的文章生成 News 图文卡片，不会把被过滤区文章自动放进卡片。

### 5. 推送企业微信

```bash
python main.py send --file review/YYYYMMDD.md
```

发送成功后，程序会更新 `data/state.json` 中对应文章的 `pushed_at`，避免后续重复推送。

### 6. 测试企业微信 webhook

```bash
python main.py test-wecom
```

发送一条简短 Markdown 连通性测试消息。不会打印完整 webhook URL。

## 推送模式切换

在 `config.yaml` 修改：

```yaml
wecom:
  mode: markdown_plus_news
```

可选值：

- `markdown_only`：只发送 Markdown 摘要。
- `news_only`：只发送 News 图文卡片。
- `markdown_plus_news`：先发送 Markdown 摘要，再发送 News 图文卡片（默认）。

News 图文卡片数量由 `wecom.news_top_n` 控制，默认 3。

## 扩展新 source

### 新增 RSS

只需在 `config.yaml` 增加：

```yaml
sources:
  - name: your_rss
    type: rss
    enabled: true
    url: https://example.com/rss.xml
```

RSS 通用字段映射：

- `title = entry.title`
- `url = entry.link`
- `summary = entry.summary / entry.description`
- `content = entry.content[0].value / summary`
- `published_at = entry.published / entry.updated`
- `image_url = media_thumbnail / media_content / enclosure / HTML 第一张图片`

### 新增 REST

只需在 `config.yaml` 增加：

```yaml
sources:
  - name: your_api
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

REST 自动支持这些常见结构：

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

- title: `title` / `name` / `headline`
- url: `url` / `link` / `source_url` / `original_url`
- summary: `summary` / `description` / `desc` / `abstract`
- content: `content` / `text` / `body`
- published_at: `published_at` / `pubDate` / `created_at` / `updated_at` / `date`
- image_url: `image_url` / `image` / `cover` / `cover_url` / `thumbnail` / `picurl`

如果 API 字段特殊，可增加 `mapping`：

```yaml
mapping:
  title: articleTitle
  url: articleUrl
  summary: brief
  content: body
  published_at: publishTime
  image_url: coverImage
```

## 异常处理说明

- 某个 source 请求失败：记录错误，继续处理其他 source。
- 某个 REST JSON 解析失败：`test-sources` 输出可读错误，主流程跳过该 source。
- 某条 item 字段缺失：跳过该条并输出 warning。
- LLM 不可用：自动 fallback 到规则评分，不中断 generate。
- LLM JSON 解析失败：当前条目 fallback 到规则评分，不影响其他条目。
- 企业微信 Markdown 推送失败：输出错误，不更新 `pushed_at`。
- 企业微信 News 推送失败：如果 Markdown 已成功发送，仅输出 warning，不重复发送 Markdown。
- 状态文件、`data/`、`review/` 不存在：程序会自动创建。

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
# 打开 review/YYYYMMDD.md，删除/修改不想推送的内容
python main.py send --file review/YYYYMMDD.md
python main.py test-wecom
```

验收重点：

1. `test-sources` 能显示两个默认源是否可访问。
2. `test-llm` 能解析 JSON，并对测试用例生成资讯给出 `qa_related=true`。
3. `generate` 会生成 Markdown，包含“推荐推送内容”和“被过滤但可人工恢复的内容”。
4. Markdown 中展示 `rule_score`、`llm_score`、`final_score` 和 `qa_related`。
5. 如果没有测试工程师相关内容，会出现“测试工程师相关内容缺失提醒”。
6. `send` 的 News 卡片只来自人工审核后仍保留在推荐区的前 `news_top_n` 篇。
