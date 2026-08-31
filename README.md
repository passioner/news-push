# 每日科技早报推送

每天 07:00（北京时间）自动抓取科技圈热点，用 DeepSeek 生成中文播报稿，推送到 iPhone（Bark），并可通过 iOS 快捷指令在车内语音朗读。

## 工作原理

```
GitHub Actions 定时(07:00) → main.py
   ├─ 抓取 RSS（科技/苹果/AI/RC模型/娱乐）
   ├─ 关键词过滤 + 去重
   ├─ DeepSeek 生成 300~500 字中文播报稿
   ├─ 写入 summary/latest.txt 并提交到仓库
   └─ Bark 推送到 iPhone（通知栏文字）
iOS 快捷指令(07:10) → 拉取 latest.txt → 朗读文本 → 车内播放
```

## 部署步骤

### 1. 准备两个账号

- **GitHub**：把本项目代码推到一个仓库（建议 Public，方便快捷指令免鉴权拉取）。
- **DeepSeek**：到 [platform.deepseek.com](https://platform.deepseek.com) 创建 API Key。
- **Bark**：iPhone 安装 [Bark](https://apps.apple.com/app/bark-customed-notifications/id1403753865)，打开后首页复制你的推送 Key（形如 `xxxxx`），即可得到推送地址 `https://api.day.app/xxxxx`。

### 2. 配置 GitHub Secrets

进入仓库 Settings → Secrets and variables → Actions → New repository secret，添加：

| Secret | 值 |
|--------|----|
| `BARK_KEY` | Bark App 首页的 Key |
| `DEEPSEEK_API_KEY` | DeepSeek 的 API Key |

可选（默认无需设置）：

| Secret | 默认值 | 说明 |
|--------|--------|------|
| `BARK_SERVER` | `https://api.day.app` | 自建 Bark 服务时填写 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | 换其他 OpenAI 兼容接口时填写 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |

### 3. 推送代码并验证

```bash
git init && git add -A && git commit -m "init"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

推上去后，在 Actions 页面的 `Daily News Push` 工作流里点 **Run workflow** 手动跑一次，验证 iPhone 能收到 Bark 通知。

### 4. 配置 iOS 语音朗读

1. 打开「快捷指令」App → 底部「自动化」→ 右上「+」→「创建个人自动化」。
2. 选「特定时间」→ 设为 `07:10`、每天重复 → 下一步。
3. 添加操作：
   - 「获取 URL 的内容」，URL 填：`https://raw.githubusercontent.com/<你的用户名>/<仓库名>/main/summary/latest.txt`
   - 「朗读文本」，语言选「中文（中国大陆）」，声音可换成你喜欢的（建议 Siri 女声或"婷婷"）。
4. 关闭「运行前询问」，完成。

之后每天上车连接蓝牙/CarPlay 时，手机会自动朗读当天的播报稿。

> 私有仓库：快捷指令默认无法免鉴权读取。可在「获取 URL 的内容」里改用带 token 的请求，或改用公开仓库。

## 自定义

- **换新闻源 / 加关键词**：编辑 `config/feeds.yaml`。
- **改播报风格**：编辑 `config/prompt.txt`。
- **改推送时间**：编辑 `.github/workflows/daily-news.yml` 的 `cron`（注意是 UTC 时间，北京 07:00 = `0 23 * * *`）。

## 本地测试

```bash
pip install -r requirements.txt
python main.py --dry-run          # 只抓取+筛选，看候选
python main.py --no-push          # 生成 summary/latest.txt，不推送
```

真正推送需要先导出环境变量：

```bash
export BARK_KEY=xxx
export DEEPSEEK_API_KEY=xxx
python main.py
```

## 文件结构

```
.
├── .github/workflows/daily-news.yml   # 定时任务
├── main.py                            # 主逻辑
├── config/feeds.yaml                  # 新闻源 & 关键词
├── config/prompt.txt                  # LLM 提示词
├── summary/latest.txt                 # 当天播报稿（脚本自动生成）
└── requirements.txt
```
