#!/usr/bin/env python3
"""
DeepSeek 余额监控悬浮窗 — 黑客终端风格
- 折叠态：屏幕右下角小标签，显示总余额
- 展开态：鼠标悬停展开完整终端风格卡片
- 支持多 API Key 监控、黑客美学设计
"""

import tkinter as tk
import json
import os
import sys
import math
import threading
import queue
import datetime
import ctypes

import requests

# ── 常量 ─────────────────────────────────────────────

APP_NAME = "DeepSeekMonitor"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
BALANCE_URL = "https://api.deepseek.com/user/balance"
VERSION = "2.0.0"

# 窗口尺寸
COLLAPSED_W = 170
COLLAPSED_H = 36
EXPANDED_W = 340
EXPANDED_H = 400

# 动画参数 — 轻量快速
EXPAND_FRAMES = 5
EXPAND_INTERVAL = 18
COLLAPSE_FRAMES = 4
COLLAPSE_INTERVAL = 16

# ── 黑客终端配色 ──
BG_TERMINAL = "#0a0a0a"       # 终端黑底
TEXT_GREEN = "#00ff41"        # 荧光绿主色
TEXT_GREEN_DIM = "#0a7a2e"    # 暗绿副色
TEXT_AMBER = "#ffb000"        # 琥珀色（余额高亮）
TEXT_RED = "#ff3333"          # 红色（错误）
TEXT_WHITE = "#c0c0c0"        # 灰白（次要文字）
BORDER_GREEN = "#0f3a1f"      # 暗绿边框
SURFACE_TERMINAL = "#0f0f0f"  # 微亮表面
SCANLINE = "#00ff41"          # 扫描线颜色

# Win32 常量
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080


# ── 工具函数 ─────────────────────────────────────────

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def lerp(a, b, t):
    return a + (b - a) * t


def hex_to_rgb(h):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


# ── 主类 ─────────────────────────────────────────────

class DeepSeekMonitor:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

        # ── 状态 ──
        self.config = self._load_config()
        self.balances = []       # 每个 key 的余额数据: [{key, label, balance, error}]
        self.last_refresh = None
        self.is_expanded = False
        self.animating = False
        self.collapse_after_id = None
        self.anim_after_ids = []
        self.error_count = 0
        self.fetch_thread = None
        self.data_queue = queue.Queue()
        self._drag_x = None
        self._drag_y = None
        self.cur_w = COLLAPSED_W
        self.cur_h = COLLAPSED_H
        self._refresh_btn_coords = None
        self._total_balance = 0.0

        # 扫描线偏移
        self._scanline_offset = 0.0
        self._blink_phase = False

        # ── 搭建窗口 ──
        self._setup_window()
        self._position_window()
        self._create_canvas()
        self._bind_events()
        self.root.deiconify()
        self._apply_ghost_style()
        self._draw()

        # 预计算颜色 RGB
        self._bg_rgb = hex_to_rgb(BG_TERMINAL)

        # ── 启动 ──
        self._schedule_refresh()
        self._poll_queue()
        self._blink_tick()

        if not self.config.get("api_keys"):
            self.root.after(600, self.show_api_key_dialog)

    # ─────────────────── 配置 ───────────────────

    def _load_config(self):
        defaults = {
            "api_keys": [],
            "window": {"x": None, "y": None},
            "refresh_interval_seconds": 30,
            "token_usage_daily": {},
        }
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    d = json.load(f)
                for k in defaults:
                    d.setdefault(k, defaults[k])
                # 兼容旧版单 key 格式
                if not d.get("api_keys") and d.get("api_key"):
                    d["api_keys"] = [{"label": "默认", "key": d.pop("api_key")}]
                return d
        except Exception:
            pass
        return defaults

    def save_config(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ─────────────────── 窗口属性 ───────────────────

    def _setup_window(self):
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.attributes("-alpha", 0.72)
        r.configure(bg=BG_TERMINAL)
        r.title("DeepSeek Monitor")

    def _apply_ghost_style(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if hwnd == 0:
                hwnd = self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _position_window(self):
        r = self.root
        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        x = self.config["window"]["x"]
        y = self.config["window"]["y"]
        if x is None or y is None:
            x = sw - COLLAPSED_W - 20
            y = sh - COLLAPSED_H - 60
        r.geometry(f"{COLLAPSED_W}x{COLLAPSED_H}+{x}+{y}")

    def _set_geometry(self, w, h):
        r = self.root
        x = r.winfo_x()
        y = r.winfo_y()
        right = x + r.winfo_width()
        bottom = y + r.winfo_height()
        r.geometry(f"{w}x{h}+{right - w}+{bottom - h}")

    def _create_canvas(self):
        self.canvas = tk.Canvas(
            self.root, width=EXPANDED_W, height=EXPANDED_H,
            bg=BG_TERMINAL, highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

    # ─────────────────── 事件绑定 ───────────────────

    def _bind_events(self):
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Double-Button-1>", lambda e: self.show_api_key_dialog())
        self.root.bind("<Escape>", lambda e: self.quit())

    def _on_click(self, event):
        if self._refresh_btn_coords:
            bx1, by1, bx2, by2 = self._refresh_btn_coords
            if bx1 <= event.x <= bx2 and by1 <= event.y <= by2:
                self._manual_refresh()
                return
        if not self.is_expanded and not self.animating:
            self._cancel_collapse()
            self._animate_expand()
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_enter(self, event):
        if not self.is_expanded and not self.animating:
            self._cancel_collapse()
            self._animate_expand()

    def _on_leave(self, event):
        if self.is_expanded and not self.animating:
            self._schedule_collapse()

    def _schedule_collapse(self):
        self._cancel_collapse()
        self.collapse_after_id = self.root.after(350, self._do_collapse)

    def _cancel_collapse(self):
        if self.collapse_after_id:
            self.root.after_cancel(self.collapse_after_id)
            self.collapse_after_id = None

    def _do_collapse(self):
        if self.is_expanded and not self.animating:
            self._animate_collapse()

    # ─────────────────── 拖拽 ───────────────────

    def _on_mouse_move(self, event):
        if self._drag_x is not None:
            dx = event.x - self._drag_x
            dy = event.y - self._drag_y
            r = self.root
            nx = r.winfo_x() + dx
            ny = r.winfo_y() + dy
            sw = r.winfo_screenwidth()
            sh = r.winfo_screenheight()
            nx = clamp(nx, -self.cur_w + 30, sw - 30)
            ny = clamp(ny, -20, sh - 20)
            r.geometry(f"{self.cur_w}x{self.cur_h}+{nx}+{ny}")

    def _on_mouse_up(self, event):
        self._drag_x = None
        self._drag_y = None
        r = self.root
        self.config["window"]["x"] = r.winfo_x()
        self.config["window"]["y"] = r.winfo_y()
        self.save_config()

    # ─────────────────── 右键菜单 ───────────────────

    def _on_right_click(self, event):
        menu = tk.Menu(self.root, tearoff=0,
                       bg="#0a1a0a", fg=TEXT_GREEN,
                       activebackground="#003300", activeforeground=TEXT_GREEN,
                       font=("Consolas", 9))

        menu.add_command(label="> 刷新余额", command=self._manual_refresh)
        menu.add_separator()
        menu.add_command(label="> 管理 API Keys…", command=self.show_api_key_dialog)
        menu.add_command(label="> 重置 Token 统计", command=self._reset_token_stats)
        menu.add_separator()

        sub = tk.Menu(menu, tearoff=0,
                      bg="#0a1a0a", fg=TEXT_GREEN,
                      activebackground="#003300", activeforeground=TEXT_GREEN,
                      font=("Consolas", 9))
        current = self.config["refresh_interval_seconds"]
        for sec in (15, 30, 60, 120):
            label = f"{sec}s" + (" ✓" if sec == current else "")
            sub.add_command(label=label,
                            command=lambda s=sec: self._set_refresh_interval(s))
        menu.add_cascade(label="> 刷新间隔", menu=sub)

        menu.add_separator()
        menu.add_command(label=f"> 关于 v{VERSION}", command=self._show_about)
        menu.add_command(label="> 退出", command=self.quit)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ─────────────────── 动画 ───────────────────

    def _animate_expand(self):
        self.animating = True
        self._cancel_all_anim()
        r = self.root
        sx, sy = r.winfo_width(), r.winfo_height()
        self._scanline_offset = 0.0
        self._animate_to(sx, sy, EXPANDED_W, EXPANDED_H,
                         EXPAND_FRAMES, EXPAND_INTERVAL,
                         on_done=self._on_expand_done)

    def _animate_collapse(self):
        self.animating = True
        self._cancel_all_anim()
        r = self.root
        sx, sy = r.winfo_width(), r.winfo_height()
        self._animate_to(sx, sy, COLLAPSED_W, COLLAPSED_H,
                         COLLAPSE_FRAMES, COLLAPSE_INTERVAL,
                         on_done=self._on_collapse_done)

    def _animate_to(self, from_w, from_h, to_w, to_h, frames, interval, on_done):
        frame = [0]

        def step():
            frame[0] += 1
            if frame[0] > frames:
                self.cur_w = to_w
                self.cur_h = to_h
                self.animating = False
                self._draw()
                if on_done:
                    on_done()
                return
            t = frame[0] / frames
            t = 1 - (1 - t) ** 3
            w = int(lerp(from_w, to_w, t))
            h = int(lerp(from_h, to_h, t))
            self.cur_w = w
            self.cur_h = h
            self._set_geometry(w, h)
            self._draw()
            # 动画中更新扫描线
            self._scanline_offset = (self._scanline_offset + 0.15) % 1.0
            aid = self.root.after(interval, step)
            self.anim_after_ids.append(aid)

        if to_w > from_w:
            self.root.attributes("-alpha", 0.92)
        else:
            self.root.attributes("-alpha", 0.72)
        aid = self.root.after(0, step)
        self.anim_after_ids.append(aid)

    def _on_expand_done(self):
        self.is_expanded = True
        self.root.attributes("-alpha", 0.92)
        self._draw()

    def _on_collapse_done(self):
        self.is_expanded = False
        self.root.attributes("-alpha", 0.72)
        self._draw()

    def _cancel_all_anim(self):
        for aid in self.anim_after_ids:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self.anim_after_ids.clear()

    def _blink_tick(self):
        self._blink_phase = not self._blink_phase
        if self.is_expanded or self.animating:
            self._scanline_offset = (self._scanline_offset + 0.03) % 1.0
            self._draw()
        self.root.after(800, self._blink_tick)

    # ═══════════════════════════════════════════════
    #  绘制 — 黑客终端风格
    # ═══════════════════════════════════════════════

    def _draw(self):
        c = self.canvas
        c.delete("all")
        c.configure(width=self.cur_w, height=self.cur_h)
        w, h = self.cur_w, self.cur_h
        pad = 12
        r = 4  # 直角小圆角，更像终端窗口

        # 背景
        self._rect(c, 0, 0, w, h, r, fill=BG_TERMINAL, outline=BORDER_GREEN, width=1)

        # 扫描线效果（展开态）
        if (self.is_expanded or self.animating) and self.cur_w > 200:
            sy = int(self._scanline_offset * h)
            c.create_line(0, sy, w, sy, fill="#00ff41", width=1, stipple="gray25",
                          state="hidden" if self.animating else "normal")

        if not self.is_expanded and not self.animating and self.cur_w < 220:
            self._draw_collapsed(c, w, h, pad)
        elif self.is_expanded or self.animating:
            progress = (self.cur_w - COLLAPSED_W) / (EXPANDED_W - COLLAPSED_W) if EXPANDED_W > COLLAPSED_W else 1
            progress = clamp(progress, 0, 1)
            if progress > 0.25:
                self._draw_expanded(c, w, h, pad, r, progress)
            else:
                self._draw_collapsed(c, max(w, COLLAPSED_W), h, pad)

    def _draw_collapsed(self, c, w, h, pad):
        r = 4
        self._rect(c, 1, 1, w - 1, h - 1, r, fill=BG_TERMINAL, outline="")
        # 品牌标识 — 终端风
        c.create_text(pad + 2, h / 2, text="root@DeepSeek:~$",
                      anchor="w", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 9))
        # 总余额
        total = self._total_balance
        if self.balances and total > 0:
            bal_text = f"¥{total:.2f}"
        elif self.error_count >= 3:
            bal_text = "[ ERR ]"
        else:
            bal_text = "[ ... ]"
        c.create_text(w - pad, h / 2, text=bal_text,
                      anchor="e", fill=TEXT_GREEN,
                      font=("Consolas", 11, "bold"))

    def _draw_expanded(self, c, w, h, pad, r, p=1.0):
        p = clamp(p, 0, 1)

        # ── 标题栏 ──
        y = pad + 4
        c.create_text(pad, y, text="┌─ DEEPSEEK MONITOR v2.0 ────────────┐",
                      anchor="nw", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 9))
        y += 16

        # 时间戳
        now = datetime.datetime.now().strftime("%H:%M:%S")
        c.create_text(pad + 4, y, text=f"[{now}] 连接已建立",
                      anchor="w", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 8))
        y += 18

        # ── 总余额大字 ──
        total = self._total_balance
        c.create_text(w / 2, y, text=f"> ¥ {total:,.2f}",
                      anchor="center", fill=TEXT_GREEN,
                      font=("Consolas", 24, "bold"))
        y += 26
        c.create_text(w / 2, y, text="TOTAL BALANCE",
                      anchor="center", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 8))
        y += 24

        # ── 分割线 ──
        c.create_line(pad, y, w - pad, y, fill=BORDER_GREEN, dash=(4, 4))
        y += 14

        # ── 各 Key 余额 ──
        c.create_text(pad, y, text="API_KEYS:", anchor="w",
                      fill=TEXT_GREEN, font=("Consolas", 9, "bold"))
        y += 18

        for entry in self.balances:
            label = entry.get("label", "未知")
            bal = entry.get("balance", 0.0)
            # 截断 label 以防太长
            label_short = label[:18] + "…" if len(label) > 18 else label
            # 行号
            status = "✓" if not entry.get("error") else "✗"
            status_color = TEXT_GREEN if not entry.get("error") else TEXT_RED
            c.create_text(pad + 4, y, text=status, anchor="w",
                          fill=status_color, font=("Consolas", 9))
            c.create_text(pad + 20, y, text=label_short, anchor="w",
                          fill=TEXT_WHITE, font=("Consolas", 9))
            bal_str = f"¥{bal:.2f}" if not entry.get("error") else "ERROR"
            bal_color = TEXT_AMBER if bal > 0 else TEXT_GREEN_DIM
            if entry.get("error"):
                bal_color = TEXT_RED
            c.create_text(w - pad, y, text=bal_str, anchor="e",
                          fill=bal_color, font=("Consolas", 9, "bold"))
            y += 18
            # 错误信息
            if entry.get("error") and entry.get("error") != "unauthorized":
                c.create_text(pad + 20, y, text=f"  ↳ {entry['error']}", anchor="w",
                              fill=TEXT_RED, font=("Consolas", 7))
                y += 14

        y += 2
        # 分割线
        c.create_line(pad, y, w - pad, y, fill=BORDER_GREEN, dash=(4, 4))
        y += 12

        # ── Token 统计 ──
        today = datetime.date.today().isoformat()
        usage = self.config.get("token_usage_daily", {}).get(today, {})
        total_t = usage.get("total_tokens", 0)
        prompt_t = usage.get("prompt_tokens", 0)
        comp_t = usage.get("completion_tokens", 0)
        cost = usage.get("estimated_cost_cny", 0)

        c.create_text(pad, y, text="TOKEN_USAGE:", anchor="w",
                      fill=TEXT_GREEN, font=("Consolas", 9, "bold"))
        y += 17
        c.create_text(pad + 4, y, text=f"prompt:    {prompt_t:>10,}", anchor="w",
                      fill=TEXT_WHITE, font=("Consolas", 9))
        y += 16
        c.create_text(pad + 4, y, text=f"completion:{comp_t:>10,}", anchor="w",
                      fill=TEXT_WHITE, font=("Consolas", 9))
        y += 16
        c.create_text(pad + 4, y, text=f"total:     {total_t:>10,}", anchor="w",
                      fill=TEXT_WHITE, font=("Consolas", 9))
        y += 16
        c.create_text(pad + 4, y, text=f"est_cost:  ¥{cost:>10.4f}", anchor="w",
                      fill=TEXT_AMBER, font=("Consolas", 9))
        y += 22

        # ── 底部状态栏 ──
        c.create_line(pad, y, w - pad, y, fill=BORDER_GREEN, dash=(4, 4))
        y += 10

        # 刷新时间
        if self.last_refresh:
            ago = int((datetime.datetime.now() - self.last_refresh).total_seconds())
            ago_str = f"{ago}s ago" if ago < 120 else f"{ago // 60}m ago"
        else:
            ago_str = "pending"
        c.create_text(pad, y, text=f"last_sync: {ago_str}", anchor="w",
                      fill=TEXT_GREEN_DIM, font=("Consolas", 8))

        # 在线状态指示
        if self.error_count == 0:
            status_info = "ONLINE"
            sc = TEXT_GREEN
        elif self.error_count < 3:
            status_info = "RETRY"
            sc = TEXT_AMBER
        else:
            status_info = "OFFLINE"
            sc = TEXT_RED
        c.create_text(w - pad - 42, y, text=status_info, anchor="w",
                      fill=sc, font=("Consolas", 8, "bold"))

        # 刷新按钮
        bx1, by1 = w - 38, y - 7
        bx2, by2 = w - pad, y + 7
        self._rect(c, bx1, by1, bx2, by2, 2,
                   fill=SURFACE_TERMINAL, outline=BORDER_GREEN)
        c.create_text((bx1 + bx2) / 2, (by1 + by2) / 2,
                      text="SYNC", fill=TEXT_GREEN,
                      font=("Consolas", 7, "bold"))
        self._refresh_btn_coords = (bx1, by1, bx2, by2)

        y += 16
        # 底部边框
        c.create_text(pad, y, text="└──────────────────────────────────┘",
                      anchor="nw", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 8))
        y += 14
        c.create_text(w / 2, y, text="[右键菜单] [双击配置] [拖拽移动] [ESC退出]",
                      anchor="center", fill=TEXT_GREEN_DIM,
                      font=("Consolas", 7))

    def _rect(self, c, x1, y1, x2, y2, radius, **kwargs):
        """轻量圆角矩形 — 不用 smooth，纯多边形近似"""
        if radius <= 0 or (x2 - x1) < radius * 2 or (y2 - y1) < radius * 2:
            return c.create_rectangle(x1, y1, x2, y2, **kwargs)
        points = []
        s = 4  # 每角采样数
        for cx, cy, sa in [
            (x1 + radius, y1 + radius, math.pi),
            (x2 - radius, y1 + radius, math.pi * 1.5),
            (x2 - radius, y2 - radius, 0),
            (x1 + radius, y2 - radius, math.pi / 2),
        ]:
            for i in range(s + 1):
                a = sa + (i / s) * (math.pi / 2)
                points.extend([cx + radius * math.cos(a), cy + radius * math.sin(a)])
        return c.create_polygon(points, fill=kwargs.get("fill"),
                                outline=kwargs.get("outline"),
                                width=kwargs.get("width", 0),
                                smooth=False)

    def _fade(self, hex_color, p):
        if p >= 1 or self.animating:
            return hex_color
        try:
            r, g, b = hex_to_rgb(hex_color)
            nr = int(lerp(self._bg_rgb[0], r, p))
            ng = int(lerp(self._bg_rgb[1], g, p))
            nb = int(lerp(self._bg_rgb[2], b, p))
            return f"#{nr:02x}{ng:02x}{nb:02x}"
        except Exception:
            return hex_color

    # ─────────────────── 数据获取 ───────────────────

    def _schedule_refresh(self):
        self._fetch_now()
        interval = self.config["refresh_interval_seconds"] * 1000
        self._next_refresh_id = self.root.after(interval, self._schedule_refresh)

    def _manual_refresh(self):
        self._fetch_now()

    def _fetch_now(self):
        api_keys = self.config.get("api_keys", [])
        if not api_keys:
            # 兼容旧格式
            old_key = self.config.get("api_key")
            if old_key:
                api_keys = [{"label": "默认", "key": old_key}]
            else:
                return
        if self.fetch_thread and self.fetch_thread.is_alive():
            return
        self.fetch_thread = threading.Thread(
            target=self._do_fetch_all, args=(api_keys,), daemon=True
        )
        self.fetch_thread.start()

    def _do_fetch_all(self, api_keys):
        """后台线程：并发查询所有 Key 的余额"""
        results = []
        for entry in api_keys:
            key = entry.get("key", "")
            label = entry.get("label", key[:8])
            if not key:
                results.append({"label": label, "balance": 0, "error": "no_key"})
                continue
            try:
                resp = requests.get(
                    BALANCE_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    total = float(data["balance_infos"][0].get("total_balance", "0"))
                    results.append({"label": label, "balance": total, "error": None,
                                    "available": data.get("is_available", True)})
                elif resp.status_code == 401:
                    results.append({"label": label, "balance": 0, "error": "unauthorized"})
                else:
                    results.append({"label": label, "balance": 0, "error": f"HTTP {resp.status_code}"})
            except requests.exceptions.Timeout:
                results.append({"label": label, "balance": 0, "error": "timeout"})
            except requests.exceptions.ConnectionError:
                results.append({"label": label, "balance": 0, "error": "connection"})
            except Exception as e:
                results.append({"label": label, "balance": 0, "error": str(e)[:30]})
        self.data_queue.put({"ok": True, "results": results, "time": datetime.datetime.now()})

    def _poll_queue(self):
        try:
            while True:
                msg = self.data_queue.get_nowait()
                self._handle_data(msg)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _handle_data(self, msg):
        if msg["ok"]:
            self.balances = msg["results"]
            self.last_refresh = msg["time"]
            self.error_count = 0
            # 计算总余额
            self._total_balance = sum(
                e.get("balance", 0) for e in self.balances if not e.get("error")
            )
        else:
            self.error_count += 1
        self._draw()

    # ─────────────────── API Key 管理 ───────────────────

    def show_api_key_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("API Key Management")
        dlg.configure(bg=BG_TERMINAL)
        dlg.resizable(True, True)

        dw, dh = 520, 380
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{dw}x{dh}+{(sw - dw) // 2}+{(sh - dh) // 2}")
        dlg.attributes("-topmost", True)

        pad_x = 16
        py = 12

        # 标题
        tk.Label(dlg, text="┌─ API KEY MANAGEMENT ──────────────┐",
                 font=("Consolas", 11, "bold"), fg=TEXT_GREEN, bg=BG_TERMINAL
                 ).pack(anchor="w", padx=pad_x, pady=(py, 2))

        tk.Label(dlg, text="管理你的 DeepSeek API Keys，支持多Key监控",
                 font=("Consolas", 8), fg=TEXT_GREEN_DIM, bg=BG_TERMINAL
                 ).pack(anchor="w", padx=pad_x + 8)

        # 列标题
        hdr = tk.Frame(dlg, bg=BG_TERMINAL)
        hdr.pack(fill="x", padx=pad_x, pady=(10, 0))
        tk.Label(hdr, text="LABEL", font=("Consolas", 8, "bold"),
                 fg=TEXT_GREEN_DIM, bg=BG_TERMINAL, width=14, anchor="w"
                 ).pack(side="left")
        tk.Label(hdr, text="API KEY", font=("Consolas", 8, "bold"),
                 fg=TEXT_GREEN_DIM, bg=BG_TERMINAL, width=36, anchor="w"
                 ).pack(side="left", padx=(8, 0))

        # Key 列表区域
        list_frame = tk.Frame(dlg, bg=BG_TERMINAL)
        list_frame.pack(fill="both", expand=True, padx=pad_x, pady=(4, 8))
        canvas = tk.Canvas(list_frame, bg=BG_TERMINAL, highlightthickness=0, bd=0, height=160)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable = tk.Frame(canvas, bg=BG_TERMINAL)
        scrollable.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        entries = []  # [(label_var, key_var, label_entry, key_entry)]

        def add_row(label_val="", key_val="", focus=False):
            row = tk.Frame(scrollable, bg=BG_TERMINAL)
            row.pack(fill="x", pady=2)
            lv = tk.StringVar(value=label_val)
            kv = tk.StringVar(value=key_val)
            le = tk.Entry(row, textvariable=lv, width=14, font=("Consolas", 9),
                          bg="#0f1a0f", fg=TEXT_GREEN, insertbackground=TEXT_GREEN,
                          relief="flat", bd=1, highlightthickness=1,
                          highlightbackground=BORDER_GREEN, highlightcolor=TEXT_GREEN)
            le.pack(side="left")
            ke = tk.Entry(row, textvariable=kv, width=38, font=("Consolas", 9),
                          bg="#0f1a0f", fg=TEXT_AMBER, insertbackground=TEXT_AMBER,
                          relief="flat", bd=1, highlightthickness=1,
                          highlightbackground=BORDER_GREEN, highlightcolor=TEXT_GREEN,
                          show="•")
            ke.pack(side="left", padx=(8, 0))
            btn = tk.Button(row, text="✕", font=("Consolas", 9, "bold"),
                            bg=BG_TERMINAL, fg=TEXT_RED, relief="flat", bd=0,
                            activebackground="#330000", activeforeground=TEXT_RED,
                            cursor="hand2",
                            command=lambda r=row, tup=(lv, kv): self._del_row(r, tup, entries))
            btn.pack(side="left", padx=(4, 0))
            entries.append((lv, kv, le, ke, row, btn))
            if focus:
                le.focus_set()

        for entry in self.config.get("api_keys", []):
            add_row(entry.get("label", ""), entry.get("key", ""))
        if not entries:
            add_row()

        # 按钮行
        btn_row = tk.Frame(dlg, bg=BG_TERMINAL)
        btn_row.pack(fill="x", padx=pad_x, pady=(0, 4))

        def add_new():
            add_row(focus=True)
            canvas.yview_moveto(1.0)

        tk.Button(btn_row, text="+ 添加 Key", command=add_new,
                  font=("Consolas", 9), bg="#0f1a0f", fg=TEXT_GREEN,
                  relief="flat", bd=1, padx=10, cursor="hand2",
                  activebackground="#003300", activeforeground=TEXT_GREEN,
                  highlightbackground=BORDER_GREEN, highlightthickness=1
                  ).pack(side="left")

        tk.Label(btn_row, text="提示：点击 ✕ 删除该行",
                 font=("Consolas", 8), fg=TEXT_GREEN_DIM, bg=BG_TERMINAL
                 ).pack(side="left", padx=12)

        # 错误标签
        err_label = tk.Label(dlg, text="", font=("Consolas", 8),
                             fg=TEXT_RED, bg=BG_TERMINAL)
        err_label.pack(padx=pad_x, pady=(0, 6))

        # 底部按钮
        bottom = tk.Frame(dlg, bg=BG_TERMINAL)
        bottom.pack(fill="x", padx=pad_x, pady=(0, 12))

        def do_save():
            data = []
            has_valid = False
            for lv, kv, *_ in entries:
                label = lv.get().strip()
                key = kv.get().strip()
                if label or key:
                    if not label:
                        err_label.configure(text="[!] 每个 Key 都需要一个标签名")
                        return
                    if not key:
                        err_label.configure(text=f"[!] '{label}' 缺少 API Key 值")
                        return
                    if not key.startswith("sk-"):
                        err_label.configure(text=f"[!] '{label}' 格式错误（应以 sk- 开头）")
                        return
                    data.append({"label": label, "key": key})
                    has_valid = True
            if not has_valid:
                err_label.configure(text="[!] 请至少添加一个有效的 API Key")
                return
            self.config["api_keys"] = data
            self.save_config()
            self._fetch_now()
            dlg.destroy()

        tk.Button(bottom, text="CANCEL", command=dlg.destroy,
                  font=("Consolas", 10), bg=BG_TERMINAL, fg=TEXT_GREEN_DIM,
                  relief="flat", bd=1, padx=14, pady=2, cursor="hand2",
                  activebackground="#0f1a0f", activeforeground=TEXT_GREEN,
                  highlightbackground=BORDER_GREEN, highlightthickness=1
                  ).pack(side="left", padx=(0, 8))

        tk.Button(bottom, text="SAVE & APPLY", command=do_save,
                  font=("Consolas", 10, "bold"), bg="#0a2a0a", fg=TEXT_GREEN,
                  relief="flat", bd=1, padx=14, pady=2, cursor="hand2",
                  activebackground="#003300", activeforeground=TEXT_GREEN,
                  highlightbackground=TEXT_GREEN, highlightthickness=1
                  ).pack(side="left")

        dlg.bind("<Return>", lambda e: do_save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.grab_set()
        dlg.wait_window()

    def _del_row(self, row_widget, tup, entries_list):
        row_widget.destroy()
        new_list = []
        for entry in entries_list:
            if entry[0] is tup[0]:  # same StringVar
                continue
            new_list.append(entry)
        entries_list.clear()
        entries_list.extend(new_list)

    # ─────────────────── 菜单回调 ───────────────────

    def _set_refresh_interval(self, sec):
        self.config["refresh_interval_seconds"] = sec
        self.save_config()
        if hasattr(self, "_next_refresh_id"):
            self.root.after_cancel(self._next_refresh_id)
        self._schedule_refresh()

    def _reset_token_stats(self):
        self.config["token_usage_daily"] = {}
        self.save_config()
        self._draw()

    def _show_about(self):
        import tkinter.messagebox as mb
        mb.showinfo(
            "About",
            f"DeepSeek Monitor v{VERSION}\n\n"
            "黑客终端风格 · 余额监控悬浮窗\n"
            "支持多 API Key 监控\n"
            "鼠标悬停展开 · 移开折叠\n\n"
            f"配置: {CONFIG_DIR}"
        )

    def quit(self):
        self.config["window"]["x"] = self.root.winfo_x()
        self.config["window"]["y"] = self.root.winfo_y()
        self.save_config()
        self.root.destroy()
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# ── 入口 ─────────────────────────────────────────────

def main():
    app = DeepSeekMonitor()
    app.run()


if __name__ == "__main__":
    main()
