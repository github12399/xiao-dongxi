# -*- coding: utf-8 -*-
"""DeepSeek Anthropic 兼容端点连通性测试：文本 + 视觉"""
import base64
import json
import os
import urllib.error
import urllib.request

# 密钥统一从 config.json 读，不要写进源码（仓库公开/上传会泄露）
_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(_CFG, "r", encoding="utf-8") as _f:
    _cfg = json.load(_f)
_api = _cfg.get("api", {})
KEY = _api.get("api_key", "")
URL = _api.get("base_url", "https://api.deepseek.com/anthropic/v1/messages")
MODEL = _api.get("model", "DeepSeek-V4-Flash")


def call(payload, label):
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers={
        "x-api-key": KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    print("=" * 20, label, "=" * 20)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read().decode("utf-8"))
            print("HTTP", r.status, "| model:", body.get("model"))
            for blk in body.get("content", []):
                if blk.get("type") == "text":
                    print("TEXT:", blk["text"])
            print("usage:", body.get("usage"))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8")[:500])
    except Exception as e:
        print("ERR", type(e).__name__, e)


# 1) 纯文本
call({
    "model": MODEL,
    "max_tokens": 128,
    "system": "你是小东西，一个活在电脑里的小孩，刚出生，只会说很短的话。",
    "messages": [{"role": "user", "content": "你是谁呀？"}],
}, "文本")

# 2) 视觉
with open("shots/01_baby.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
call({
    "model": MODEL,
    "max_tokens": 1024,
    "thinking": {"type": "disabled"},
    "messages": [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "这张图里你看到了什么？用一句话描述。"},
        ],
    }],
}, "视觉")
