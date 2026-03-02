# 小宇AI晚报 · 个人站点

> 探索 AI 的无限可能 | 每日自动生成全球 AI 与综合热点晚报

**站点地址：** https://xiaoyuaipro.github.io

---

## 🏗️ 项目结构

```
.
├── .github/
│   └── workflows/
│       ├── daily-report.yml   # 每日定时生成晚报（北京时间 18:30）
│       └── deploy.yml         # 推送后自动构建并部署到 GitHub Pages
├── content/
│   └── posts/                 # 每日晚报 Markdown 文件（自动生成）
├── scripts/
│   ├── daily_report.py        # 核心脚本：RSS 采集 + DeepSeek 写作 + Hugo 渲染
│   ├── prompt.md              # 写作风格 Prompt（由此控制晚报的内容结构和风格）
│   ├── test_api.py            # API Key 连通性测试工具
│   └── requirements.txt       # Python 依赖
├── archetypes/
│   └── posts.md               # 新文章模板
├── layouts/
│   └── redirect/
│       └── single.html        # /latest/ 动态跳转到最新晚报
└── hugo.toml                  # Hugo 站点配置
```

---

## ⚙️ 自动化流程

每日晚报由四个步骤自动完成：

```
Step 1 — RSS 采集
  从 BBC、Guardian、CNN、TechCrunch、VentureBeat 等抓取当日新闻
  综合热点 + AI 动态，每条均保留真实可点击的原文链接

Step 2 — DeepSeek 中文写作
  将 RSS 原文 + scripts/prompt.md 风格要求发给 DeepSeek
  生成符合 prompt 要求的高质量中文晚报（综合新闻5条 + AI动态5条）

Step 3 — 格式标准化
  DeepSeek 将正文转为严格 JSON，保证每次格式一致

Step 4 — Hugo 渲染
  JSON 渲染为 Hugo Markdown 文件，自动 push 触发站点部署
```

---

## 🚀 快速开始

### 本地预览站点

```bash
# 安装 Hugo（macOS）
brew install hugo

# 启动本地预览（访问 http://localhost:1313）
hugo server -D
```

### 手动生成今日晚报

```bash
# 安装 Python 依赖
pip install -r scripts/requirements.txt

# 设置 DeepSeek API Key 后运行
export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
python scripts/daily_report.py
```

### 测试 API Key 是否可用

```bash
python scripts/test_api.py --deepseek sk-xxxxxxxxxxxxxxxx
```

---

## ⚙️ 自动化配置（必做）

### 第一步：开启 GitHub Pages

1. 进入仓库 → **Settings** → **Pages**
2. Source 选择 **GitHub Actions**
3. 保存

### 第二步：配置 Actions 权限

1. 进入仓库 → **Settings** → **Actions** → **General**
2. 将 **Workflow permissions** 设置为 **Read and write permissions**
3. 勾选 **Allow GitHub Actions to create and approve pull requests**
4. 保存

### 第三步：配置 DeepSeek API Key

1. 进入仓库 → **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**，添加以下密钥：

| Secret 名称 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | **必填**，DeepSeek 官方 API Key（[获取地址](https://platform.deepseek.com/api_keys)） |
| `ANTHROPIC_API_KEY` | 可选，Claude 备用（当 DeepSeek 不可用时自动切换） |
| `GEMINI_API_KEY` | 可选，Gemini 备用（最后兜底） |

> 三个 Key 至少配置一个。推荐 DeepSeek，性价比最高。

---

## ✏️ 自定义晚报风格

编辑 `scripts/prompt.md` 即可控制晚报的内容结构和写作风格，无需改动代码。

当前配置：
- 综合新闻 5 条：全球政治、经济、社会热点
- AI 技术/产业动态 5 条：模型、投融资、政策、算力等
- 每条包含：标题 + 摘要（1-2句）+ 📌点评 + 🔗真实来源链接

---

## 📰 新闻来源（RSS，完全免费）

| 来源 | 类型 |
|---|---|
| BBC World | 综合新闻 |
| The Guardian World | 综合新闻 |
| CNN World | 综合新闻 |
| Al Jazeera | 综合新闻 |
| TechCrunch AI | AI 产业动态 |
| VentureBeat AI | AI 创业投融资 |
| The Verge AI | 科技消费 |
| MIT Technology Review | AI 学术/深度 |
| AI News | AI 综合资讯 |
| Hacker News（AI 话题） | 开发者社区 |

---

## 💡 扩展建议

- **调整新闻来源**：在 `scripts/daily_report.py` 的 `RSS_FEEDS` 列表中增减条目
- **修改写作风格**：直接编辑 `scripts/prompt.md`，无需改代码
- **调整发布时间**：修改 `daily-report.yml` 中的 `cron` 表达式（当前为 UTC 10:30 = 北京 18:30）
- **添加新功能**：在 `content/` 下添加新的内容类型（如周报、专题分析）
