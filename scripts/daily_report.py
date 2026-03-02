#!/usr/bin/env python3
"""
每日AI晚报自动生成脚本
============================
功能：
  - 从多个 AI/科技领域的 RSS 源抓取当日最新资讯
  - 支持三种模式（按优先级自动选择）：
      1. Claude 模式（推荐）：使用 Anthropic Claude API，写作质量最高
         需设置环境变量 ANTHROPIC_API_KEY
         模型默认 claude-3-5-sonnet-20241022，可通过 CLAUDE_MODEL 覆盖
      2. Gemini 模式：使用 Gemini 免费 API（每日 1500 次免费额度）
         需设置环境变量 GEMINI_API_KEY
      3. 纯 RSS 模式：完全免费，无需任何 API Key，直接聚合英文原文
  - 自动生成 Hugo Markdown 文件，输出到 content/posts/

使用方法：
  - Claude 模式:  ANTHROPIC_API_KEY=your_key python scripts/daily_report.py
  - Gemini 模式:  GEMINI_API_KEY=your_key python scripts/daily_report.py
  - 纯 RSS 模式:  python scripts/daily_report.py
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

# ---------------------------------------------------------------------------
# 依赖检测
# ---------------------------------------------------------------------------
try:
    import feedparser
except ImportError:
    print("❌ 缺少依赖: feedparser。请运行: pip install feedparser", file=sys.stderr)
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None

# ---------------------------------------------------------------------------
# 配置区 — 可按需增减 RSS 源
# ---------------------------------------------------------------------------

# 时区设置（北京时间）
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

# RSS 源列表（全部免费，无需 API Key）
RSS_FEEDS = [
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
        "name": "Hacker News Top AI",
        # 过滤 HN 上关于 AI/LLM 的热门讨论（需要 100+ 点赞才纳入）
        "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22machine+learning%22+OR+%22large+language+model%22&points=80",
        "category": "综合新闻",
    },
    {
        "name": "AI News",
        "url": "https://www.artificialintelligence-news.com/feed/",
        "category": "综合新闻",
    },
    {
        "name": "Import AI (Jack Clark)",
        "url": "https://jack-clark.net/feed/",
        "category": "AI技术/产业动态",
    },
]

# 关键词过滤（英文，不区分大小写）— 只保留与 AI 强相关的文章
AI_KEYWORDS = [
    "AI", "artificial intelligence", "machine learning", "deep learning",
    "LLM", "large language model", "GPT", "Claude", "Gemini", "DeepSeek",
    "neural network", "generative", "AGI", "OpenAI", "Anthropic", "Google DeepMind",
    "NVIDIA", "transformer", "diffusion", "agent", "RAG", "fine-tuning",
    "robot", "autonomous", "computer vision", "NLP", "foundation model",
    "Mistral", "Meta AI", "Microsoft AI", "Grok", "xAI",
]

# 每个分类最多展示的条目数
MAX_ITEMS_PER_CATEGORY = 5

# 项目根目录（脚本在 scripts/ 下，向上一级）
PROJECT_ROOT = Path(__file__).parent.parent
CONTENT_DIR = PROJECT_ROOT / "content" / "posts"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def is_ai_related(title: str, summary: str = "") -> bool:
    """判断文章是否与 AI 领域相关"""
    text = (title + " " + summary).lower()
    return any(kw.lower() in text for kw in AI_KEYWORDS)


def clean_html(raw: str) -> str:
    """移除 HTML 标签，返回纯文本"""
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]  # 截取前 300 字符作摘要


def fetch_rss_articles(max_age_hours: int = 36) -> dict[str, list[dict]]:
    """
    从所有 RSS 源抓取文章，返回按分类分组的字典。
    max_age_hours: 只保留最近 N 小时内的文章
    """
    cutoff = datetime.datetime.now(BEIJING_TZ) - datetime.timedelta(hours=max_age_hours)
    categorized: dict[str, list[dict]] = {}

    for feed_config in RSS_FEEDS:
        name = feed_config["name"]
        url = feed_config["url"]
        category = feed_config["category"]
        print(f"  📡 抓取: {name} ...")

        try:
            feed = feedparser.parse(url)
            if feed.bozo:
                print(f"    ⚠️  解析警告: {feed.bozo_exception}")
        except Exception as e:
            print(f"    ❌ 失败: {e}")
            continue

        for entry in feed.entries[:20]:  # 每个源最多检查 20 条
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary_raw = entry.get("summary", "") or entry.get("description", "")
            summary = clean_html(summary_raw)

            # 过滤非 AI 相关内容
            if not is_ai_related(title, summary):
                continue

            # 解析发布时间
            pub_time = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_time = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                pub_time = pub_time.astimezone(BEIJING_TZ)
            else:
                pub_time = datetime.datetime.now(BEIJING_TZ)

            # 过滤过旧文章
            if pub_time < cutoff:
                continue

            article = {
                "title": title,
                "link": link,
                "summary": summary,
                "source": name,
                "pub_time": pub_time,
            }

            categorized.setdefault(category, []).append(article)

    # 每个分类去重（按标题关键词去重）并限制数量
    deduped: dict[str, list[dict]] = {}
    for cat, articles in categorized.items():
        seen_titles: set[str] = set()
        unique_articles = []
        for a in sorted(articles, key=lambda x: x["pub_time"], reverse=True):
            # 用标题前 30 字符做去重 key
            key = a["title"][:30].lower()
            if key not in seen_titles:
                seen_titles.add(key)
                unique_articles.append(a)
        deduped[cat] = unique_articles[:MAX_ITEMS_PER_CATEGORY]

    return deduped


# ---------------------------------------------------------------------------
# LLM 调用层（Claude / Gemini，共用同一份 Prompt 和渲染逻辑）
# ---------------------------------------------------------------------------

LLM_SYSTEM_PROMPT = """你是一位专业的 AI 领域分析师，负责撰写每日 AI 晚报。
你的读者是对 AI 感兴趣的互联网从业者和投资人，文风应当专业、简洁、有独到见解。

任务：根据下方提供的英文新闻列表，生成一篇高质量的中文 AI 晚报。

格式要求（严格遵守）：
1. 整体只返回一个合法的 JSON 对象，不要有任何额外文字
2. JSON 结构如下：
{
  "summary": "三句话今日看点，每句以✅开头，凝练有力",
  "categories": [
    {
      "title": "分类标题（如：AI技术动态 / 产业与资本 / 全球科技）",
      "items": [
        {
          "title": "中文标题（20字以内，精炼准确）",
          "body": "正文（2-3句话，100字以内，客观陈述核心事实）",
          "comment": "专业点评（2句话，80字以内，要有产业或技术视角的独到见解）",
          "source": "来源媒体名称",
          "link": "原始链接（原样保留，不得修改）"
        }
      ]
    }
  ]
}
3. link 字段必须原样保留，不得修改或省略
4. 只返回 JSON，不要包含 markdown 代码块标记
"""

# DeepSeek 默认模型，可通过环境变量 DEEPSEEK_MODEL 覆盖
# 可选值: deepseek-chat（DeepSeek-V3，速度快、价格低，推荐）
#         deepseek-reasoner（DeepSeek-R1，深度推理，适合复杂分析）
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

# Claude 默认模型，可通过环境变量 CLAUDE_MODEL 覆盖
DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet-20241022"


def call_deepseek(api_key: str, articles_json: str) -> Optional[dict]:
    """调用 DeepSeek API 生成中文晚报内容（OpenAI 兼容格式）"""
    if httpx is None:
        print("  ⚠️  缺少 httpx 库。安装: pip install httpx")
        return None

    model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    print(f"  🤖 使用模型: {model}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user",   "content": articles_json},
        ],
    }

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_text = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        print(f"  📊 Token 消耗: 输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")

        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
        return json.loads(raw_text)

    except Exception as e:
        print(f"  ❌ DeepSeek API 调用失败: {e}")
        traceback.print_exc()
        return None


def call_claude(api_key: str, articles_json: str) -> Optional[dict]:
    """调用 Anthropic Claude API 生成中文晚报内容"""
    if httpx is None:
        print("  ⚠️  缺少 httpx 库。安装: pip install httpx")
        return None

    model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
    print(f"  🤖 使用模型: {model}")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.7,
        "system": LLM_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": articles_json}
        ],
    }

    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_text = data["content"][0]["text"].strip()
        # 移除可能的 markdown 代码块包裹
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
        return json.loads(raw_text)

    except Exception as e:
        print(f"  ❌ Claude API 调用失败: {e}")
        traceback.print_exc()
        return None


def call_gemini(api_key: str, articles_json: str) -> Optional[dict]:
    """调用 Gemini API 生成中文晚报内容（备用）"""
    if httpx is None:
        print("  ⚠️  缺少 httpx 库。安装: pip install httpx")
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent"
        f"?key={api_key}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": LLM_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": articles_json}]}],
        "generationConfig": {
            "temperature": 0.7,
            "responseMimeType": "application/json",
        },
    }

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
        return json.loads(raw_text)

    except Exception as e:
        print(f"  ❌ Gemini API 调用失败: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Markdown 生成
# ---------------------------------------------------------------------------

def render_markdown_with_llm(
    date_obj: datetime.date,
    llm_result: dict,
    raw_articles: dict[str, list[dict]],
) -> str:
    """使用 LLM（Claude/Gemini）返回的结构化数据渲染 Markdown"""
    # 兼容旧调用（曾用 gemini_result 参数名）
    gemini_result = llm_result
    date_str = date_obj.strftime("%Y年%m月%d日")
    date_iso = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    summary_lines = gemini_result.get("summary", "今日 AI 动态汇总")
    categories = gemini_result.get("categories", [])

    # 从摘要中提取关键词作为 tags
    all_titles = " ".join(
        item.get("title", "")
        for cat in categories
        for item in cat.get("items", [])
    )
    tags = extract_tags(all_titles)
    tags_yaml = json.dumps(tags, ensure_ascii=False)

    # Front matter
    desc = summary_lines.replace('"', "'")[:120] if isinstance(summary_lines, str) else "每日 AI 前沿资讯"
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

    # 正文标题和看点
    body_header = f"🤖 **每日AI晚报 ｜ {date_str}**\n\n今日看点：\n\n"
    if isinstance(summary_lines, str):
        for line in summary_lines.split("✅"):
            line = line.strip()
            if line:
                body_header += f"- {line}\n"
    body_header += "\n---\n\n"

    # 分类内容
    body_sections = ""
    for i, cat in enumerate(categories, 1):
        body_sections += f"### {'一二三四五六七八九十'[i-1]}、 {cat['title']}\n\n"
        for j, item in enumerate(cat.get("items", []), 1):
            body_sections += f"#### {j}. {item.get('title', '')}\n"
            body_sections += f"{item.get('body', '')}\n\n"
            if item.get("comment"):
                body_sections += f"> 📌 **点评：** {item['comment']}\n"
            if item.get("link"):
                body_sections += f"> 🔗 **来源：** [{item.get('source', '原文')}]({item['link']})\n"
            body_sections += "\n"

    footer = "> 免责声明：以上内容由 AI 辅助生成，仅供参考，不构成投资建议。\n"

    return front_matter + body_header + body_sections + "---\n\n" + footer


def render_markdown_pure_rss(
    date_obj: datetime.date,
    articles: dict[str, list[dict]],
) -> str:
    """不依赖 LLM，直接用 RSS 原文渲染 Markdown（纯免费模式）"""
    date_str = date_obj.strftime("%Y年%m月%d日")
    date_iso = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    total = sum(len(v) for v in articles.values())
    desc = f"今日共收录 {total} 条 AI 前沿资讯，涵盖技术突破、产业动态与学术研究。"

    all_titles = " ".join(a["title"] for items in articles.values() for a in items)
    tags = extract_tags(all_titles)
    tags_yaml = json.dumps(tags, ensure_ascii=False)

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
    body += f"> 今日共收录 **{total}** 条 AI 前沿资讯，来源覆盖 TechCrunch、VentureBeat、MIT TR 等主流媒体。\n\n---\n\n"

    category_names = ["一", "二", "三", "四", "五", "六"]
    for idx, (category, items) in enumerate(articles.items()):
        roman = category_names[idx] if idx < len(category_names) else str(idx + 1)
        body += f"### {roman}、 {category}\n\n"
        for j, item in enumerate(items, 1):
            body += f"#### {j}. {item['title']}\n"
            if item["summary"]:
                body += f"{item['summary']}\n\n"
            body += f"> 🔗 **来源：** [{item['source']}]({item['link']})\n\n"

    body += "---\n\n> 免责声明：以上内容来自公开 RSS 源，由自动化脚本聚合，仅供参考。\n"
    return front_matter + body


def extract_tags(text: str, max_tags: int = 6) -> list[str]:
    """从文本中提取常见 AI 关键词作为标签"""
    tag_candidates = [
        "OpenAI", "ChatGPT", "Claude", "Gemini", "DeepSeek", "Grok",
        "NVIDIA", "Meta AI", "Google DeepMind", "Anthropic", "xAI",
        "LLM", "AI Agent", "具身智能", "多模态", "AI晚报",
    ]
    found = ["AI晚报"]
    for tag in tag_candidates:
        if tag.lower() in text.lower() and tag not in found:
            found.append(tag)
        if len(found) >= max_tags:
            break
    return found


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    today = datetime.date.today()
    date_beijing = datetime.datetime.now(BEIJING_TZ).date()

    print(f"\n🚀 开始生成每日 AI 晚报 [{date_beijing}]\n")
    print("=" * 50)

    # Step 1: 抓取 RSS
    print("\n📡 Step 1: 抓取 RSS 源...")
    articles = fetch_rss_articles(max_age_hours=36)

    if not articles:
        print("⚠️  未抓取到任何文章，退出。")
        sys.exit(1)

    total = sum(len(v) for v in articles.items())
    print(f"\n✅ 共抓取 {sum(len(v) for v in articles.values())} 篇相关文章")
    for cat, items in articles.items():
        print(f"   - {cat}: {len(items)} 篇")

    # Step 2: 按优先级选择生成模式
    #   优先级: DEEPSEEK_API_KEY > ANTHROPIC_API_KEY > GEMINI_API_KEY > 纯 RSS
    deepseek_api_key  = os.environ.get("DEEPSEEK_API_KEY",  "").strip()
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gemini_api_key    = os.environ.get("GEMINI_API_KEY",    "").strip()
    markdown_content  = ""

    # 将文章序列化为 JSON，供 LLM 使用
    articles_for_llm = []
    for cat, items in articles.items():
        for item in items:
            articles_for_llm.append({
                "category": cat,
                "title": item["title"],
                "summary": item["summary"],
                "source": item["source"],
                "link": item["link"],
            })
    articles_json = json.dumps(articles_for_llm, ensure_ascii=False, indent=2)

    # 按优先级逐级尝试，失败则自动降级
    llm_result = None
    if deepseek_api_key:
        print("\n🚀 Step 2: 检测到 DEEPSEEK_API_KEY，使用 DeepSeek 写作模式...")
        llm_result = call_deepseek(deepseek_api_key, articles_json)
        if llm_result:
            print("  ✅ DeepSeek 生成成功")

    if not llm_result and anthropic_api_key:
        print("\n✨ Step 2: 使用 Claude 备用模式...")
        llm_result = call_claude(anthropic_api_key, articles_json)
        if llm_result:
            print("  ✅ Claude 生成成功")

    if not llm_result and gemini_api_key:
        print("\n🤖 Step 2: 使用 Gemini 备用模式...")
        llm_result = call_gemini(gemini_api_key, articles_json)
        if llm_result:
            print("  ✅ Gemini 生成成功")

    if llm_result:
        markdown_content = render_markdown_with_llm(date_beijing, llm_result, articles)
    else:
        if not any([deepseek_api_key, anthropic_api_key, gemini_api_key]):
            print("\n📋 Step 2: 未设置任何 API Key，使用纯 RSS 聚合模式（完全免费）")
        else:
            print("\n⚠️  所有 LLM API 均失败，回退到纯 RSS 模式")
        markdown_content = render_markdown_pure_rss(date_beijing, articles)

    # Step 3: 写入文件
    output_filename = f"{date_beijing.strftime('%Y-%m-%d')}-daily-report.md"
    output_path = CONTENT_DIR / output_filename

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_content, encoding="utf-8")

    print(f"\n✅ Step 3: 文件已生成 → {output_path}")
    print("\n🎉 完成！")
    print("=" * 50)

    # 输出文件路径，供 GitHub Actions 使用
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"report_file={output_path}\n")
            f.write(f"report_date={date_beijing}\n")


if __name__ == "__main__":
    main()
