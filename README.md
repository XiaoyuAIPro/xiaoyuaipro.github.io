# 小宇AI晚报 · 个人站点

> 探索 AI 的无限可能 | 每日自动聚合全球 AI 前沿资讯

**站点地址：** https://xiaoyuaipro.github.io

---

## 🏗️ 项目结构

```
.
├── .github/
│   └── workflows/
│       ├── daily-report.yml   # 每日定时生成晚报（18:30 CST）
│       └── deploy.yml         # 推送后自动构建并部署到 GitHub Pages
├── content/
│   └── posts/                 # 每日晚报 Markdown 文件
├── scripts/
│   ├── daily_report.py        # 核心脚本：RSS 抓取 + 内容生成
│   └── requirements.txt       # Python 依赖
├── archetypes/
│   └── posts.md               # 新文章模板
└── hugo.toml                  # Hugo 站点配置
```

---

## 🚀 快速开始

### 本地预览

```bash
# 安装 Hugo（macOS）
brew install hugo

# 启动本地预览服务器
hugo server -D
```

### 手动生成今日晚报

```bash
# 安装 Python 依赖
pip install -r scripts/requirements.txt

# 纯 RSS 模式（完全免费，无需 API Key）
python scripts/daily_report.py

# Gemini 增强模式（推荐，免费额度每日 1500 次）
GEMINI_API_KEY=你的密钥 python scripts/daily_report.py
```

---

## ⚙️ 自动化配置（必做）

### 第一步：开启 GitHub Pages

1. 进入仓库 → **Settings** → **Pages**
2. Source 选择 **GitHub Actions**
3. 保存

### 第二步：配置 GitHub Actions 权限

1. 进入仓库 → **Settings** → **Actions** → **General**
2. 将 **Workflow permissions** 设置为 **Read and write permissions**
3. 勾选 **Allow GitHub Actions to create and approve pull requests**
4. 保存

### 第三步（可选）：配置 Gemini API Key

获取免费 Key：https://aistudio.google.com/app/apikey

1. 进入仓库 → **Settings** → **Secrets and variables** → **Actions**
2. 点击 **New repository secret**
3. Name: `GEMINI_API_KEY`，Value: 你的 API Key
4. 保存

> 不配置此项时，系统自动使用纯 RSS 聚合模式，完全免费。

---

## 📊 新闻来源（RSS，完全免费）

| 来源 | 类型 |
|------|------|
| TechCrunch AI | AI 产业动态 |
| VentureBeat AI | AI 创业投融资 |
| The Verge AI | 科技消费 |
| MIT Technology Review | 学术/深度 |
| Hacker News（AI 话题） | 开发者社区 |
| AI News | 综合资讯 |

---

## 💡 扩展建议

- **增加新闻源**：在 `scripts/daily_report.py` 的 `RSS_FEEDS` 列表中添加新条目
- **调整发布时间**：修改 `daily-report.yml` 中的 `cron` 表达式
- **添加新功能**：在 `content/` 下添加新的内容类型（如周报、专题分析）
