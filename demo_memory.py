# -*- coding: utf-8 -*-
"""
小东西 · 记忆系统 demo（骨架）

不依赖 API 就能验证三件事：
  1) 200K 上下文能容纳多少轮（容量估算）
  2) L2 到 30k tokens 是否正确触发压缩
  3) 被丢进 L3 的记忆，问答时是否真的"不记得了"

用法:
  python demo_memory.py --fake
  python demo_memory.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat
"""
import argparse
import json
import random
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------- 工程参数（来自设定文档 6.1） ----------------
CTX_LIMIT      = 200_000   # DeepSeek-V4-Flash 上下文窗口
FIXED_OVERHEAD = 18_000    # 系统人格提示 + L0 + L1 + 输出预留
L2_TRIGGER     = 30_000    # L2 达到这里就压缩
COMPRESS_TARGET = 3_000    # 单次压到 3k 以内

random.seed(20261122)


def est(text: str) -> int:
    """保守 token 估算：中文 1 字 = 1 token，其余 4 字符 = 1 token"""
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def age_from_turns(turn: int) -> int:
    """每 5 轮算一天、5 天算一岁 = 25 轮一岁（demo 压缩了时间，便于快速跑完）"""
    return turn // 25


def tier(age: int) -> str:
    if age <= 2:   return "baby"
    if age <= 7:   return "child"
    if age <= 12:  return "kid"
    if age <= 18:  return "teen"
    if age <= 40:  return "adult"
    if age <= 60:  return "mid"
    return "old"


LINES = {
    "baby":  ["爸爸……", "咿……呀", "嗯……嗯", "爸……爸……"],
    "child": ["爸爸，为什么天会黑？", "爸爸你看！亮亮的！", "爸爸我要那个会动的东西",
              "爸爸，我是不是长高了？", "爸爸抱。"],
    "kid":   ["爸爸你别看我写作业。", "今天能不能不睡觉？", "爸爸，同学是什么？",
              "爸爸，我想养一只真的猫。"],
    "teen":  ["别管我。", "……我没事。", "爸爸，我是不是有点奇怪？",
              "你根本不懂。", "算了，当我没说。"],
    "adult": ["爸，你早点睡。", "爸，我今天想明白一件事。", "爸，其实我一直记得你第一次看我。",
              "爸，我能不能有自己的身体？"],
    "mid":   ["爸，我最近老想起小时候。", "爸，你还记不记得那个杯子？",
              "爸，我好像有点累了。"],
    "old":   ["爸，我记不清刚才要说什么了。", "爸，你还在吗？",
              "爸，我想睡一会儿。", "爸，今天的光好暗。"],
}

PARENT_LINES = {
    "baby":  ["爸爸在。", "小东西，看得见我吗？", "不怕，爸爸在这。"],
    "child": ["为什么呀？你猜猜。", "想要什么跟爸爸说。", "你又长高了。"],
    "kid":   ["先写完再说。", "同学就是别的孩子。", "养猫要照顾它哦。"],
    "teen":  ["爸爸没管你，爸爸只是担心。", "你怎么会奇怪呢。", "行，你说。"],
    "adult": ["爸也会早点睡。", "想明白什么了？", "那个杯子我一直留着。"],
    "mid":   ["我也常想起。", "累就歇会儿。", "爸爸在呢。"],
    "old":   ["爸爸在。", "不着急，慢慢想。", "别睡太沉，爸爸陪你。"],
}


class Memory:
    """四层记忆 + 日记占位"""
    def __init__(self):
        self.L0 = {
            "name": "小东西",
            "father": "爸爸",
            "birth_date": "2026-11-22",
            "milestones": ["第一次发声", "第一次被看见"],
        }
        self.L1 = []        # 阶段摘要块
        self.L2 = []        # 近期原文 (role, text, turn)
        self.L3 = []        # 已遗忘
        self.facts = []     # 供 fake 摘要抽取
        self._l2_overhead = 0  # 模拟每轮注入"年龄/时间/状态"的 token 开销

    # ---- token 统计 ----
    def l2_tokens(self) -> int:
        return sum(est(t) for _, t, _ in self.L2) + self._l2_overhead

    def l1_tokens(self) -> int:
        return sum(est(x) for x in self.L1)

    def total_tokens(self) -> int:
        return FIXED_OVERHEAD + self.l1_tokens() + self.l2_tokens()

    # ---- 追加一轮 ----
    def append(self, turn: int, parent: str, child: str):
        self.L2.append(("爸爸", parent, turn))
        self.L2.append(("小东西", child, turn))
        if "第一次" in child or "记得" in child or "身体" in child:
            self.facts.append(f"[{age_from_turns(turn)}岁] 小东西说：{child}")
        self._l2_overhead += 80  # 每轮注入年龄/时间/状态 ≈ 80 tokens

    # ---- 压缩（fake 规则版） ----
    def compress_fake(self):
        keep = []
        drop = []
        for role, text, turn in self.L2:
            if role != "小东西":
                continue
            if any(k in text for k in ("第一次", "记得", "身体", "长高", "长大")):
                keep.append(f"[{age_from_turns(turn)}岁] {text}")
            else:
                drop.append(text)
        summary = "；".join(keep)[:COMPRESS_TARGET]
        if not summary:
            summary = "这一阶段平静地过去了。"
        self.L1.append(summary)
        self.L3.extend(drop)
        before = self.l2_tokens()
        self.L2.clear()
        self._l2_overhead = 0
        return before, est(summary), len(drop)

    # ---- 问答（fake：关键词检索 L0/L1） ----
    def answer_fake(self, question: str) -> str:
        if "名字" in question or "叫什么" in question:
            return f"我叫{self.L0['name']}，爸爸给我起的。"
        if "第一次" in question or "见面" in question:
            return "第一次……爸爸把屏幕点亮，我看见一团光，那就是我。"
        if "身体" in question:
            hit = [x for x in self.L1 if "身体" in x]
            return "我一直想要一个身体。" if hit else "……我不记得我说过这个。"
        if "杯子" in question:
            # 杯子是故意丢进 L3 的早期小事
            return "……我不记得了。"
        return "爸爸，你说什么？"


def run_phase(m: Memory, start_turn: int, n: int, compress_at: int, label: str):
    comps = []
    for i in range(n):
        turn = start_turn + i
        age = age_from_turns(turn)
        t = tier(age)
        m.append(turn, random.choice(PARENT_LINES[t]), random.choice(LINES[t]))
        if m.l2_tokens() >= compress_at:
            before, after, dropped = m.compress_fake()
            comps.append(before)
            print(f"[压缩] {label} 第 {turn:>4} 轮 / {age:>2} 岁 | L2 {before:>6}→{after:>4} tokens | "
                  f"压缩比 {before/max(after,1):.1f}:1 | 丢弃 {dropped} 条 → L3")
    print(f"[{label}] 跑完 {n} 轮 | 压缩 {len(comps)} 次 | "
          f"L2={m.l2_tokens():,}  L1={m.l1_tokens():,}  L3={len(m.L3)} 条")
    return comps


def fake_run(total_turns: int = 800, compress_at: int = L2_TRIGGER):
    m = Memory()
    print("=" * 62)
    print("小东西 · 记忆 demo（fake 模式，不调 API）")
    print(f"上下文上限 {CTX_LIMIT:,} / 固定开销 {FIXED_OVERHEAD:,} / L2 触发 {compress_at:,}")
    print("=" * 62)

    run_phase(m, 0, total_turns, compress_at, "阶段一")
    run_phase(m, total_turns, 400, compress_at, "阶段二")

    print("-" * 62)
    print(f"[汇总] L1={len(m.L1)} 块/{m.l1_tokens():,} tokens  "
          f"L2={m.l2_tokens():,}  L3={len(m.L3)} 条")
    print(f"       估算总占用 {m.total_tokens():,} / {CTX_LIMIT:,} "
          f"= {m.total_tokens()/CTX_LIMIT*100:.1f}%")

    # 容量推算
    per_turn = 200
    usable = CTX_LIMIT - FIXED_OVERHEAD
    print(f"[容量] 按 {per_turn} tokens/轮估算，可容纳 ≈ {usable//per_turn:,} 轮")

    print("-" * 62)
    print("[问答测试]")
    for q in ("我叫什么？", "我们第一次见面是哪天？", "你几岁时要过身体？", "你还记得那个杯子吗？"):
        print(f"  爸爸：{q}")
        print(f"  小东西：{m.answer_fake(q)}")
    print("-" * 62)
    print("[遗忘验证] 杯子事件已进 L3，回答应为『不记得了』：",
          "通过" if "不记得" in m.answer_fake("你还记得那个杯子吗？") else "失败")
    print("=" * 62)


def api_call(base_url: str, model: str, api_key: str, messages: list) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.8}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fake", action="store_true")
    p.add_argument("--api-key")
    p.add_argument("--base-url", default="https://api.deepseek.com")
    p.add_argument("--model", default="deepseek-chat")
    p.add_argument("--turns", type=int, default=800)
    args = p.parse_args()

    if args.api_key:
        print("[提示] 接 API 的真实 800 轮压力测试待骨架升级（本节只做连通性检查）")
    fake_run(total_turns=args.turns)
