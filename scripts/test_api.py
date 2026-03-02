#!/usr/bin/env python3
"""
API 连通性测试脚本
===================
测试 DeepSeek / Claude / Gemini API Key 是否有效可用。

使用方法：
  python scripts/test_api.py --deepseek  sk-xxxxxxx
  python scripts/test_api.py --claude    sk-ant-xxxxxxx
  python scripts/test_api.py --gemini    AIzaxxxxxxx
  python scripts/test_api.py             （自动测试环境变量中的所有 Key）
"""

import sys
import os
import json

try:
    import httpx
except ImportError:
    print("❌ 缺少 httpx，请先运行：pip install httpx")
    sys.exit(1)


# ─────────────────────────────────────────────
# DeepSeek 测试（OpenAI 兼容格式）
# ─────────────────────────────────────────────

def test_deepseek(api_key: str, model: str = "deepseek-chat") -> bool:
    """发送一条极简请求，验证 DeepSeek API Key 是否有效"""
    print(f"\n🔍 测试 DeepSeek API Key...")
    print(f"   Key 前缀: {api_key[:15]}...")
    print(f"   模型:     {model}  (deepseek-chat=V3, deepseek-reasoner=R1)")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "请用一句话介绍你自己。"}],
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            print(f"\n   ✅ DeepSeek API 连通成功！")
            print(f"   DeepSeek 回复: {reply}")
            print(f"   本次消耗 Token: 输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")
            return True
        else:
            print(f"\n   ❌ 请求失败，HTTP {resp.status_code}")
            try:
                err = resp.json()
                print(f"   错误详情: {err.get('error', {}).get('message', resp.text)}")
            except Exception:
                print(f"   响应内容: {resp.text[:200]}")
            return False

    except httpx.ConnectError:
        print("   ❌ 网络连接失败，请检查网络或代理设置")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


# ─────────────────────────────────────────────
# Claude 测试
# ─────────────────────────────────────────────

def test_claude(api_key: str, model: str = "claude-3-5-haiku-20241022") -> bool:
    """发送一条极简请求，验证 Claude API Key 是否有效"""
    print(f"\n🔍 测试 Claude API Key...")
    print(f"   Key 前缀: {api_key[:20]}...")
    print(f"   模型:     {model}")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 30,
        "messages": [{"role": "user", "content": "请用一句话介绍你自己。"}],
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )

        if resp.status_code == 200:
            data = resp.json()
            reply = data["content"][0]["text"]
            print(f"\n   ✅ Claude API 连通成功！")
            print(f"   Claude 回复: {reply}")
            return True
        else:
            print(f"\n   ❌ 请求失败，HTTP {resp.status_code}")
            try:
                err = resp.json()
                print(f"   错误详情: {err.get('error', {}).get('message', resp.text)}")
            except Exception:
                print(f"   响应内容: {resp.text[:200]}")
            return False

    except httpx.ConnectError:
        print("   ❌ 网络连接失败，请检查网络或代理设置")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


# ─────────────────────────────────────────────
# Gemini 测试
# ─────────────────────────────────────────────

def test_gemini(api_key: str) -> bool:
    """发送一条极简请求，验证 Gemini API Key 是否有效"""
    print(f"\n🔍 测试 Gemini API Key...")
    print(f"   Key 前缀: {api_key[:20]}...")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": "请用一句话介绍你自己。"}]}],
        "generationConfig": {"maxOutputTokens": 50},
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)

        if resp.status_code == 200:
            data = resp.json()
            reply = data["candidates"][0]["content"]["parts"][0]["text"]
            print(f"\n   ✅ Gemini API 连通成功！")
            print(f"   Gemini 回复: {reply}")
            return True
        else:
            print(f"\n   ❌ 请求失败，HTTP {resp.status_code}")
            try:
                err = resp.json()
                print(f"   错误详情: {json.dumps(err, ensure_ascii=False)[:300]}")
            except Exception:
                print(f"   响应内容: {resp.text[:200]}")
            return False

    except httpx.ConnectError:
        print("   ❌ 网络连接失败，请检查网络或代理设置")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    tested = False

    # 命令行传参模式
    if len(args) == 2 and args[0] == "--deepseek":
        test_deepseek(args[1])
        return
    if len(args) == 2 and args[0] == "--claude":
        test_claude(args[1])
        return
    if len(args) == 2 and args[0] == "--gemini":
        test_gemini(args[1])
        return

    # 自动读取环境变量，依次测试所有已配置的 Key
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    claude_key   = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gemini_key   = os.environ.get("GEMINI_API_KEY", "").strip()

    if deepseek_key:
        test_deepseek(deepseek_key)
        tested = True
    if claude_key:
        test_claude(claude_key)
        tested = True
    if gemini_key:
        test_gemini(gemini_key)
        tested = True

    if not tested:
        print("""
未检测到任何 API Key。请选择以下方式之一运行：

  # 方式一：环境变量（推荐，Key 不会出现在命令历史记录里）
  export DEEPSEEK_API_KEY="sk-xxxxxxx"
  python scripts/test_api.py

  # 方式二：命令行直接传参（快速验证）
  python scripts/test_api.py --deepseek  sk-xxxxxxx
  python scripts/test_api.py --claude    sk-ant-xxxxxxx
  python scripts/test_api.py --gemini    AIzaxxxxxxx
""")


if __name__ == "__main__":
    main()
