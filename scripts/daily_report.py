#!/usr/bin/env python3
"""
每日AI晚报自动生成脚本 v3
============================
架构：

  Step 1 — RSS 真实数据采集
    从多个权威媒体 RSS 源抓取当日 AI / 科技新闻
    → 保证每条新闻都有真实可点击的原文链接

  Step 2 — DeepSeek 中文写作（遵循 scripts/prompt.md 风格）
    将 RSS 原文 + 用户的 prompt 风格要求发给 DeepSeek
    → 生成高质量中文摘要与专业点评

  Step 3 — 格式标准化
    将 Step 2 输出再次发给 LLM，转为严格的 JSON 结构
    → 保证每次 Hugo 文件格式完全一致

  Step 4 — 渲染输出
    将 JSON 渲染为带 front matter 的 Hugo Markdown 文件

优先级：DEEPSEEK_API_KEY > ANTHROPIC_API_KEY > GEMINI_API_KEY

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
PROMPT_FILE  = Path(__file__).parent / "prompt.md"   # scripts/prompt.md

DEFAULT_DEEPSEEK_MODEL    = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_CLAUDE_MODEL      = "claude-3-5-sonnet-20241022"

# ---------------------------------------------------------------------------
# RSS 数据源（保证链接真实性）
# ---------------------------------------------------------------------------

RSS_FEEDS = [
    # ── AI / 科技专项（用于"AI技术/产业动态"）─────────────────
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": "AI技术/产业动态",
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/ai/feed/",
        "category": "AI技术/产业动态",
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
        "category": "AI技术/产业动态",
    },
    {
        "name": "MIT Technology Review",
        "url": "https://www.technologyreview.com/feed/",
        "category": "AI技术/产业动态",
    },
    {
        "name": "AI News",
        "url": "https://www.artificialintelligence-news.com/feed/",
        "category": "AI技术/产业动态",
    },
    {
        "name": "Hacker News Top AI",
        "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22machine+learning%22&points=80",
        "category": "AI技术/产业动态",
    },
    # ── 综合新闻（全球热点，不限主题）────────────────────────────
    {
        "name": "Reuters World",
        "url": "https://feeds.reuters.com/reuters/worldNews",
        "category": "综合新闻",
    },
    {
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "综合新闻",
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "category": "综合新闻",
    },
    {
        "name": "Al Jazeera",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "category": "综合新闻",
    },
]

# AI 关键词过滤（用于综合新闻源中筛选 AI 相关内容）
AI_KEYWORDS = [
    "AI", "artificial intelligence", "machine learning", "deep learning",
    "LLM", "large language model", "GPT", "Claude", "Gemini", "DeepSeek",
    "neural network", "generative", "AGI", "OpenAI", "Anthropic", "DeepMind",
    "NVIDIA", "transformer", "diffusion", "agent", "robot", "autonomous",
    "Mistral", "Meta AI", "Microsoft AI", "Grok", "xAI", "foundation model",
]

MAX_ITEMS_PER_CATEGORY = 6   # 每分类最多保留条数（多留几条给 LLM 筛选）


# ---------------------------------------------------------------------------
# Step 1：RSS 数据采集
# ---------------------------------------------------------------------------

def is_ai_related(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in AI_KEYWORDS)


def clean_html(raw: str) -> str:
    """移除 HTML 标签；清理 HackerNews 元数据行"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    # 清理 hnrss 特有格式
    text = re.sub(r"Article URL:.*?(?=Comments URL:|$)", "", text, flags=re.DOTALL)
    text = re.sub(r"Comments URL:.*?(?=Points:|$)",      "", text, flags=re.DOTALL)
    text = re.sub(r"Points:\s*\d+.*",                    "", text, flags=re.DOTALL)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:400]


def fetch_rss_articles(max_age_hours: int = 36) -> dict[str, list[dict]]:
    """
    从所有 RSS 源抓取文章，返回按分类分组的字典。
    每条文章均含真实可点击的原文链接。
    """
    cutoff = datetime.datetime.now(BEIJING_TZ) - datetime.timedelta(hours=max_age_hours)
    categorized: dict[str, list[dict]] = {}

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

            # AI 分类：只保留 AI 相关内容
            # 综合新闻：不过滤，保留所有全球热点
            if category == "AI技术/产业动态" and not is_ai_related(title, summary):
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

            categorized.setdefault(category, []).append({
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
    for cat, articles in categorized.items():
        seen: set[str] = set()
        unique = []
        for a in sorted(articles, key=lambda x: x["pub_time"], reverse=True):
            key = a["title"][:35].lower()
            if key not in seen:
                seen.add(key)
                unique.append(a)
        result[cat] = unique[:MAX_ITEMS_PER_CATEGORY]

    return result


# ---------------------------------------------------------------------------
# Step 2：LLM 中文写作（遵循用户 prompt 风格）
# ---------------------------------------------------------------------------

def load_style_guidelines() -> str:
    """读取 scripts/prompt.md 中的风格要求（去掉执行指令，只保留规范说明）"""
    if PROMPT_FILE.exists():
        raw = PROMPT_FILE.read_text(encoding="utf-8").strip()
        raw = re.sub(r"(现在开始执行[。.]?\s*)$", "", raw.strip())
        raw = re.sub(r"## 四、执行流程.*", "", raw, flags=re.DOTALL).strip()
        print(f"    ✅ prompt.md 已加载（{len(raw)} 字符）")
        return raw
    print("    ⚠️  未找到 scripts/prompt.md，使用默认风格")
    return "请以简洁专业的风格生成内容，每条包含标题、摘要和点评。"


WRITING_SYSTEM_TEMPLATE = """\
你是一位专业的 AI 资讯编辑。以下是你的写作风格规范，请严格遵守：

{style_guidelines}

---

重要规则：
1. 你将收到一批今日从权威媒体 RSS 采集的真实新闻原文（英文）
2. 请基于这些真实内容撰写中文晚报，不要凭空捏造新闻
3. 每条新闻必须原样保留原始链接（link 字段），绝对不能修改或省略
4. 综合新闻和 AI 技术动态各选最重要的 5 条，不足 5 条则全部保留
5. 直接输出 Markdown 格式的晚报正文，不需要任何解释说明
"""


def generate_report_from_rss(articles: dict[str, list[dict]], date_obj: datetime.date) -> Optional[str]:
    """
    Step 2：将 RSS 文章 + 用户风格 prompt 发给 LLM，生成中文晚报原文。
    """
    style = load_style_guidelines()
    system_prompt = WRITING_SYSTEM_TEMPLATE.format(style_guidelines=style)

    date_str = date_obj.strftime("%Y年%-m月%-d日")
    articles_text = f"今天是 {date_str}。以下是今日采集的真实新闻，请据此撰写晚报：\n\n"

    for cat, items in articles.items():
        articles_text += f"## {cat}\n\n"
        for i, item in enumerate(items, 1):
            # 摘要截短，避免单条过长
            summary = item['summary'][:200] if item['summary'] else ""
            articles_text += f"### 原文 {i}\n"
            articles_text += f"- 标题：{item['title']}\n"
            articles_text += f"- 摘要：{summary}\n"
            articles_text += f"- 来源：{item['source']}\n"
            articles_text += f"- 链接：{item['link']}\n\n"

    # 安全检查：若总字符数超过 12000，截断多余内容
    MAX_USER_CHARS = 12000
    if len(articles_text) > MAX_USER_CHARS:
        articles_text = articles_text[:MAX_USER_CHARS] + "\n\n（以上为截断内容，请基于已有信息完成晚报）"
        print(f"  ⚠️  文章内容过长，已截断至 {MAX_USER_CHARS} 字符")

    return call_llm(system_prompt, articles_text, label="Step 2 中文写作")


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
      "title": "分类名称",
      "items": [
        {
          "title": "条目标题（25字以内）",
          "summary": "摘要正文（1-2句，80字以内）",
          "comment": "点评内容（去掉📌前缀，1-2句，70字以内）",
          "source": "来源媒体名称",
          "link": "原文链接（原样保留，没有则为空字符串）"
        }
      ]
    }
  ]
}

规则：
- highlights 从文中"今日看点"提取；若无，从最重要3条自行总结
- link 字段必须与原文中的链接完全一致，不得修改或捏造
- 每类最多保留5条
"""


def normalize_to_json(raw_content: str) -> Optional[dict]:
    """Step 3：将原始 Markdown 标准化为 JSON"""
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
# LLM 统一调用层
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
    print(f"    📏 System: {len(system)} 字符 | User: {len(user)} 字符")
    with httpx.Client(timeout=120) as c:
        resp = c.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        if not resp.is_success:
            print(f"    ❌ HTTP {resp.status_code}，响应体：{resp.text[:500]}")
            resp.raise_for_status()
    data  = resp.json()
    usage = data.get("usage", {})
    print(f"    📊 Token: 输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")
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
    """按优先级调用 LLM：DeepSeek > Claude > Gemini"""
    ds_key  = os.environ.get("DEEPSEEK_API_KEY",  "").strip()
    an_key  = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gm_key  = os.environ.get("GEMINI_API_KEY",    "").strip()

    providers = []
    if ds_key:
        ds_model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
        # 用默认参数捕获当前值，避免 lambda 闭包延迟绑定 bug
        providers.append((f"DeepSeek ({ds_model})", lambda m=ds_model: _call_deepseek(ds_key, m, system, user)))
    if an_key:
        cl_model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
        providers.append((f"Claude ({cl_model})", lambda m=cl_model: _call_claude(an_key, m, system, user)))
    if gm_key:
        providers.append(("Gemini", lambda s=system, u=user: _call_gemini(gm_key, s, u)))

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


def render_markdown(date_obj: datetime.date, data: dict) -> str:
    date_str  = date_obj.strftime("%Y年%-m月%-d日")
    date_iso  = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    highlights = data.get("highlights", [])
    categories = data.get("categories", [])
    tags       = extract_tags(data)
    tags_yaml  = json.dumps(tags, ensure_ascii=False)

    desc = "、".join(highlights[:2]).replace('"', "'")[:120] if highlights else "每日 AI 前沿资讯"

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
            caption: "智启未来，始于今日"
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
        num = zh_nums[idx] if idx < len(zh_nums) else str(idx + 1)
        body += f"### {num}、 {cat.get('title', '资讯')}\n\n"
        for j, item in enumerate(cat.get("items", []), 1):
            title   = item.get("title", "")
            summary = item.get("summary", "")
            comment = item.get("comment", "")
            link    = item.get("link", "").strip()
            source  = item.get("source", "原文")

            body += f"#### {j}. {title}\n"
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
    """Step 3 失败时的兜底：套入 front matter 直接输出"""
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
            caption: "智启未来，始于今日"
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

    print(f"\n🚀 每日AI晚报生成器 v3  [{date_beijing}]")
    print("=" * 54)

    if not any([
        os.environ.get("DEEPSEEK_API_KEY"),
        os.environ.get("ANTHROPIC_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
    ]):
        print("\n❌ 未检测到任何 API Key。")
        print("   请设置：export DEEPSEEK_API_KEY=sk-xxx")
        sys.exit(1)

    # ── Step 1：RSS 采集 ───────────────────────────────────────────
    print("\n📡 Step 1：抓取真实 RSS 新闻...")
    articles = fetch_rss_articles(max_age_hours=36)

    total = sum(len(v) for v in articles.values())
    if total == 0:
        print("  ⚠️  RSS 抓取无结果，请检查网络")
        sys.exit(1)

    print(f"\n  ✅ 共抓取 {total} 条，分类：")
    for cat, items in articles.items():
        print(f"     - {cat}: {len(items)} 条")

    # ── Step 2：LLM 中文写作 ──────────────────────────────────────
    print("\n✍️  Step 2：DeepSeek 中文写作（遵循 prompt.md 风格）...")
    raw_content = generate_report_from_rss(articles, date_beijing)

    if not raw_content:
        print("\n❌ Step 2 失败，所有 LLM 均无响应。")
        sys.exit(1)

    print(f"  ✅ 原文生成完成（{len(raw_content)} 字符）")

    # ── Step 3：格式标准化 ────────────────────────────────────────
    print("\n🔧 Step 3：格式标准化（→ JSON）...")
    normalized = normalize_to_json(raw_content)

    if normalized:
        print("  ✅ 标准化成功")
        markdown_content = render_markdown(date_beijing, normalized)
    else:
        print("  ⚠️  标准化失败，使用原文兜底")
        markdown_content = render_markdown_fallback(date_beijing, raw_content)

    # ── Step 4：写入文件 ──────────────────────────────────────────
    output_path = CONTENT_DIR / f"{date_beijing.strftime('%Y-%m-%d')}-daily-report.md"
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_content, encoding="utf-8")

    print(f"\n✅ Step 4：已写入 → {output_path}")
    print("\n🎉 全流程完成！")
    print("=" * 54)

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"report_file={output_path}\n")
            f.write(f"report_date={date_beijing}\n")


if __name__ == "__main__":
    main()
