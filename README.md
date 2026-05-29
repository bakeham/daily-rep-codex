# AI 早报二次汇总、审核、企业微信推送 PoC

这是一个 Python 3.11+ 轻量 PoC，用于定时采集 RSS / REST API 资讯，标准化为 `NewsItem`，去重、规则初筛、调用 OpenAI-compatible LLM（例如 DeepSeek v4 flash）评分和摘要，生成 Markdown 人工审核稿，审核后再推送到企业微信机器人。

核心链路：

```text
RSS / REST API → 标准化 NewsItem → 去重 → rule_score → LLM 摘要/评分
→ final_score 排序 → review/YYYYMMDD.md 人工审核 → 企业微信 markdown/news 推送
```

> 重要：`generate` 只生成审核稿，不会推送。只有 `send --file review/YYYYMMDD.md` 才会推送。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

然后编辑本地 `.env`：

```env
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=deepseek-v4-flash
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key_here
```

## 安全说明

- 真实 key 只应该写入本地 `.env` 或环境变量。
- `.env` 已加入 `.gitignore`，不要提交。
- 不要把真实 API key、企业微信 webhook 写进 `config.yaml`、代码、README、日志或测试输出。
- 程序输出会避免打印完整企业微信 webhook URL，也不会打印 API key。

## 配置

默认配置在 `config.yaml`。敏感字段使用环境变量占位：

```yaml
llm:
  base_url: ${OPENAI_BASE_URL}
  api_key: ${OPENAI_API_KEY}
  model: ${OPENAI_MODEL}

wecom:
  webhook_url: ${WECOM_WEBHOOK_URL}
```

默认包含两个源：

1. `https://imjuya.github.io/juya-ai-daily/rss.xml`：通用 RSS parser。
2. `https://aihot.virxact.com/api/public/items`：通用 REST parser。

`https://aihot.virxact.com/openapi.yaml` 是 API schema，不是实际资讯列表接口；实际采集接口应配置为 `/api/public/items` 或其他公开 endpoint。

## 命令

```bash
python main.py test-sources
python main.py test-llm
python main.py generate
python main.py send --file review/YYYYMMDD.md
python main.py test-wecom
```

### `test-sources`

测试 `config.yaml` 中启用的 source 是否可访问，并输出每个源的条数和首条样例。

### `test-llm`

使用内置测试资讯调用 LLM，检查是否能返回 JSON，并验证 `qa_related=true`、分数较高。不会打印 API key。

### `generate`

执行采集、去重、规则评分、LLM 评分，生成 `review/YYYYMMDD.md`。审核稿包含：

- 本次筛选概览
- 推荐推送内容
- `rule_score`、`llm_score`、`final_score`
- `qa_related` 显式标记
- 测试工程师相关内容缺失提醒（当推荐区没有强相关内容时）
- 被过滤但可人工恢复的内容

### 人工审核

打开 `review/YYYYMMDD.md`：

1. 删除不想推送的条目。
2. 可手动改标题、摘要、推荐理由、参考价值。
3. 只保留 `## 推荐推送内容` 下需要推送的文章。
4. 建议至少保留 1 条“测试工程师 / QA / 测试自动化 / 数据质量”相关内容。

### `send`

读取人工审核后的 Markdown 文件，按配置推送企业微信：

- `markdown_only`：只发送 Markdown。
- `news_only`：只发送 News 图文卡片。
- `markdown_plus_news`：先发送 Markdown，再发送 News 图文卡片（默认）。

News 图文卡片只解析 `## 推荐推送内容` 下的文章，默认最多 3 篇；人工删除的文章不会进入 news 卡片。

## 切换企业微信推送模式

编辑 `config.yaml`：

```yaml
wecom:
  mode: markdown_plus_news  # markdown_only / news_only / markdown_plus_news
  send_markdown: true
  send_news: true
  news_top_n: 3
```

## 扩展新 source

新增 RSS：

```yaml
sources:
  - name: example_rss
    type: rss
    enabled: true
    url: https://example.com/rss.xml
```

新增 REST：

```yaml
sources:
  - name: example_api
    type: rest
    enabled: true
    url: https://example.com/api/news
    method: GET
    headers:
      User-Agent: "Mozilla/5.0"
      Accept: "application/json"
    params:
      limit: 50
```

REST 自动支持 `list`、`items`、`data`、`data.items` 等常见结构，并自动推断字段：`title/name/headline`、`url/link/source_url/original_url`、`summary/description/desc/abstract` 等。

如果接口字段比较特殊，可加 mapping：

```yaml
mapping:
  title: payload.title
  url: payload.sourceUrl
  summary: payload.brief
  image_url: payload.cover
```

## 异常处理

- 单个 source 请求失败：记录错误并继续处理其他 source。
- REST JSON 解析失败：在 `test-sources` 输出可读错误。
- 单条 item 字段缺失：跳过该条。
- LLM 调用失败或 JSON 解析失败：该条 fallback 到规则评分，不中断流程。
- 企业微信 Markdown 失败：返回失败，不更新 `pushed_at`。
- 企业微信 News 失败：`markdown_plus_news` 下只输出 warning，不重复发送 Markdown；`news_only` 下整体失败。
- 状态文件、`data/`、`review/` 不存在时会自动创建。

## 本地状态

状态文件默认在 `data/state.json`，记录 `seen_items`、`first_seen_at` 和 `pushed_at`。`generate` 默认跳过已推送内容；未推送但已见过的内容可继续展示并标记 seen。

## 手动验证流程

1. 安装依赖并复制 `.env.example` 为 `.env`。
2. 在 `.env` 中填入 OpenAI-compatible LLM 和企业微信 webhook。
3. 运行 `python main.py test-sources`，确认两个默认源至少一个返回资讯。
4. 运行 `python main.py test-llm`，确认返回 JSON 且 `qa_related` 为 true。
5. 运行 `python main.py generate`，确认生成 `review/YYYYMMDD.md`。
6. 打开 Markdown，删除不想推送的条目，保留需要推送的 1-3 篇。
7. 运行 `python main.py send --file review/YYYYMMDD.md`，确认企业微信群收到 Markdown 和 News 卡片。
8. 查看 `data/state.json`，确认已推送文章写入 `pushed_at`。

## 接口不可用时的替代配置

如果 `aihot_selected` 不可访问，可先将该 source 的 `enabled` 改为 `false`，或替换为其他返回 JSON 列表的公开 API。RSS 源也可替换为任何标准 RSS/Atom feed。
