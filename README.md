# AI 早报二次汇总 / 审核 / 企业微信推送 PoC

这是一个 Python 3.11+ 轻量工程，用于定时采集 RSS 与 REST API 资讯源，统一标准化为 `NewsItem`，去重、规则筛选、调用 OpenAI-compatible LLM（例如 DeepSeek v4 flash）做二次摘要与评分，然后先生成 Markdown 人工审核稿。人工确认后，`send` 命令再按配置推送到企业微信机器人。

核心链路：

```text
RSS / REST API
  → 统一采集
  → 标准化 NewsItem
  → 去重
  → 规则初筛和 rule_score
  → OpenAI-compatible LLM 评分和摘要
  → final_score 排序
  → 生成 Markdown 人工审核稿
  → 人工确认后推送企业微信
```

## 目录结构

```text
.
├── main.py
├── config.yaml
├── requirements.txt
├── .env.example
├── src/
│   ├── models.py
│   ├── sources/
│   ├── core/
│   └── publishers/
├── data/
└── review/
```

## 安装与配置

```bash
pip install -r requirements.txt
cp .env.example .env
```

然后只在本地 `.env` 中填写真实敏感信息：

```env
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=deepseek-v4-flash
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key_here
```

安全约束：

- 真实 key 只应该写入本地 `.env`。
- `.env` 已加入 `.gitignore`，不要提交。
- 不要把真实 key 写进 `config.yaml`、代码、README、日志或测试输出。
- 程序只会打印脱敏后的 webhook 标识，不会打印完整企业微信 webhook URL。

## 默认资讯源

`config.yaml` 默认包含两个源：

1. `juya_ai_daily`：RSS 源 `https://imjuya.github.io/juya-ai-daily/rss.xml`
2. `aihot_selected`：REST 源 `https://aihot.virxact.com/api/public/items`

注意：`https://aihot.virxact.com/openapi.yaml` 是 OpenAPI schema，不是实际资讯列表接口。默认配置使用实际公开采集 endpoint `/api/public/items`，并在配置注释中保留了 schema 地址说明。

## 命令

### 1. 测试 source 是否可访问

```bash
python main.py test-sources
```

输出每个 source 的可访问状态和解析条数。某个 source 失败不会影响其他 source。

### 2. 测试 LLM

```bash
python main.py test-llm
```

使用内置模拟资讯“LLM 自动生成测试用例的新方法”测试 LLM 是否能返回 JSON。输出包括：

- LLM 连接是否成功
- 模型名
- 返回 JSON
- 解析是否成功
- `qa_related` 是否为 true

不会打印 API key。

### 3. 生成 Markdown 人工审核稿（不会推送）

```bash
python main.py generate
```

生成文件示例：

```text
review/20260529.md
```

`generate` 阶段只采集、去重、评分、生成 Markdown，绝不会自动推送企业微信。

### 4. 人工审核

打开 `review/YYYYMMDD.md` 后可以：

- 删除不想推送的条目。
- 手动修改标题、摘要、推荐理由、参考价值。
- 将“被过滤但可人工恢复的内容”移动到“推荐推送内容”。
- 建议至少保留 1 条“测试工程师 / QA / 测试自动化”相关内容。

`send` 阶段只解析 `## 推荐推送内容` 下的文章生成 News 图文卡片，不会把被过滤区或缺失提醒区的文章自动放进 News 卡片，除非你人工移动到推荐区。

### 5. 推送审核后的 Markdown

```bash
python main.py send --file review/YYYYMMDD.md
```

根据 `config.yaml` 的 `wecom.mode` 推送：

- `markdown_only`：只发送 Markdown 摘要。
- `news_only`：只发送 News 图文卡片。
- `markdown_plus_news`：先发送 Markdown，再发送 News 图文卡片（默认）。

推送成功后，程序会更新 `data/state.json` 的 `pushed_at`，避免后续重复推送。

### 6. 测试企业微信 webhook

```bash
python main.py test-wecom
```

发送一条测试 Markdown 消息。不会打印完整 webhook URL。

## 规则评分与 LLM 评分

规则评分 `rule_score` 范围 1-10：

- 基础分 3。
- AI Coding / Codex / Claude Code / opencode / Cursor / Kiro 命中：+3。
- Agent / MCP / tool calling / workflow / memory 命中：+2。
- DBT / DSL / data quality / 数据质量 / 大数据测试 命中：+2。
- testing / QA / 测试 / 测试用例 / 测试自动化 / 需求评审 命中：+3。
- 模型发布 / benchmark / 推理模型 / 多模态：+1。
- 明显营销、融资、广告：-2。
- 无链接或标题过短：-1。

最终分：

```text
final_score = rule_score * 0.4 + llm_score * 0.6
```

如果 LLM 不可用、配置缺失、调用失败或 JSON 解析失败，该条资讯会自动 fallback 到规则评分，不会中断整个流程。

## 测试工程师相关内容保障

配置项：

```yaml
app:
  require_qa_related: true
```

系统会尽量保证推荐区至少有 1 条 `qa_related=true` 内容。如果没有明显测试工程师相关内容，Markdown 会显式生成：

```markdown
## 测试工程师相关内容缺失提醒
```

并列出相对最接近的候选内容，方便人工判断。

## 新增 RSS source

只需要修改 `config.yaml`：

```yaml
sources:
  - name: another_rss
    type: rss
    enabled: true
    url: https://example.com/rss.xml
```

RSS 会使用通用 `feedparser` 解析：标题、链接、摘要、正文片段、发布时间和图片。

## 新增 REST source

常见 JSON 结构会自动推断：

```json
[{"title": "...", "url": "..."}]
```

```json
{"items": [{"title": "...", "url": "..."}]}
```

```json
{"data": {"items": [{"title": "...", "url": "..."}]}}
```

字段自动推断包括：

- title / name / headline
- url / link / source_url / original_url
- summary / description / desc / abstract
- content / text / body
- published_at / pubDate / created_at / updated_at / date
- image_url / image / cover / cover_url / thumbnail / picurl

如果字段名不常见，可以添加 mapping：

```yaml
sources:
  - name: custom_api
    type: rest
    enabled: true
    url: https://example.com/api/news
    method: GET
    headers:
      Accept: application/json
    params:
      limit: 50
    mapping:
      title: article_title
      url: article_url
      summary: brief
      image_url: cover_image
```

## 切换企业微信推送模式

修改 `config.yaml`：

```yaml
wecom:
  mode: markdown_plus_news
```

可选值：

- `markdown_only`
- `news_only`
- `markdown_plus_news`

News 卡片默认最多发送 3 篇，可通过 `news_top_n` 调整。

## 异常处理说明

- source 级别失败：打印可读错误，继续处理其他 source。
- REST 返回非 JSON 或无法找到列表：`test-sources` 会输出错误原因。
- item 字段缺失：跳过该条。
- LLM 调用失败或 JSON 解析失败：单条 fallback 到规则评分。
- Markdown 推送失败：不更新 `pushed_at`。
- News 推送失败：如果 Markdown 已发送，只输出 warning，不重复发送 Markdown。
- 状态文件、`data/`、`review/` 不存在：自动创建或使用空状态。

## 手动验证流程

1. 安装依赖：`pip install -r requirements.txt`
2. 复制环境变量模板：`cp .env.example .env`
3. 在 `.env` 中填写 OpenAI-compatible LLM 和企业微信 webhook。
4. 运行 `python main.py test-sources`，确认两个默认源至少一个可解析出资讯。
5. 运行 `python main.py test-llm`，确认能解析 JSON 且测试资讯 `qa_related=true`。
6. 运行 `python main.py generate`，确认生成 `review/YYYYMMDD.md`。
7. 打开 Markdown，确认包含“推荐推送内容”“被过滤但可人工恢复的内容”、`rule_score`、`llm_score`、`final_score`、`qa_related`。
8. 人工删除或调整不想推送的文章。
9. 运行 `python main.py send --file review/YYYYMMDD.md`，确认企业微信收到 Markdown 和最多 3 张 News 图文卡片。
10. 查看 `data/state.json`，确认已推送文章写入 `pushed_at`。

## 接口无法跑通时的替代建议

如果 `aihot_selected` 返回结构变化或接口不可用，可以临时将其禁用：

```yaml
sources:
  - name: aihot_selected
    enabled: false
```

也可以根据 `https://aihot.virxact.com/openapi.yaml` 中最新 schema，把实际列表 endpoint 和字段 mapping 更新到 `config.yaml`。
