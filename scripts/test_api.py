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


def list_deepseek_models(api_key: str, base_url: str = "https://api.deepseek.com") -> list[str]:
    """查询账号下可用的模型列表"""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{base_url}/models", headers=headers)
        if resp.status_code == 200:
            models = [m["id"] for m in resp.json().get("data", [])]
            return models
    except Exception:
        pass
    return []


def test_deepseek(api_key: str, model: str = "", base_url: str = "https://api.deepseek.com") -> bool:
    print(f"\n🔍 测试 DeepSeek API Key...")
    print(f"   Key 前缀: {api_key[:15]}...")
    print(f"   接口地址: {base_url}")

    # 先查询可用模型
    print("\n   📋 查询账号可用模型...")
    available = list_deepseek_models(api_key, base_url)
    if available:
        print(f"   可用模型: {available}")
    else:
        print("   ⚠️  无法获取模型列表（接口不支持 /models 查询）")

    # 自动选择模型
    if not model:
        candidates = ["deepseek-chat", "deepseek-v3", "Pro/deepseek-V3",
                      "deepseek-ai/DeepSeek-V3", "deepseek-r1", "deepseek-reasoner"]
        if available:
            # 优先从可用列表里找 chat 类型
            for c in candidates:
                if c in available:
                    model = c
                    break
            if not model:
                model = available[0]  # 用第一个
        else:
            model = "deepseek-chat"

    print(f"   使用模型: {model}")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "用一句话介绍你自己。"}],
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
        if resp.status_code == 200:
            data  = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            print(f"\n   ✅ DeepSeek API 连通成功！")
            print(f"   回复: {reply}")
            print(f"   Token 消耗: 输入 {usage.get('prompt_tokens',0)} + 输出 {usage.get('completion_tokens',0)}")
            print(f"\n   💡 GitHub Secret 配置建议：")
            print(f"      DEEPSEEK_API_KEY = （你的 Key）")
            print(f"      DEEPSEEK_MODEL   = {model}")
            if base_url != "https://api.deepseek.com":
                print(f"      DEEPSEEK_BASE_URL = {base_url}")
            return True
        else:
            err = resp.json().get("error", {})
            print(f"\n   ❌ HTTP {resp.status_code}：{err.get('message', resp.text[:300])}")
            return False
    except httpx.ConnectError:
        print("   ❌ 网络连接失败，请检查网络或代理设置")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


def test_claude(api_key: str, model: str = "claude-3-5-haiku-20241022") -> bool:
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
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "用一句话介绍你自己。"}],
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        if resp.status_code == 200:
            reply = resp.json()["content"][0]["text"]
            print(f"\n   ✅ Claude API 连通成功！")
            print(f"   回复: {reply}")
            return True
        else:
            err = resp.json().get("error", {})
            print(f"\n   ❌ HTTP {resp.status_code}：{err.get('message', resp.text[:200])}")
            return False
    except httpx.ConnectError:
        print("   ❌ 网络连接失败")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


def test_gemini(api_key: str) -> bool:
    print(f"\n🔍 测试 Gemini API Key...")
    print(f"   Key 前缀: {api_key[:20]}...")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "用一句话介绍你自己。"}]}],
        "generationConfig": {"maxOutputTokens": 50},
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
        if resp.status_code == 200:
            reply = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"\n   ✅ Gemini API 连通成功！")
            print(f"   回复: {reply}")
            return True
        else:
            print(f"\n   ❌ HTTP {resp.status_code}：{resp.text[:200]}")
            return False
    except httpx.ConnectError:
        print("   ❌ 网络连接失败")
        return False
    except Exception as e:
        print(f"   ❌ 异常: {e}")
        return False


def main():
    args = sys.argv[1:]
    tested = False

    if len(args) == 2 and args[0] == "--deepseek":
        test_deepseek(args[1]); return
    if len(args) == 2 and args[0] == "--claude":
        test_claude(args[1]); return
    if len(args) == 2 and args[0] == "--gemini":
        test_gemini(args[1]); return

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    claude_key   = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    gemini_key   = os.environ.get("GEMINI_API_KEY", "").strip()

    if deepseek_key:
        test_deepseek(deepseek_key); tested = True
    if claude_key:
        test_claude(claude_key);     tested = True
    if gemini_key:
        test_gemini(gemini_key);     tested = True

    if not tested:
        print("""
未检测到任何 API Key。使用方式：

  # 方式一：环境变量（推荐，Key 不会留在命令历史）
  export DEEPSEEK_API_KEY="sk-xxxxxxx"
  python scripts/test_api.py

  # 方式二：命令行直接传参
  python scripts/test_api.py --deepseek  sk-xxxxxxx
  python scripts/test_api.py --claude    sk-ant-xxxxxxx
  python scripts/test_api.py --gemini    AIzaxxxxxxx
""")


if __name__ == "__main__":
    main()
