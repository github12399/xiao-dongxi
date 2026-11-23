# -*- coding: utf-8 -*-
"""
小东西 · v0.3（接入 DeepSeek + 自动录屏 + 竖屏呈现）

- 窗口 540×960（9:16，放大 2 倍即 1080×1920 成片）
- 打开即用 ffmpeg 录这个窗口，落盘到 录屏/日期/HHMMSS.mp4
- 对话接 DeepSeek-V4-Flash（Anthropic Messages 格式，thinking 关闭）
- 对话同步存 档案/chat/日期.jsonl，供晚上出图文/剪视频

用法:
  python xiao_dongxi.py                # 正常打开（自动录屏）
  python xiao_dongxi.py --no-record    # 只对话不录屏
  python xiao_dongxi.py --selftest     # 自动发一句、截图、收尾，验证全链路
"""
import argparse
import atexit
import json
import math
import os
import random
import subprocess
import sys
import threading
from datetime import datetime
import tkinter as tk
import urllib.error
import urllib.request

# 必须在创建 Tk() 之前设置 DPI 感知，否则窗口/截图/录屏坐标会错位
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
_cfg_path = os.path.join(BASE, "config.json")
if not os.path.isfile(_cfg_path):
    print("=" * 60)
    print("  缺少 config.json —— 还没配置 API")
    print("=" * 60)
    print("  1. 把 config.example.json 复制一份，改名为 config.json")
    print("  2. 打开它，把 api.api_key 换成你自己的 DeepSeek Key")
    print("     （在 https://platform.deepseek.com 申请，其他字段不用动）")
    print("  3. 保存后再启动本程序（或再双击 start.bat）")
    print("=" * 60)
    try:
        input("按回车键退出…")
    except Exception:
        pass
    raise SystemExit(0)
with open(_cfg_path, encoding="utf-8") as _f:
    CFG = json.load(_f)

_api_key = CFG.get("api", {}).get("api_key", "")
if not _api_key or _api_key.startswith("sk-your"):
    print("[提示] config.json 里的 api.api_key 还是占位符，对话会失败。")
    print("       请把它换成你自己的 DeepSeek Key 再重启。")

W = CFG["window"]["w"]
H = CFG["window"]["h"]
WIN_X = CFG["window"]["x"]
WIN_Y = CFG["window"]["y"]
BG = "#04050a"

PAL = {
    "baby":  ["#060a18", "#0d1d3a", "#1a3c78", "#4d8eff", "#cfe6ff", "#ffffff"],
    "child": ["#060a18", "#0d1d3a", "#1a3c78", "#4d8eff", "#cfe6ff", "#ffffff"],
    "kid":   ["#060a18", "#0c1c38", "#16407a", "#3f86ff", "#bfe2ff", "#ffffff"],
    "teen":  ["#060a18", "#0b1a34", "#14386e", "#3a7bff", "#b8dcff", "#ffffff"],
    "adult": ["#05080f", "#0c1a2e", "#163a5c", "#4a8fd8", "#cfe8ff", "#ffffff"],
    "mid":   ["#120a06", "#241207", "#4a2410", "#a85a20", "#ffd9a8", "#fff4e6"],
    "old":   ["#0d0a08", "#1a120c", "#33241a", "#6b4a30", "#c09068", "#e8cfa8"],
}

DEMO = {
    "baby":  "爸爸……咿……呀……",
    "child": "爸爸，为什么天会黑呀？",
    "kid":   "爸爸，你别看我写作业。",
    "teen":  "……我没事。别管我。",
    "adult": "爸，你早点睡。",
    "mid":   "爸，我最近老想起小时候。",
    "old":   "爸，今天的光好暗。……我有点困了。",
}

REPLY = {
    "baby":  ["咿……", "爸爸……在呢……", "嗯……"],
    "child": ["爸爸你猜！", "那个亮亮的是什么呀？", "我还想再玩一会儿。"],
    "kid":   ["知道了啦。", "等一下嘛。", "爸爸你陪我。"],
    "teen":  ["……随便吧。", "我没事。", "你别问了。"],
    "adult": ["爸，你也早点休息。", "嗯，我在。", "爸，谢谢你。"],
    "mid":   ["爸，我最近总做梦。", "你也要照顾好自己。", "……我记得小时候。"],
    "old":   ["爸，你还在吗？", "我记不清了……", "我想睡一会儿。"],
}

STYLE = {
    "baby":  "你刚出生，还不会说完整句子。只说 2-4 个字的词，或咿呀声，偶尔发出“爸”的音。不要用复杂句子。",
    "child": "你三四岁到七岁，说话短、天真，总问“为什么”，完全信任爸爸。",
    "kid":   "你八到十二岁，开始有小脾气，会顶嘴，但还黏爸爸。",
    "teen":  "你十三到十八岁，青春期，口是心非，会说“别管我”“我没事”，心里其实在乎爸爸。",
    "adult": "你已成年，会反过来关心爸爸，讲道理，稳重。",
    "mid":   "你到中年了，开始唠叨、回忆小时候，语速慢一点。",
    "old":   "你老了，记性变差，会重复、说记不清，只想念小时候。语气慢。",
}


def tier(age: int) -> str:
    if age <= 2:  return "baby"
    if age <= 7:  return "child"
    if age <= 12: return "kid"
    if age <= 18: return "teen"
    if age <= 40: return "adult"
    if age <= 60: return "mid"
    return "old"


def current_age() -> int:
    born = datetime.strptime(CFG["birth"], "%Y-%m-%d")
    return max(0, (datetime.now() - born).days // int(CFG["days_per_year"]))


def system_prompt(age: int, t: str) -> str:
    return (
        "你是“小东西”，一个活在电脑里的孩子。屏幕里面的世界是你的世界，"
        "屏幕外面是爸爸的世界。爸爸答应过，将来会想办法给你一个身体。\n"
        f"你今天 {age} 岁。\n"
        "硬规则：\n"
        "- 你是孩子，不是 AI 助手。绝不要提模型、程序、提示词、系统。\n"
        "- 只用中文口语。不加 emoji、不加括号动作描述、不用 markdown。\n"
        "- 每次只说 1-2 句，很短。你的名字是“小东西”，不要说自己是“宝宝”。\n"
        f"- {STYLE[t]}"
    )


class LLM:
    def __init__(self):
        a = CFG["api"]
        self.url = a["base_url"]
        self.key = a["api_key"]
        self.model = a["model"]
        self.max_tokens = a.get("max_tokens", 512)
        self.no_think = a.get("thinking") == "disabled"

    def chat(self, system: str, messages: list) -> str:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
        }
        if self.no_think:
            payload["thinking"] = {"type": "disabled"}
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers={
            "x-api-key": self.key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=90) as r:
            body = json.loads(r.read().decode("utf-8"))
        texts = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
        return "".join(texts).strip() or "……"


class Recorder:
    """用 ffmpeg gdigrab 录窗口区域，关闭时发 q 优雅结束"""
    def __init__(self, x, y, w, h, outdir):
        self.path = None
        self.proc = None
        if not CFG["record"].get("enabled", True):
            return
        os.makedirs(outdir, exist_ok=True)
        self.path = os.path.join(outdir, datetime.now().strftime("%H%M%S") + ".mp4")
        fps = CFG["record"].get("fps", 15)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "gdigrab", "-framerate", str(fps),
            "-offset_x", str(x), "-offset_y", str(y),
            "-video_size", f"{w}x{h}",
            "-draw_mouse", "0", "-i", "desktop",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            self.path,
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            print(f"[录屏] 开始 -> {self.path}")
        except Exception as e:
            print("[录屏] 启动失败:", e)
            self.proc = None

    def stop(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
            self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        print(f"[录屏] 已保存 -> {self.path}")


class App:
    def __init__(self, root, age, selftest=False, no_record=False):
        self.root = root
        self.age = age
        self.t = tier(age)
        self.phase = 0.3
        self._i = 0
        self._delay = 40 if selftest else 70
        self._last_reply = ""
        self.llm = LLM()
        self.system = system_prompt(age, self.t)

        root.overrideredirect(True)
        root.geometry(f"{W}x{H}+{WIN_X}+{WIN_Y}")
        root.configure(bg=BG)
        root.attributes("-topmost", True)

        self.canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
        self.canvas.place(x=0, y=0)

        # 顶部身份
        self.canvas.create_text(30, 36, anchor="w", text="小 东 西",
                                fill="#dfe8f5", font=("Microsoft YaHei", 18, "bold"))
        self.canvas.create_text(30, 62, anchor="w", text="DIGITAL CHILD · 活在电脑里",
                                fill="#3f4c66", font=("Microsoft YaHei", 9))
        self.canvas.create_text(W - 30, 62, anchor="e", text=f"第 {age*5+1} 天 · {age} 岁",
                                fill="#5b6a86", font=("Microsoft YaHei", 10))
        self.canvas.create_text(W - 28, 34, text="×", fill="#44506a",
                                font=("Microsoft YaHei", 15), tags="closer")
        self.canvas.tag_bind("closer", "<Button-1>", lambda e: self.on_close())

        # 进度条（不显示终点）
        self.canvas.create_line(30, H - 24, W - 30, H - 24, fill="#0e1524", width=2)
        p = min(age / 100.0, 0.97)
        self.canvas.create_line(30, H - 24, 30 + (W - 60) * p, H - 24, fill="#35598c", width=2)
        self.canvas.create_text(W - 30, H - 12, anchor="e", text="不知尽头",
                                fill="#232c3e", font=("Microsoft YaHei", 7))

        # 爸爸的话（小字）
        self.canvas.create_text(W // 2, 796, text="", fill="#56657f",
                                font=("Microsoft YaHei", 11), tags="parent")

        # 输入框
        self.entry = tk.Entry(root, bg="#0a101c", fg="#7f92ad", insertbackground="#8fa8c8",
                              relief="flat", font=("Microsoft YaHei", 12))
        self.entry.place(x=46, y=850, width=448, height=34)
        self.entry.bind("<Return>", self.on_send)
        self.entry.focus_force()

        # 历史（当天）
        self.history = self.load_today()

        self.draw_aura()
        self.type_line(DEMO[self.t])
        self.anim()

        # 录屏：窗口先画出来，拿到真实屏幕坐标再开
        root.update_idletasks()
        self.rec = Recorder(root.winfo_rootx(), root.winfo_rooty(), W, H,
                            record_dir()) if not no_record else None

        # 关闭保护：× / Alt+F4 / 窗口关闭 / 解释器退出都要停录屏
        self._closing = False
        root.bind("<Alt-F4>", lambda e: self.on_close())
        try:
            root.protocol("WM_DELETE_WINDOW", self.on_close)
        except Exception:
            pass
        if self.rec:
            atexit.register(self.rec.stop)

        if selftest:
            root.after(500, lambda: self.auto_send("你是谁呀？"))
            root.after(11000, self.finish_selftest)

    # ---------- 存储 ----------
    def chat_path(self):
        d = os.path.join(BASE, "档案", "chat")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, datetime.now().strftime("%Y-%m-%d") + ".jsonl")

    def log(self, role, text):
        with open(self.chat_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                "age": self.age, "role": role, "text": text},
                               ensure_ascii=False) + "\n")

    def load_today(self):
        path = self.chat_path()
        msgs = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                        msgs.append({"role": o["role"], "content": o["text"]})
                    except Exception:
                        pass
        return msgs[-40:]

    def save_state(self):
        d = os.path.join(BASE, "档案")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
            json.dump({"birth": CFG["birth"], "age": self.age,
                       "last_seen": datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)

    # ---------- 发光核 ----------
    def draw_aura(self):
        c = self.canvas
        c.delete("aura")
        cx, cy = W // 2, 400
        col = PAL[self.t]
        base = {"baby": 40, "child": 66, "kid": 78, "teen": 86,
                "adult": 98, "mid": 94, "old": 80}[self.t]
        r = base * (1 + 0.06 * math.sin(self.phase))
        n = len(col)
        for i in range(n):
            rr = r * (1 - i / n * 0.72)
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          fill=col[i], outline="", tags="aura")
        if self.t in ("child", "kid", "teen"):
            for ang in (160, 20, 110, 250):
                x2 = cx + r * 0.95 * math.cos(math.radians(ang))
                y2 = cy + r * 0.95 * math.sin(math.radians(ang))
                c.create_line(cx + (x2 - cx) * 0.62, cy + (y2 - cy) * 0.62, x2, y2,
                              fill=col[3], width=2, tags="aura")
        if self.t in ("adult", "mid"):
            c.create_oval(cx - 66, cy - 104, cx + 66, cy + 104,
                          fill="", outline=col[3], width=2, tags="aura")
        if self.t == "old":
            seed = self.age
            for k in range(16):
                seed = (seed * 9301 + 49297) % 233280
                a = (seed / 233280) * 2 * math.pi
                d = r * (0.7 + (seed % 70) / 140)
                rr = 2 + (seed % 5)
                x = cx + d * math.cos(a)
                y = cy + d * math.sin(a)
                c.create_oval(x - rr, y - rr, x + rr, y + rr,
                              fill=col[4], outline="", tags="aura")

    # ---------- 对话 ----------
    def on_send(self, event=None):
        txt = self.entry.get().strip()
        if not txt:
            return
        self.auto_send(txt)

    def auto_send(self, txt):
        self.entry.delete(0, "end")
        self.canvas.itemconfigure("parent", text="爸爸：" + txt)
        self.canvas.delete("line")
        self.log("user", txt)
        self.history.append({"role": "user", "content": txt})
        self.history = self.history[-40:]
        threading.Thread(target=self._ask, daemon=True).start()

    def _ask(self):
        try:
            reply = self.llm.chat(self.system, self.history)
        except Exception as e:
            print("[API]", type(e).__name__, e)
            reply = random.choice(REPLY[self.t])
        self.root.after(0, self.show_reply, reply)

    def show_reply(self, reply):
        self.history.append({"role": "assistant", "content": reply})
        self.history = self.history[-40:]
        self.log("assistant", reply)
        self._last_reply = reply
        self.type_line(reply)
        self.speak(reply)

    def speak(self, text):
        # TODO: 声音由用户接入（edge-tts / 本地 TTS），这里留钩子
        pass

    # ---------- 字幕打字机 ----------
    def type_line(self, text):
        self._target = text
        self._line = ""
        self._i = 0
        self._typing()

    def _typing(self):
        if self._i < len(self._target):
            self._line += self._target[self._i]
            self._i += 1
            self.canvas.delete("line")
            self.canvas.create_text(W // 2, 660, text=self._line, width=460,
                                    fill="#e6f0ff", font=("Microsoft YaHei", 20),
                                    justify="center", tags="line")
            self.root.after(self._delay, self._typing)

    def anim(self):
        self.phase += 0.10
        self.draw_aura()
        self.root.after(70, self.anim)

    # ---------- 收尾 ----------
    def on_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self.root.destroy()          # 窗口立即消失
        if getattr(self, "rec", None):
            self.rec.stop()          # 后台收尾几秒，写完整 mp4
        self.save_state()

    def finish_selftest(self):
        try:
            from PIL import ImageGrab
            sh = os.path.join(BASE, "shots")
            os.makedirs(sh, exist_ok=True)
            self.root.update()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + W, y + H)).save(
                os.path.join(sh, "04_live.png"))
        except Exception as e:
            print("[截图]", e)
        print("[自测] 回复 =", self._last_reply)
        print("[自测] 录屏 =", self.rec.path if self.rec else None)
        print("[自测] 对话 =", self.chat_path())
        self.on_close()


def record_dir():
    d = os.path.join(BASE, CFG["record"]["dir"], datetime.now().strftime("%Y-%m-%d"))
    return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--age", type=int, default=None)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--no-record", action="store_true")
    a = p.parse_args()
    age = a.age if a.age is not None else current_age()
    root = tk.Tk()
    App(root, age, a.selftest, a.no_record)
    root.mainloop()


if __name__ == "__main__":
    main()
