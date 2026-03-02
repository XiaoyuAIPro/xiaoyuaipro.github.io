#!/usr/bin/env python3
"""
每日AI晚报自动生成脚本
============================
架构（四步流程）：

  Step 1 — RSS 真实数据采集
    三个分类独立采集：
      • AI技术/产业动态  → TechCrunch / VentureBeat / The Verge / MIT TR 等
      • 国际综合新闻     → BBC World / Guardian / Al Jazeera / CNN 等
      • 国内综合新闻     → China Daily / SCMP China / 36氪 / 虎嗅 等

  Step 2 — DeepSeek 中文写作
    将三分类 RSS 原文 + scripts/prompt.md 风格要求发给 DeepSeek
    生成包含 AI动态5条 + 国际新闻5条 + 国内新闻5条 的中文晚报

  Step 3 — 格式标准化
    将正文再次发给 DeepSeek，转为严格 JSON 结构（三个 category 对象）

  Step 4 — 渲染输出
    将 JSON 渲染为带 Hugo front matter 的 Markdown 文件
    写入 content/posts/YYYY-MM-DD-daily-report.md

所需环境变量：
  DEEPSEEK_API_KEY   必填
  DEEPSEEK_MODEL     可选，默认 deepseek-chat
  DEEPSEEK_BASE_URL  可选，默认 https://api.deepseek.com

备用 LLM（任一可用即触发）：
  ANTHROPIC_API_KEY  Claude
  GEMINI_API_KEY     Gemini

使用方法：
  DEEPSEEK_API_KEY=sk-xxx python scripts/daily_report.py
"""

import os
import sys
import re
import json
import datetime
import textwrap
import traceback
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

try:
    import feedparser
except ImportError:
    print("❌ 缺少依赖: feedparser。请运行: pip install feedparser", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("❌ 缺少依赖: httpx。请运行: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

BEIJING_TZ   = ZoneInfo("Asia/Shanghai")
PROJECT_ROOT = Path(__file__).parent.parent
CONTENT_DIR  = PROJECT_ROOT / "content" / "posts"
PROMPT_FILE  = Path(__file__).parent / "prompt.md"

DEFAULT_DEEPSEEK_MODEL    = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_CLAUDE_MODEL      = "claude-3-5-sonnet-20241022"

# 分类定义（顺序即最终晚报展示顺序）
CATEGORY_AI       = "AI技术/产业动态"
CATEGORY_INTL     = "国际综合新闻"
CATEGORY_DOMESTIC = "国内综合新闻"
CATEGORY_ORDER    = [CATEGORY_AI, CATEGORY_INTL, CATEGORY_DOMESTIC]

# ---------------------------------------------------------------------------
# RSS 数据源
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    # ── AI / 科技动态 ─────────────────────────────────────────────
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": CATEGORY_AI,
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/ai/feed/",
        "category": CATEGORY_AI,
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "category": CATEGORY_AI,
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": CATEGORY_AI,
    },
    {
        "name": "AI News",
        "url": "https://www.artificialintelligence-news.com/feed/",
        "category": CATEGORY_AI,
    },
    {
        "name": "Hacker News Top AI",
        "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22machine+learning%22&points=80",
        "category": CATEGORY_AI,
    },
    # ── 国际综合新闻 ──────────────────────────────────────────────
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "category": CATEGORY_INTL,
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "category": CATEGORY_INTL,
    },
    {
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "category": CATEGORY_INTL,
    },
    {
        "name": "CNN World",
        "url": "http://rss.cnn.com/rss/edition_world.rss",
        "category": CATEGORY_INTL,
    },
    # ── 国内综合新闻 ──────────────────────────────────────────────
    # 以下源从 GitHub Actions（海外服务器）抓取，部分可能因网络访问受限而失败，
    # 脚本会自动跳过失败的源，并将 DeepSeek 作为内容生成的兜底。
    {
        "name": "China Daily",
        "url": "http://www.chinadaily.com.cn/rss/china_rss.xml",
        "category": CATEGORY_DOMESTIC,
    },
    {
        "name": "SCMP China",
        "url": "https://www.scmp.com/rss/2/feed",
        "category": CATEGORY_DOMESTIC,
    },
    {
        "name": "Caixin Global",
        "url": "https://www.caixinglobal.com/rss/all_stories.xml",
        "category": CATEGORY_DOMESTIC,
    },
    {
        "name": "36氪",
        "url": "https://36kr.com/feed",
        "category": CATEGORY_DOMESTIC,
    },
    {
        "name": "虎嗅",
        "url": "https://www.huxiu.com/rss/0.xml",
        "category": CATEGORY_DOMESTIC,
    },
]

# AI 关键词（仅用于 AI 分类内容过滤，其他分类不过滤）
AI_KEYWORDS = [
    "AI", "artificial intelligence", "machine learning", "deep learning",
    "LLM", "large language model", "GPT", "Claude", "Gemini", "DeepSeek",
    "neural network", "generative", "AGI", "OpenAI", "Anthropic", "DeepMind",
    "NVIDIA", "transformer", "diffusion", "agent", "robot", "autonomous",
    "Mistral", "Meta AI", "Microsoft AI", "Grok", "xAI", "foundation model",
]

MAX_ITEMS_PER_CATEGORY = 8  # 每分类多采集一些，供 DeepSeek 筛选最重要的 5 条


# ---------------------------------------------------------------------------
# Step 1：RSS 数据采集
# ---------------------------------------------------------------------------

def is_ai_related(title: str, summary: str = "") -> bool:
    """判断文章是否与 AI 领域相关（仅用于 AI 分类过滤）"""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in AI_KEYWORDS)


def clean_html(raw: str) -> str:
    """移除 HTML 标签，清理 HackerNews 元数据"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"Article URL:.*?(?=Comments URL:|$)", "", text, flags=re.DOTALL)
    text = re.sub(r"Comments URL:.*?(?=Points:|$)",      "", text, flags=re.DOTALL)
    text = re.sub(r"Points:\s*\d+.*",                    "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


def fetch_rss_articles(max_age_hours: int = 36) -> dict[str, list[dict]]:
    """
    从所有 RSS 源抓取文章，返回按分类分组的有序字典。
    分类顺序：AI技术/产业动态 → 国际综合新闻 → 国内综合新闻
    """
    cutoff = datetime.datetime.now(BEIJING_TZ) - datetime.timedelta(hours=max_age_hours)
    # 按预定顺序初始化，保证输出顺序稳定
    categorized: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}

    for feed_cfg in RSS_FEEDS:
        name     = feed_cfg["name"]
        url      = feed_cfg["url"]
        category = feed_cfg["category"]
        print(f"    📡 {name} ...", end=" ", flush=True)

        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"❌ ({e})")
            continue

        count = 0
        for entry in feed.entries[:25]:
            title   = entry.get("title", "").strip()
            link    = entry.get("link",  "").strip()
            raw_sum = entry.get("summary", "") or entry.get("description", "")
            summary = clean_html(raw_sum)

            if not title or not link:
                continue

            # 只对 AI 分类做关键词过滤；国际/国内综合新闻不过滤
            if category == CATEGORY_AI and not is_ai_related(title, summary):
                continue

            # 解析发布时间
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_time = datetime.datetime(
                    *entry.published_parsed[:6], tzinfo=datetime.timezone.utc
                ).astimezone(BEIJING_TZ)
            else:
                pub_time = datetime.datetime.now(BEIJING_TZ)

            if pub_time < cutoff:
                continue

            categorized[category].append({
                "title":    title,
                "link":     link,
                "summary":  summary,
                "source":   name,
                "pub_time": pub_time,
            })
            count += 1

        print(f"✅ {count} 条")

    # 每分类去重 + 按时间倒序 + 限量
    result: dict[str, list[dict]] = {}
    for cat in CATEGORY_ORDER:
        articles = categorized.get(cat, [])
        seen: set[str] = set()
        unique = []
        for a in sorted(articles, key=lambda x: x["pub_time"], reverse=True):
            key = a["title"][:35].lower()
            if key not in seen:
                seen.add(key)
                unique.append(a)
        if unique:  # 只保留有内容的分类
            result[cat] = unique[:MAX_ITEMS_PER_CATEGORY]

    return result


# ---------------------------------------------------------------------------
# Step 2：DeepSeek 中文写作
# ---------------------------------------------------------------------------

def load_style_guidelines() -> str:
    """读取 scripts/prompt.md，去除执行指令，只保留风格/内容规范"""
    if PROMPT_FILE.exists():
        raw = PROMPT_FILE.read_text(encoding="utf-8").strip()
        raw = re.sub(r"## 四、执行流程.*", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"现在开始执行[。.]?\s*$", "", raw).strip()
        print(f"    ✅ prompt.md 已加载（{len(raw)} 字符）")
        return raw
    print("    ⚠️  未找到 scripts/prompt.md，使用默认风格")
    return "请以简洁专业的风格生成三个板块：AI技术/产业动态、国际综合新闻、国内综合新闻，每板块5条，每条含标题、摘要和点评。"


WRITING_SYSTEM_TEMPLATE = """\
你是一位专业的 AI 资讯编辑。以下是你的写作风格规范，请严格遵守：

{style_guidelines}

---

补充规则（优先级高于上述规范）：
1. 你将收到今日从权威媒体 RSS 采集的真实新闻（含英文和中文原文）
2. 请基于这些真实内容撰写中文晚报，不要凭空捏造任何新闻
3. 每条新闻必须在正文中保留原始链接，格式：🔗 来源：[媒体名](链接)
4. 严格按以下顺序输出三个板块：
   - 第一板块：AI技术/产业动态（从"AI技术/产业动态"分类中选5条）
   - 第二板块：国际综合新闻（从"国际综合新闻"分类中选5条）
   - 第三板块：国内综合新闻（从"国内综合新闻"分类中选5条）
5. 若某分类的 RSS 数据不足5条，则基于已有数据撰写，不足部分可用 DeepSeek 训练知识中的近期同类新闻补充，但须标注"（知识截止）"
6. 直接输出 Markdown 格式正文，不要有任何解释说明
"""


def generate_report_from_rss(articles: dict[str, list[dict]], date_obj: datetime.date) -> Optional[str]:
    """Step 2：将三分类 RSS 文章 + prompt 风格发给 LLM，生成中文晚报"""
    style = load_style_guidelines()
    system_prompt = WRITING_SYSTEM_TEMPLATE.format(style_guidelines=style)

    date_str = date_obj.strftime("%Y年%-m月%-d日")
    user_msg = f"今天是 {date_str}。以下是今日采集的真实新闻，请据此撰写三板块晚报：\n\n"

    # 按预定顺序输出，确保 LLM 看到有序输入
    for cat in CATEGORY_ORDER:
        items = articles.get(cat, [])
        if not items:
            user_msg += f"## {cat}\n\n（当前无 RSS 数据，请基于训练知识补充近期同类新闻，标注来源）\n\n"
            continue
        user_msg += f"## {cat}\n\n"
        for i, item in enumerate(items, 1):
            summary = (item["summary"] or "")[:200]
            user_msg += f"### 原文 {i}\n"
            user_msg += f"- 标题：{item['title']}\n"
            user_msg += f"- 摘要：{summary}\n"
            user_msg += f"- 来源：{item['source']}\n"
            user_msg += f"- 链接：{item['link']}\n\n"

    if len(user_msg) > 14000:
        user_msg = user_msg[:14000] + "\n\n（内容已截断，请基于以上信息完成三板块晚报）"
        print("  ⚠️  内容过长，已截断至 14000 字符")

    return call_llm(system_prompt, user_msg, label="Step 2 中文写作")


# ---------------------------------------------------------------------------
# Step 3：格式标准化 → JSON
# ---------------------------------------------------------------------------

NORMALIZE_SYSTEM = """\
你是一个内容格式化助手。将输入的晚报 Markdown 文本严格解析为 JSON 格式。

只返回合法 JSON，不要有任何额外文字或代码块标记。JSON 结构：

{
  "highlights": ["今日看点第1条（20字以内）", "今日看点第2条", "今日看点第3条"],
  "categories": [
    {
      "title": "AI技术/产业动态",
      "items": [...]
    },
    {
      "title": "国际综合新闻",
      "items": [...]
    },
    {
      "title": "国内综合新闻",
      "items": [...]
    }
  ]
}

每个 item 的结构：
{
  "title": "条目标题（25字以内）",
  "summary": "摘要正文（1-2句，80字以内）",
  "comment": "点评内容（去掉📌前缀，1-2句，70字以内）",
  "source": "来源媒体名称",
  "link": "原文链接（原样保留，没有则为空字符串）"
}

规则：
- categories 必须严格按顺序包含三个板块：AI技术/产业动态、国际综合新闻、国内综合新闻
- highlights 从文中"今日看点"提取 2-3 条；若无，从最重要内容自行总结
- link 字段必须与原文中的链接完全一致，不得修改或捏造
- 每类最多保留 5 条
"""


def normalize_to_json(raw_content: str) -> Optional[dict]:
    """Step 3：将原始 Markdown 标准化为 JSON 结构"""
    result_text = call_llm(NORMALIZE_SYSTEM, raw_content, label="Step 3 格式标准化")
    if not result_text:
        return None

    cleaned = re.sub(r"```(?:json)?\s*", "", result_text)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        print(f"  ⚠️  JSON 解析失败，原始片段:\n{cleaned[:400]}")
        return None


# ---------------------------------------------------------------------------
# LLM 统一调用层（DeepSeek 优先，Claude / Gemini 备用）
# ---------------------------------------------------------------------------

def _call_deepseek(api_key: str, model: str, system: str, user: str) -> Optional[str]:
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")
    headers  = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload  = {
        "model": model, "max_tokens": 4096, "temperature": 0.7,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    with httpx.Client(timeout=120) as c:
        resp = c.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        if not resp.is_success:
            print(f"    ❌ HTTP {resp.status_code}：{resp.text[:300]}")
            resp.raise_for_status()
    data  = resp.json()
    usage = data.get("usage", {})
    print(f"    📊 Token 消耗：输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")
    return data["choices"][0]["message"]["content"].strip()


def _call_claude(api_key: str, model: str, system: str, user: str) -> Optional[str]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model, "max_tokens": 4096, "temperature": 0.7,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=120) as c:
        resp = c.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


def _call_gemini(api_key: str, system: str, user: str) -> Optional[str]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    with httpx.Client(timeout=60) as c:
        resp = c.post(url, json=payload)
        resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def call_llm(system: str, user: str, label: str = "") -> Optional[str]:
    """按优先级依次尝试可用的 LLM（DeepSeek > Claude > Gemini）"""
    ds_key = os.environ.get("DEEPSEEK_API_KEY",  "").strip()
    an_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gm_key = os.environ.get("GEMINI_API_KEY",    "").strip()

    providers = []
    if ds_key:
        ds_model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
        providers.append(
            (f"DeepSeek ({ds_model})", lambda m=ds_model: _call_deepseek(ds_key, m, system, user))
        )
    if an_key:
        cl_model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
        providers.append(
            (f"Claude ({cl_model})", lambda m=cl_model: _call_claude(an_key, m, system, user))
        )
    if gm_key:
        providers.append(
            ("Gemini", lambda s=system, u=user: _call_gemini(gm_key, s, u))
        )

    for name, fn in providers:
        print(f"  🤖 {label} → {name}")
        try:
            result = fn()
            if result:
                return result
        except Exception as e:
            print(f"    ❌ {name} 失败: {e}")
            traceback.print_exc()
        print(f"    ⚠️  {name} 无响应，尝试下一个...")

    return None


# ---------------------------------------------------------------------------
# Step 4：渲染为 Hugo Markdown
# ---------------------------------------------------------------------------

def extract_tags(data: dict) -> list[str]:
    """从 JSON 内容中提取相关关键词作为 Hugo 标签"""
    tag_candidates = [
        "OpenAI", "ChatGPT", "Claude", "Gemini", "DeepSeek", "Grok",
        "NVIDIA", "Meta AI", "Google DeepMind", "Anthropic", "xAI",
        "LLM", "AI Agent", "具身智能", "多模态",
    ]
    text  = json.dumps(data, ensure_ascii=False)
    found = ["AI晚报"]
    for tag in tag_candidates:
        if tag.lower() in text.lower() and tag not in found:
            found.append(tag)
        if len(found) >= 6:
            break
    return found


# 分类标题对应的 Emoji
CATEGORY_EMOJI = {
    CATEGORY_AI:       "🤖",
    CATEGORY_INTL:     "🌍",
    CATEGORY_DOMESTIC: "🇨🇳",
}


def render_markdown(date_obj: datetime.date, data: dict) -> str:
    """将标准化 JSON 渲染为 Hugo Markdown 文件（含 front matter）"""
    date_str  = date_obj.strftime("%Y年%-m月%-d日")
    date_iso  = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    highlights = data.get("highlights", [])
    categories = data.get("categories", [])
    tags       = extract_tags(data)
    tags_yaml  = json.dumps(tags, ensure_ascii=False)
    desc       = "、".join(highlights[:2]).replace('"', "'")[:120] if highlights else "每日 AI 前沿资讯"

    front_matter = textwrap.dedent(f"""\
        ---
        title: "🤖 每日AI晚报 ｜ {date_str}"
        date: {date_iso}
        draft: false
        slug: "{file_date}"
        description: "{desc}"
        summary: "{desc}"
        tags: {tags_yaml}
        categories: ["AI晚报"]
        series: ["AI晚报"]
        cover:
            image: "https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&q=80&w=1200"
            alt: "AI Daily Report {file_date}"
            caption: "小宇AI"
            relative: false
        showToc: true
        TocOpen: false
        ---
    """)

    body = f"🤖 **每日AI晚报 ｜ {date_str}**\n\n"
    if highlights:
        body += "**今日看点：**\n\n"
        for h in highlights:
            body += f"- {h}\n"
        body += "\n---\n\n"

    zh_nums = ["一", "二", "三", "四", "五", "六"]
    for idx, cat in enumerate(categories):
        cat_title = cat.get("title", "资讯")
        emoji     = CATEGORY_EMOJI.get(cat_title, "📰")
        num       = zh_nums[idx] if idx < len(zh_nums) else str(idx + 1)
        body += f"## {num}、{emoji} {cat_title}\n\n"
        for j, item in enumerate(cat.get("items", []), 1):
            title   = item.get("title",   "")
            summary = item.get("summary", "")
            comment = item.get("comment", "")
            link    = item.get("link",    "").strip()
            source  = item.get("source",  "原文")

            body += f"### {j}. {title}\n"
            if summary:
                body += f"{summary}\n\n"
            if comment:
                body += f"> 📌 **点评：** {comment}\n"
            if link:
                body += f"> 🔗 **来源：** [{source}]({link})\n"
            elif source:
                body += f"> 📰 **来源：** {source}\n"
            body += "\n"

    body += "---\n\n> 免责声明：以上内容由 AI 基于真实 RSS 数据生成，链接均来自原始报道，仅供参考，不构成投资建议。\n"
    return front_matter + body


def render_markdown_fallback(date_obj: datetime.date, raw_content: str) -> str:
    """Step 3 失败时的兜底：将原始 Markdown 套入 front matter 输出"""
    date_str  = date_obj.strftime("%Y年%-m月%-d日")
    date_iso  = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    front_matter = textwrap.dedent(f"""\
        ---
        title: "🤖 每日AI晚报 ｜ {date_str}"
        date: {date_iso}
        draft: false
        slug: "{file_date}"
        description: "每日 AI 前沿资讯"
        summary: "每日 AI 前沿资讯"
        tags: ["AI晚报"]
        categories: ["AI晚报"]
        series: ["AI晚报"]
        cover:
            image: "https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&q=80&w=1200"
            alt: "AI Daily Report {file_date}"
            caption: "小宇AI"
            relative: false
        showToc: true
        TocOpen: false
        ---
    """)
    return front_matter + raw_content


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    date_beijing = datetime.datetime.now(BEIJING_TZ).date()

    print(f"\n🚀 每日AI晚报生成器  [{date_beijing}]")
    print("=" * 54)

    if not any([
        os.environ.get("DEEPSEEK_API_KEY"),
        os.environ.get("ANTHROPIC_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
    ]):
        print("\n❌ 未检测到任何 LLM API Key。")
        print("   请设置：export DEEPSEEK_API_KEY=sk-xxx")
        sys.exit(1)

    # ── Step 1：RSS 采集 ───────────────────────────────────────────
    print("\n📡 Step 1：抓取 RSS 新闻（三个分类）...")
    articles = fetch_rss_articles(max_age_hours=36)

    total = sum(len(v) for v in articles.values())
    print(f"\n  ✅ 共抓取 {total} 条")
    for cat in CATEGORY_ORDER:
        n = len(articles.get(cat, []))
        status = f"{n} 条" if n > 0 else "0 条（将由 DeepSeek 基于训练知识补充）"
        print(f"     {cat}: {status}")

    # ── Step 2：中文写作 ──────────────────────────────────────────
    print("\n✍️  Step 2：中文写作（三板块）...")
    raw_content = generate_report_from_rss(articles, date_beijing)

    if not raw_content:
        print("\n❌ Step 2 失败，所有 LLM 均无响应，请检查 API Key 和网络。")
        sys.exit(1)

    print(f"  ✅ 原文生成完成（{len(raw_content)} 字符）")

    # ── Step 3：格式标准化 ────────────────────────────────────────
    print("\n🔧 Step 3：格式标准化（→ JSON）...")
    normalized = normalize_to_json(raw_content)

    if normalized:
        cats = normalized.get("categories", [])
        print(f"  ✅ 标准化成功（{len(cats)} 个分类）")
        markdown_content = render_markdown(date_beijing, normalized)
    else:
        print("  ⚠️  标准化失败，使用原文兜底方案")
        markdown_content = render_markdown_fallback(date_beijing, raw_content)

    # ── Step 4：写入文件 ──────────────────────────────────────────
    output_path = CONTENT_DIR / f"{date_beijing.strftime('%Y-%m-%d')}-daily-report.md"
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_content, encoding="utf-8")

    print(f"\n✅ Step 4：已写入 → {output_path}")
    print("\n🎉 全流程完成！")
    print("=" * 54)

    # 输出变量供 GitHub Actions 使用
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"report_file={output_path}\n")
            f.write(f"report_date={date_beijing}\n")


if __name__ == "__main__":
    main()
