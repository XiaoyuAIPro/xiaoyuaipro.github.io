#!/usr/bin/env python3
"""
每日AI晚报自动生成脚本 v2
============================
架构（双步 LLM 调用）：

  Step 1 — 内容生成
    将 prompt.md + 今日日期 发送给 DeepSeek，
    由模型直接生成今日晚报原文（自由格式 Markdown）

  Step 2 — 格式标准化
    将 Step 1 的原文再次发给 DeepSeek，
    要求严格输出 JSON 结构，保证每次 Hugo 文件格式一致

  Step 3 — 渲染输出
    将 JSON 渲染为带 front matter 的 Hugo Markdown 文件，
    写入 content/posts/YYYY-MM-DD-daily-report.md

支持的 LLM（按优先级）：
  DEEPSEEK_API_KEY  →  deepseek-chat（默认）或 deepseek-reasoner
  ANTHROPIC_API_KEY →  claude-3-5-sonnet-20241022（备用）
  GEMINI_API_KEY    →  gemini-2.0-flash（备用）

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
    import httpx
except ImportError:
    print("❌ 缺少依赖: httpx。请运行: pip install httpx", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
PROJECT_ROOT = Path(__file__).parent.parent
CONTENT_DIR  = PROJECT_ROOT / "content" / "posts"
PROMPT_FILE  = PROJECT_ROOT / "prompt.md"

DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_CLAUDE_MODEL   = "claude-3-5-sonnet-20241022"

# ---------------------------------------------------------------------------
# Step 1 Prompt：加载用户定义的晚报生成 prompt
# ---------------------------------------------------------------------------

def load_user_prompt(date_obj: datetime.date) -> str:
    """
    读取 prompt.md，注入今日日期后返回完整 prompt。
    如果文件不存在，使用内置的默认 prompt。
    """
    date_str = date_obj.strftime("%Y年%-m月%-d日")

    if PROMPT_FILE.exists():
        raw = PROMPT_FILE.read_text(encoding="utf-8").strip()
        # 将 prompt 中"现在开始执行。"替换为含日期的版本
        raw = re.sub(
            r"现在开始执行[。.]?\s*$",
            f"今天是 {date_str}，现在开始执行。",
            raw.strip(),
        )
        # 如果没有匹配到，直接在末尾追加日期
        if date_str not in raw:
            raw += f"\n\n今天是 {date_str}，现在开始执行。"
        return raw
    else:
        # 内置默认 prompt（兜底）
        return f"""你是一位专业 AI 资讯编辑。今天是 {date_str}，请生成一份《每日AI晚报》。

要求：
1. 综合新闻 5 条：全球热度最高的新闻（不限AI）
2. AI技术/产业动态 5 条：AI领域最新动态
3. 每条包含：标题 + 摘要（1-2句）+ 📌点评（1-2句，有观点）+ 🔗链接（尽量真实）
4. 简洁有力，适合社群快速阅读
5. 使用 Markdown 格式输出
6. 末尾附简短免责声明

现在开始执行。"""


# ---------------------------------------------------------------------------
# Step 2 Prompt：格式标准化，将自由文本转为 JSON
# ---------------------------------------------------------------------------

NORMALIZE_SYSTEM_PROMPT = """你是一个内容格式化助手。
你的任务是将输入的晚报 Markdown 文本，严格解析并转换为 JSON 格式。

要求：
1. 只返回合法的 JSON 对象，不要有任何额外文字或 markdown 代码块标记
2. JSON 结构如下：

{
  "highlights": ["今日看点第1条（20字以内）", "今日看点第2条", "今日看点第3条"],
  "categories": [
    {
      "title": "分类名称（如：综合新闻 / AI技术产业动态）",
      "items": [
        {
          "title": "条目标题（25字以内）",
          "summary": "摘要正文（1-2句话，80字以内）",
          "comment": "📌点评内容（1-2句话，去掉📌前缀）",
          "link": "原文链接（原样保留，若无则为空字符串）",
          "source": "来源媒体名称（若能从链接或文中推断）"
        }
      ]
    }
  ]
}

3. highlights 从文中"今日看点"部分提取，若无则从最重要的3条自行总结
4. link 字段原样保留原文中的链接，不要捏造，没有就填 ""
5. 每个分类的 items 数量保持原文一致（通常每类5条）
"""


# ---------------------------------------------------------------------------
# LLM 调用函数
# ---------------------------------------------------------------------------

def _call_openai_compatible(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> Optional[str]:
    """通用 OpenAI 兼容接口调用（DeepSeek 使用此格式）"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        if usage:
            print(f"    📊 Token: 输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ❌ 调用失败: {e}")
        traceback.print_exc()
        return None


def _call_claude(
    api_key: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Optional[str]:
    """Anthropic Claude 接口调用"""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"    ❌ Claude 调用失败: {e}")
        traceback.print_exc()
        return None


def _call_gemini(api_key: str, system: str, user: str) -> Optional[str]:
    """Google Gemini 接口调用"""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
    }
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    ❌ Gemini 调用失败: {e}")
        traceback.print_exc()
        return None


def call_llm(system: str, user: str, label: str = "") -> Optional[str]:
    """
    按优先级调用可用的 LLM，返回原始文本响应。
    优先级：DeepSeek > Claude > Gemini
    """
    deepseek_key  = os.environ.get("DEEPSEEK_API_KEY",  "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gemini_key    = os.environ.get("GEMINI_API_KEY",    "").strip()

    if deepseek_key:
        model = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
        print(f"  🚀 {label} → DeepSeek ({model})")
        result = _call_openai_compatible(
            deepseek_key, "https://api.deepseek.com", model, system, user
        )
        if result:
            return result
        print("  ⚠️  DeepSeek 失败，尝试备用...")

    if anthropic_key:
        model = os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
        print(f"  ✨ {label} → Claude ({model})")
        result = _call_claude(anthropic_key, model, system, user)
        if result:
            return result
        print("  ⚠️  Claude 失败，尝试备用...")

    if gemini_key:
        print(f"  🤖 {label} → Gemini")
        result = _call_gemini(gemini_key, system, user)
        if result:
            return result

    return None


# ---------------------------------------------------------------------------
# Step 1：生成晚报原文
# ---------------------------------------------------------------------------

GENERATION_SYSTEM = "你是一位专业的 AI 资讯编辑，负责生成每日 AI 晚报。请严格按用户要求的格式执行。"

def generate_raw_report(date_obj: datetime.date) -> Optional[str]:
    """Step 1：调用 LLM，生成今日晚报原文（自由格式 Markdown）"""
    user_prompt = load_user_prompt(date_obj)
    print(f"\n  📝 Prompt 已加载（{len(user_prompt)} 字符）")
    return call_llm(GENERATION_SYSTEM, user_prompt, label="Step 1 内容生成")


# ---------------------------------------------------------------------------
# Step 2：格式标准化
# ---------------------------------------------------------------------------

def normalize_to_json(raw_content: str) -> Optional[dict]:
    """Step 2：将原始 Markdown 晚报内容标准化为 JSON 结构"""
    result_text = call_llm(NORMALIZE_SYSTEM_PROMPT, raw_content, label="Step 2 格式标准化")
    if not result_text:
        return None

    # 清理可能的 markdown 代码块标记
    cleaned = re.sub(r"```(?:json)?\s*", "", result_text)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON 解析失败: {e}")
        # 尝试提取第一个 { ... } 块
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        print(f"  原始响应片段:\n{cleaned[:500]}")
        return None


# ---------------------------------------------------------------------------
# Step 3：渲染为 Hugo Markdown
# ---------------------------------------------------------------------------

def extract_tags(data: dict) -> list[str]:
    """从 JSON 数据中提取关键词作为 Hugo 标签"""
    tag_candidates = [
        "OpenAI", "ChatGPT", "Claude", "Gemini", "DeepSeek", "Grok",
        "NVIDIA", "Meta AI", "Google DeepMind", "Anthropic", "xAI",
        "LLM", "AI Agent", "具身智能", "多模态",
    ]
    text = json.dumps(data, ensure_ascii=False)
    found = ["AI晚报"]
    for tag in tag_candidates:
        if tag.lower() in text.lower() and tag not in found:
            found.append(tag)
        if len(found) >= 6:
            break
    return found


def render_markdown(date_obj: datetime.date, data: dict, raw_content: str) -> str:
    """将标准化 JSON 渲染为 Hugo Markdown 文件"""
    date_str  = date_obj.strftime("%Y年%-m月%-d日")
    date_iso  = date_obj.strftime("%Y-%m-%dT18:00:00+08:00")
    file_date = date_obj.strftime("%Y-%m-%d")

    highlights = data.get("highlights", [])
    categories = data.get("categories", [])
    tags       = extract_tags(data)
    tags_yaml  = json.dumps(tags, ensure_ascii=False)

    # 取第一条 highlight 作为 description
    desc = "、".join(highlights[:2]) if highlights else "每日 AI 前沿资讯"
    desc = desc.replace('"', "'")[:120]

    # ── Front matter ──────────────────────────────────────────────
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

    # ── 正文头部：今日看点 ─────────────────────────────────────────
    body = f"🤖 **每日AI晚报 ｜ {date_str}**\n\n"
    if highlights:
        body += "**今日看点：**\n\n"
        for h in highlights:
            body += f"- {h}\n"
        body += "\n---\n\n"

    # ── 各分类内容 ─────────────────────────────────────────────────
    zh_nums = ["一", "二", "三", "四", "五", "六", "七", "八"]
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

    # ── 免责声明 ──────────────────────────────────────────────────
    body += "---\n\n> 免责声明：以上内容由 AI 生成，链接来自模型知识库，请自行核实真实性，不构成任何投资建议。\n"

    return front_matter + body


def render_markdown_fallback(date_obj: datetime.date, raw_content: str) -> str:
    """
    Step 2 标准化失败时的兜底方案：
    将原始 Markdown 套入 Hugo front matter 直接输出。
    """
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

    print(f"\n🚀 每日AI晚报生成器 v2  [{date_beijing}]")
    print("=" * 52)

    # 检查是否有可用的 LLM API Key
    has_key = any([
        os.environ.get("DEEPSEEK_API_KEY"),
        os.environ.get("ANTHROPIC_API_KEY"),
        os.environ.get("GEMINI_API_KEY"),
    ])
    if not has_key:
        print("\n❌ 未检测到任何 API Key，无法生成晚报。")
        print("   请设置环境变量：export DEEPSEEK_API_KEY=sk-xxx")
        sys.exit(1)

    # ── Step 1：生成原文 ──────────────────────────────────────────
    print("\n📝 Step 1：调用 LLM 生成今日晚报原文...")
    raw_content = generate_raw_report(date_beijing)

    if not raw_content:
        print("\n❌ Step 1 失败，所有 LLM 均无响应，请检查 API Key 或网络。")
        sys.exit(1)

    print(f"  ✅ 原文生成完成（{len(raw_content)} 字符）")

    # ── Step 2：格式标准化 ────────────────────────────────────────
    print("\n🔧 Step 2：格式标准化（转换为 JSON 结构）...")
    normalized = normalize_to_json(raw_content)

    if normalized:
        print("  ✅ 格式标准化成功")
        markdown_content = render_markdown(date_beijing, normalized, raw_content)
    else:
        print("  ⚠️  格式标准化失败，使用原文兜底方案（front matter 套壳）")
        markdown_content = render_markdown_fallback(date_beijing, raw_content)

    # ── Step 3：写入文件 ──────────────────────────────────────────
    output_filename = f"{date_beijing.strftime('%Y-%m-%d')}-daily-report.md"
    output_path = CONTENT_DIR / output_filename
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_content, encoding="utf-8")

    print(f"\n✅ Step 3：文件已写入 → {output_path}")
    print("\n🎉 完成！")
    print("=" * 52)

    # 输出路径给 GitHub Actions 使用
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"report_file={output_path}\n")
            f.write(f"report_date={date_beijing}\n")


if __name__ == "__main__":
    main()
