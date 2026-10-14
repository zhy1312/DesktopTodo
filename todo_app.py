#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面待办 DesktopTodo
====================
常驻 Windows 桌面的轻量待办清单工具。

功能概要
--------
* 窗口始终置顶在所有窗口前方（标题栏可切换置顶 / 取消置顶）
* 窗口拖到屏幕边缘时自动收起为一个小边条；鼠标移到边条上自动展开，移开后再次收起
* 按紧急程度分为三个区域：当天要做 / 3天内要做 / 大于7天后要做
* 每条待办左侧显示内容，右侧显示剩余天数；跨天或跨区域时自动刷新分组
* 右上角加号新建待办（内容 + 目标日期），右键可修改日期 / 编辑内容 / 删除
* 数据本地保存于 %APPDATA%\\DesktopTodo，重启不丢失

运行方式
--------
源码运行:  python todo_app.py
打包运行:  DesktopTodo.exe
"""

import ctypes
import datetime as dt
import json
import os
import sys
import uuid

# 高 DPI 感知，避免缩放屏幕下窗口尺寸异常（需在创建主窗口前调用）
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import tkinter as tk
from tkinter import ttk

try:
    import winreg
except Exception:
    winreg = None

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
APP_NAME = "桌面待办"

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DesktopTodo")
DATA_FILE = os.path.join(DATA_DIR, "todos.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# 配色（扁平化：纯色平铺，无阴影/渐变/立体效果；清新明快）
BG = "#F5F7FA"          # 页面底色（清新浅灰蓝）
CARD = "#FFFFFF"        # 卡片表面
BORDER = "#E3E9F2"      # 窗口描边（1px 极浅）
TEXT = "#262B33"        # 主文字（高对比深灰）
TEXT_SUB = "#8B95A3"    # 次要文字
HOVER = "#EEF4FC"       # 行悬停（浅蓝）
BRAND = "#4C8DFF"       # 品牌蓝
BRAND_DARK = "#3A78EF"  # 品牌蓝悬停加深（纯色）
BRAND_TINT = "#EAF2FF"  # 品牌浅底
BTN_BG = "#EDF1F7"      # 中性按钮底
BTN_HOVER = "#E4EAF3"

# 三个区域: (名称, 强调色, 浅色底)
ZONE_DEFS = [
    ("当天要做", "#E5484D", "#FDECEC"),
    ("3天内要做", "#E07A1F", "#FEF1E2"),
    ("大于7天后要做", "#0D9488", "#E0F4F2"),
]

EDGE_MARGIN = 14        # 距屏幕边缘多少像素内触发吸附收起
STRIP = 8               # 收起后留在屏幕内的边条宽度（与左右品牌色边条同宽）
ANIM_STEP_MS = 10       # 展开/收起动画步进间隔
ANIM_STEP_PX = 28       # 每步移动像素
HOVER_POLL_MS = 100     # 鼠标位置轮询间隔
REFRESH_MS = 20000      # 跨天自动刷新检查间隔
WIN_MIN_W, WIN_MIN_H = 300, 420
WIN_DEF_W, WIN_DEF_H = 340, 560

WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 字体：统一使用更清爽的 YaHei UI，整体加大字号提升可读性
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_SMALL_BOLD = ("Microsoft YaHei UI", 9, "bold")
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_ZONE = ("Microsoft YaHei UI", 11, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 12, "bold")


# --------------------------------------------------------------------------
# 纯逻辑 helpers
# --------------------------------------------------------------------------
def screen_bounds(root):
    """返回虚拟桌面边界 (x, y, w, h)，支持多显示器；失败时回退主屏。"""
    try:
        u32 = ctypes.windll.user32
        vx = u32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = u32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = u32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = u32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if vw > 0 and vh > 0:
            return vx, vy, vw, vh
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def monitor_work_area(root):
    """窗口所在显示器的工作区 (x, y, w, h)，排除任务栏；失败回退虚拟桌面。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if hmon:
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                rc = mi.rcWork
                return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top
    except Exception:
        pass
    return screen_bounds(root)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


try:
    _u32 = ctypes.windll.user32
    _u32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_uint]
    _u32.MonitorFromPoint.restype = ctypes.c_void_p
except Exception:
    pass


def monitor_at_point(px, py, nearest=False):
    """包含该点的显示器工作区 (x, y, w, h)。

    nearest=False 时，点不在任何显示器上返回 None，
    用于识别多显示器之间没有屏幕的"死区"。
    """
    try:
        u32 = ctypes.windll.user32
        hmon = u32.MonitorFromPoint(_POINT(int(px), int(py)),
                                    2 if nearest else 0)
        if hmon:
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                rc = mi.rcWork
                return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top
    except Exception:
        pass
    return None


def today_str():
    return dt.date.today().isoformat()


def days_left(date_str):
    """目标日期相对今天还剩几天（0=今天，负数=已逾期）。"""
    return (dt.date.fromisoformat(date_str) - dt.date.today()).days


def zone_index(days):
    """剩余天数 -> 区域索引。0=当天, 1=3天内, 2=大于7天。"""
    if days <= 0:
        return 0
    if days <= 7:
        return 1
    return 2


def fmt_days(days):
    if days == 0:
        return "今天"
    if days < 0:
        return "逾期%d天" % -days
    return "%d天" % days


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    """原子写入，避免写入中途断电/崩溃导致数据损坏。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_todos():
    data = load_json(DATA_FILE, {})
    todos = data.get("todos", []) if isinstance(data, dict) else []
    out = []
    for t in todos:
        if not isinstance(t, dict):
            continue
        tid, text, date = t.get("id"), t.get("text"), t.get("date")
        if not tid or not text or not date:
            continue
        try:
            dt.date.fromisoformat(str(date))
        except Exception:
            continue
        out.append({
            "id": str(tid),
            "text": str(text)[:200],
            "date": str(date),
            "created": str(t.get("created", "")),
        })
    return out


def save_todos(todos):
    return save_json(DATA_FILE, {"version": 1, "todos": todos})


def group_todos(todos):
    """待办列表 -> 三个区域分组；组内按（剩余天数, 创建时间, 内容）升序。"""
    groups = [[], [], []]
    for t in todos:
        try:
            d = days_left(t["date"])
        except Exception:
            continue
        groups[zone_index(d)].append((d, t))
    for g in groups:
        g.sort(key=lambda x: (x[0], x[1].get("created", ""), x[1]["text"]))
    return groups


def flat_button(parent, text, cmd, bg=BTN_BG, fg=TEXT, hover_bg=BTN_HOVER,
                font=FONT_SMALL, padx=9, pady=4):
    """扁平按钮（Label 实现）：纯色底、无描边无阴影，悬停纯色加深。"""
    b = tk.Label(parent, text=text, bg=bg, fg=fg, font=font,
                 padx=padx, pady=pady, cursor="hand2")
    b._base = {"bg": bg, "hover": hover_bg}
    b.bind("<Button-1>", lambda e: cmd())
    b.bind("<Enter>", lambda e: b.configure(bg=b._base["hover"]))
    b.bind("<Leave>", lambda e: b.configure(bg=b._base["bg"]))
    return b


def bind_recursive(widget, seq, func, skip=None):
    """给组件及其所有子组件绑定事件（skip 中的组件及其子树除外）。"""
    if skip is None:
        skip = set()
    if widget in skip:
        return
    widget.bind(seq, func)
    for child in widget.winfo_children():
        bind_recursive(child, seq, func, skip)


# --------------------------------------------------------------------------
# 新建 / 编辑 对话框
# --------------------------------------------------------------------------
class TodoDialog(tk.Toplevel):
    """新建或编辑待办。with_text=False 时仅修改日期。"""

    def __init__(self, app, title, text="", date_str=None, with_text=True):
        super().__init__(app.root)
        self.app = app
        self.with_text = with_text
        self.result = None
        self.title(title)
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.transient(app.root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())

        if with_text:
            tk.Label(self, text="待办内容", bg=BG, fg=TEXT_SUB, font=FONT_SMALL,
                     anchor="w").pack(fill="x", padx=14, pady=(14, 2))
            self.text_var = tk.StringVar(value=text or "")
            entry = tk.Entry(self, textvariable=self.text_var, font=FONT, relief="flat",
                             highlightthickness=1, highlightcolor=BRAND,
                             highlightbackground=BORDER, bg=CARD)
            entry.pack(fill="x", padx=14, pady=(0, 8))
            entry.focus_set()
            entry.select_range(0, "end")
            self.bind("<Return>", lambda e: self._ok())

        d = dt.date.today()
        if date_str:
            try:
                d = dt.date.fromisoformat(date_str)
            except Exception:
                pass
        tk.Label(self, text="目标日期", bg=BG, fg=TEXT_SUB, font=FONT_SMALL,
                 anchor="w").pack(fill="x", padx=14, pady=(0, 2))
        drow = tk.Frame(self, bg=BG)
        drow.pack(fill="x", padx=14, pady=(0, 6))
        self.y_var = tk.IntVar(value=d.year)
        self.m_var = tk.IntVar(value=d.month)
        self.d_var = tk.IntVar(value=d.day)
        sb_cfg = dict(font=FONT, relief="flat", highlightthickness=1,
                      highlightcolor=BRAND, highlightbackground=BORDER,
                      bg=CARD)
        tk.Spinbox(drow, from_=2020, to=2035, textvariable=self.y_var,
                   width=5, **sb_cfg).pack(side="left")
        tk.Label(drow, text="年", bg=BG, fg=TEXT, font=FONT).pack(side="left", padx=(3, 10))
        tk.Spinbox(drow, from_=1, to=12, textvariable=self.m_var,
                   width=3, **sb_cfg).pack(side="left")
        tk.Label(drow, text="月", bg=BG, fg=TEXT, font=FONT).pack(side="left", padx=(3, 10))
        tk.Spinbox(drow, from_=1, to=31, textvariable=self.d_var,
                   width=3, **sb_cfg).pack(side="left")
        tk.Label(drow, text="日", bg=BG, fg=TEXT, font=FONT).pack(side="left", padx=3)

        qrow = tk.Frame(self, bg=BG)
        qrow.pack(fill="x", padx=14, pady=(0, 10))
        for label, delta in (("今天", 0), ("明天", 1), ("3天后", 3),
                             ("7天后", 7), ("30天后", 30)):
            flat_button(qrow, label, lambda dl=delta: self._set_quick(dl),
                        padx=6, pady=2, font=FONT_SMALL).pack(side="left", padx=(0, 6))

        brow = tk.Frame(self, bg=BG)
        brow.pack(fill="x", padx=14, pady=(0, 14))
        flat_button(brow, "取 消", self._cancel, padx=14, pady=4).pack(side="right")
        flat_button(brow, "确 定", self._ok, bg=BRAND, fg="#FFFFFF",
                    hover_bg=BRAND_DARK, padx=14, pady=4,
                    font=FONT_BOLD).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        self._center_on_parent()

    def _set_quick(self, delta):
        d = dt.date.today() + dt.timedelta(days=delta)
        self.y_var.set(d.year)
        self.m_var.set(d.month)
        self.d_var.set(d.day)

    def _center_on_parent(self):
        p = self.app.root
        px, py = p.winfo_x(), p.winfo_y()
        pw, ph = p.winfo_width(), p.winfo_height()
        vx, vy, vw, vh = screen_bounds(p)
        w, h = self.winfo_width(), self.winfo_height()
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        x = max(vx, min(x, vx + vw - w))
        y = max(vy, min(y, vy + vh - h))
        self.geometry("+%d+%d" % (x, y))

    def _ok(self):
        if self.with_text:
            txt = self.text_var.get().strip()
            if not txt:
                from tkinter import messagebox
                messagebox.showwarning("提示", "请输入待办内容", parent=self)
                return
        else:
            txt = None
        try:
            d = dt.date(self.y_var.get(), self.m_var.get(), self.d_var.get())
        except ValueError:
            from tkinter import messagebox
            messagebox.showwarning("提示", "日期无效，请检查年月日", parent=self)
            return
        self.result = (txt, d.isoformat())
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# --------------------------------------------------------------------------
# 主应用
# --------------------------------------------------------------------------
class TodoApp:
    def __init__(self, root):
        self.root = root
        self.todos = load_todos()
        s = load_json(SETTINGS_FILE, {})
        self.pinned = bool(s.get("pinned", True))
        self.auto_start = self._autostart_enabled()

        # 边缘吸附状态
        self.collapsed_edge = None      # 当前收起边缘: left/right/top/None
        self.last_edge = None           # 最近一次收起边缘
        self.saved_geo = None           # 收起前的窗口位置（用于展开还原）
        self.saved_mon = None           # 收起时所在显示器工作区（展开按原屏还原）
        self._pos = None                # 窗口逻辑位置（唯一事实源，避免 winfo 读数滞后）
        self.expanded_from_edge = False # 是否因悬停边条而展开
        self.animating = False
        self._anim_id = None
        self._save_geo_id = None
        self._render_id = None
        self._drag = None
        self._rz = None
        self.dialog_open = False
        self.last_date = today_str()

        self._build()
        self._set_icon()

    # ---------------- 窗口骨架 ----------------
    def _build(self):
        r = self.root
        r.title(APP_NAME)
        r.overrideredirect(True)
        r.wm_attributes("-topmost", self.pinned)
        r.configure(bg=BG, highlightthickness=1,
                    highlightbackground=BORDER, highlightcolor=BORDER)
        r.minsize(WIN_MIN_W, WIN_MIN_H)

        # 恢复上次位置/大小；越界时回退到屏幕右侧居中
        vx, vy, vw, vh = screen_bounds(r)
        s = load_json(SETTINGS_FILE, {})
        gx = gy = gw = gh = None
        geo = s.get("geometry")
        if isinstance(geo, list) and len(geo) == 4:
            try:
                gx, gy, gw, gh = [int(v) for v in geo]
            except Exception:
                gx = None
        if gx is None:
            gw, gh = WIN_DEF_W, WIN_DEF_H
            gx, gy = vx + vw - gw - 40, vy + max(0, (vh - gh) // 2)
        gx = max(vx, min(gx, vx + vw - 60))
        gy = max(vy, min(gy, vy + vh - 60))
        r.geometry("%dx%d+%d+%d" % (gw, gh, gx, gy))
        # 夹紧到窗口所在显示器的工作区（避免悬垂到屏幕外/压住任务栏），
        # 并把最终位置写入逻辑坐标 _pos
        try:
            r.update_idletasks()
            mx, my, mw, mh = monitor_work_area(r)
            gx2 = max(mx, min(gx, mx + mw - gw))
            gy2 = max(my, min(gy, my + mh - gh))
            self._pos = [gx2, gy2]
            if (gx2, gy2) != (gx, gy):
                r.geometry("%dx%d+%d+%d" % (gw, gh, gx2, gy2))
        except Exception:
            self._pos = [gx, gy]
        if self._pos is None:
            self._pos = [r.winfo_x(), r.winfo_y()]

        # ---- 标题栏（可拖动，扁平） ----
        title = tk.Frame(r, bg=BG, height=44)
        title.pack(fill="x", side="top")
        tk.Frame(title, bg=BRAND, width=12, height=12).pack(
            side="left", padx=(14, 8), pady=16)
        tk.Label(title, text=APP_NAME, bg=BG, fg=TEXT,
                 font=FONT_TITLE).pack(side="left")
        self.date_lbl = tk.Label(title, text="", bg=BG, fg=TEXT_SUB,
                                 font=FONT_SMALL)
        self.date_lbl.pack(side="left", padx=(10, 0))

        btns = tk.Frame(title, bg=BG)
        btns.pack(side="right", padx=(0, 10))
        self.pin_btn = flat_button(btns, "置顶", self.toggle_pin,
                                   padx=9, pady=3)
        self.pin_btn.pack(side="right", padx=(8, 0), pady=7)
        flat_button(btns, "＋", self.add_todo, bg=BRAND, fg="#FFFFFF",
                    hover_bg=BRAND_DARK, font=FONT_TITLE, padx=10,
                    pady=2).pack(side="right", pady=7)
        flat_button(btns, "×", self.on_close, font=FONT_TITLE, padx=10,
                    pady=2).pack(side="right", pady=7)

        bind_recursive(title, "<ButtonPress-1>", self._drag_start,
                       skip={btns})
        bind_recursive(title, "<B1-Motion>", self._drag_move, skip={btns})
        bind_recursive(title, "<ButtonRelease-1>", self._drag_stop, skip={btns})
        bind_recursive(title, "<Button-3>", self._title_menu, skip={btns})

        # ---- 内容区 ----
        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True, side="top")
        # 左右品牌色边条：收起后露出的就是这条彩色小边条
        tk.Frame(body, bg=BRAND, width=STRIP).pack(side="left", fill="y")
        tk.Frame(body, bg=BRAND, width=STRIP).pack(side="right", fill="y")

        mid = tk.Frame(body, bg=BG)
        mid.pack(side="left", fill="both", expand=True)
        # 扁平化滚动条
        try:
            style = ttk.Style(r)
            style.theme_use("clam")
            style.configure("TScrollbar", troughcolor=BG,
                            background="#C7D2E4", bordercolor=BG,
                            lightcolor="#C7D2E4", darkcolor="#C7D2E4",
                            arrowcolor="#7C8899", relief="flat",
                            arrowsize=11)
        except Exception:
            pass
        self.canvas = tk.Canvas(mid, bg=BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll = ttk.Scrollbar(mid, orient="vertical",
                                    command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG)
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: (self.canvas.configure(scrollregion=self.canvas.bbox("all")),
                       self._update_scrollbar()))
        self.cwin = self.canvas.create_window((0, 0), window=self.scroll_frame,
                                              anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_yscroll)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        r.bind_all("<MouseWheel>", self._on_wheel)

        # 右下角缩放手柄
        self.grip = tk.Frame(r, bg=BG, width=16, height=16, cursor="size_nw_se")
        self.grip.place(relx=1.0, rely=1.0, anchor="se")
        inner = tk.Frame(self.grip, bg="#C7D2E4", width=8, height=8)
        inner.place(relx=1.0, rely=1.0, anchor="se", x=-4, y=-4)
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)

        # 收起状态下：点边条展开，右键出菜单（bind_all 保证点到任何子组件都生效）
        r.bind_all("<ButtonPress-1>", self._root_press)
        r.bind_all("<Button-3>", self._root_menu)

    def _set_icon(self):
        try:
            if getattr(sys, "frozen", False):
                base = sys._MEIPASS
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(base, "icon.ico")
            if os.path.exists(p):
                self.root.iconbitmap(p)
        except Exception:
            pass

    # ---------------- 渲染 ----------------
    def render(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        groups = group_todos(self.todos)
        wrap = max(140, self.canvas.winfo_width() - 130)
        for zi, (name, color, tint) in enumerate(ZONE_DEFS):
            items = groups[zi]
            head = tk.Frame(self.scroll_frame, bg=BG)
            head.pack(fill="x", padx=14, pady=(16 if zi else 10, 6))
            tk.Frame(head, bg=color, width=9, height=9).pack(
                side="left", padx=(1, 8), pady=4)
            tk.Label(head, text=name, bg=BG, fg=TEXT,
                     font=FONT_ZONE).pack(side="left")
            tk.Label(head, text=str(len(items)), bg=tint, fg=color,
                     font=FONT_SMALL_BOLD, padx=7, pady=1).pack(
                side="left", padx=(8, 0))
            if not items:
                tk.Label(self.scroll_frame, text="暂无事项", bg=BG,
                         fg=TEXT_SUB, font=FONT_SMALL, anchor="w").pack(
                    fill="x", padx=16, pady=(0, 4))
                continue
            for d, t in items:
                self._make_row(t, d, color, tint, wrap)
        # 底部留白，避免最后一行贴边
        spacer = tk.Frame(self.scroll_frame, bg=BG, height=12)
        spacer.pack(fill="x")
        spacer.pack_propagate(False)
        self._update_scrollbar()

    def _make_row(self, todo, days, color, tint, wrap):
        # 扁平卡片：白色纯色底、无描边无阴影，左侧彩色强调条 + 天数徽章
        row = tk.Frame(self.scroll_frame, bg=CARD)
        row.pack(fill="x", padx=12, pady=3)
        bar = tk.Frame(row, bg=color, width=4)
        bar.pack(side="left", fill="y")
        row._accent = bar
        lbl = tk.Label(row, text=todo["text"], bg=CARD, fg=TEXT, font=FONT,
                       anchor="w", justify="left", wraplength=wrap)
        lbl.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=9)
        chip = tk.Label(row, text=fmt_days(days), bg=tint, fg=color,
                        font=FONT_SMALL_BOLD if days <= 0 else FONT_SMALL,
                        padx=8, pady=3)
        chip.pack(side="right", padx=(6, 10))
        row._chip = chip

        bind_recursive(row, "<Button-3>",
                       lambda e, t=todo: self._row_menu(e, t))
        bind_recursive(row, "<Double-Button-1>",
                       lambda e, t=todo: self.edit_text(t))
        row.bind("<Enter>", lambda e, row=row: self._row_hover(row, True))
        row.bind("<Leave>", lambda e, row=row: self._row_hover(row, False))

    def _row_hover(self, row, on):
        bg = HOVER if on else CARD
        row.configure(bg=bg)
        for w in row.winfo_children():
            if w is getattr(row, "_accent", None):
                continue  # 左侧彩色强调条保持原色
            if w is getattr(row, "_chip", None):
                continue  # 天数徽章保持浅色底
            try:
                w.configure(bg=bg)
            except Exception:
                pass

    def _on_canvas_configure(self, e):
        self.canvas.itemconfig(self.cwin, width=e.width)
        self._schedule_render()

    def _schedule_render(self):
        if self._render_id is not None:
            self.root.after_cancel(self._render_id)
        self._render_id = self.root.after(150, self.render)

    def _on_yscroll(self, first, last):
        self.scroll.set(first, last)
        self._update_scrollbar()

    def _update_scrollbar(self, *_):
        try:
            bbox = self.canvas.bbox("all")
            need = bbox and bbox[3] > self.canvas.winfo_height() + 2
            if need and not self.scroll.winfo_ismapped():
                self.scroll.pack(side="right", fill="y")
            elif not need and self.scroll.winfo_ismapped():
                self.scroll.pack_forget()
        except Exception:
            pass

    def _on_wheel(self, e):
        if self.dialog_open or self.collapsed_edge:
            return
        self.canvas.yview_scroll(int(-e.delta / 120), "units")

    # ---------------- 增删改 ----------------
    def add_todo(self):
        if self.collapsed_edge:
            self.expand()
        self._open_dialog(TodoDialog(self, "新建待办"),
                          lambda text, date: self._append(text, date))

    def _append(self, text, date):
        self.todos.append({
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "date": date,
            "created": dt.datetime.now().isoformat(timespec="seconds"),
        })
        self._commit()

    def edit_date(self, todo):
        self._open_dialog(TodoDialog(self, "修改日期", date_str=todo["date"],
                                     with_text=False),
                          lambda _, date: self._set_date(todo, date))

    def edit_text(self, todo):
        if self.collapsed_edge:
            self.expand()
        self._open_dialog(TodoDialog(self, "编辑内容", text=todo["text"],
                                     date_str=todo["date"]),
                          lambda text, _: self._set_text(todo, text))

    def _set_date(self, todo, date):
        todo["date"] = date
        self._commit()

    def _set_text(self, todo, text):
        todo["text"] = text
        self._commit()

    def delete_todo(self, todo):
        from tkinter import messagebox
        if not messagebox.askyesno("删除待办", "确定删除「%s」吗？" % todo["text"],
                                   parent=self.root):
            return
        self.todos = [t for t in self.todos if t["id"] != todo["id"]]
        self._commit()

    def _commit(self):
        save_todos(self.todos)
        self.render()

    def _open_dialog(self, dlg, apply):
        self.dialog_open = True
        self.root.wait_window(dlg)
        self.dialog_open = False
        if dlg.result:
            apply(*dlg.result)

    # ---------------- 右键菜单 ----------------
    def _row_menu(self, e, todo):
        m = tk.Menu(self.root, tearoff=0, font=FONT)
        m.add_command(label="修改日期", command=lambda: self.edit_date(todo))
        m.add_command(label="编辑内容", command=lambda: self.edit_text(todo))
        m.add_command(label="删除", command=lambda: self.delete_todo(todo))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _title_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, font=FONT)
        m.add_command(label="取消置顶" if self.pinned else "置顶前台",
                      command=self.toggle_pin)
        m.add_command(label="取消开机自启" if self.auto_start else "开机自动启动",
                      command=self.toggle_autostart)
        m.add_separator()
        m.add_command(label="退出", command=self.on_close)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _root_menu(self, e):
        if not self.collapsed_edge:
            return
        m = tk.Menu(self.root, tearoff=0, font=FONT)
        m.add_command(label="展开窗口", command=self.expand)
        m.add_command(label="退出程序", command=self.on_close)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _root_press(self, e):
        if self.collapsed_edge:
            self.expand()

    # ---------------- 置顶 / 开机自启 ----------------
    def toggle_pin(self):
        self.pinned = not self.pinned
        self.root.wm_attributes("-topmost", self.pinned)
        self._refresh_pin_btn()
        self.save_settings()

    def _refresh_pin_btn(self):
        if self.pinned:
            self.pin_btn._base = {"bg": BRAND_TINT, "hover": "#DCEAFF"}
            self.pin_btn.configure(text="置顶", bg=BRAND_TINT, fg=BRAND,
                                   font=FONT_SMALL_BOLD)
        else:
            self.pin_btn._base = {"bg": BTN_BG, "hover": BTN_HOVER}
            self.pin_btn.configure(text="置顶", bg=BTN_BG, fg=TEXT_SUB,
                                   font=FONT_SMALL)

    def toggle_autostart(self):
        ok = self._set_autostart(not self.auto_start)
        if ok:
            self.auto_start = not self.auto_start
            self.save_settings()

    def _autostart_enabled(self):
        if not winreg:
            return False
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_READ)
            v, _ = winreg.QueryValueEx(k, "DesktopTodo")
            winreg.CloseKey(k)
            return bool(v)
        except Exception:
            return False

    def _set_autostart(self, on):
        if not winreg:
            from tkinter import messagebox
            messagebox.showerror("开机自启", "当前环境不支持注册表操作",
                                 parent=self.root)
            return False
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_SET_VALUE)
            if on:
                if getattr(sys, "frozen", False):
                    cmd = '"%s"' % sys.executable
                else:
                    pyw = os.path.join(os.path.dirname(sys.executable),
                                       "pythonw.exe")
                    cmd = '"%s" "%s"' % (pyw, os.path.abspath(__file__))
                winreg.SetValueEx(k, "DesktopTodo", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "DesktopTodo")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(k)
            return True
        except Exception as ex:
            from tkinter import messagebox
            messagebox.showerror("开机自启", "设置失败: %s" % ex, parent=self.root)
            return False

    # ---------------- 窗口拖动 / 缩放 / 边缘吸附 ----------------
    def _move_to(self, x, y):
        """移动窗口并同步逻辑坐标。

        winfo_x/y 在 geometry 请求后不会立即更新（存在滞后），
        因此窗口位置以 _pos 为唯一事实源，避免夹紧被旧读数覆盖。
        """
        x, y = int(x), int(y)
        self._pos = [x, y]
        self.root.geometry("+%d+%d" % (x, y))

    def _cancel_anim(self):
        if self._anim_id is not None:
            self.root.after_cancel(self._anim_id)
            self._anim_id = None
        self.animating = False

    def _drag_start(self, e):
        if self.collapsed_edge:
            self.expand()
            return
        self._cancel_anim()  # 用户接管拖拽时终止进行中的动画
        self._drag = (e.x_root - self._pos[0],
                      e.y_root - self._pos[1])

    def _drag_move(self, e):
        if not self._drag:
            return
        dx, dy = self._drag
        # 按整个虚拟桌面夹紧，允许在所有显示器之间自由拖动；
        # 悬进"死区"（显示器之间的空隙）的部分在松手时统一纠正
        vx, vy, vw, vh = screen_bounds(self.root)
        w, h = self.root.winfo_width(), self.root.winfo_height()
        nx = min(max(e.x_root - dx, vx), vx + vw - w)
        ny = min(max(e.y_root - dy, vy), vy + vh - h)
        self._move_to(nx, ny)

    def _drag_stop(self, e):
        self._drag = None
        self.expanded_from_edge = False
        self._keep_on_monitors(e)
        self.snap_check(e.x_root, e.y_root)
        self._schedule_save_settings()

    def _keep_on_monitors(self, e):
        """松手后确保窗口没有悬进显示器之间的死区。

        窗口允许跨屏（压在两块屏幕上），但若任何部分落在
        没有显示器的区域，则整体拉回鼠标所在显示器的工作区。
        全程基于逻辑坐标 _pos 计算，不读 winfo。
        """
        try:
            x, y = self._pos
            w, h = self.root.winfo_width(), self.root.winfo_height()
            pts = [(x + 2, y + 2), (x + w - 2, y + 2),
                   (x + 2, y + h - 2), (x + w - 2, y + h - 2),
                   (x + w // 2, y + 2), (x + w // 2, y + h - 2),
                   (x + 2, y + h // 2), (x + w - 2, y + h // 2)]
            if all(monitor_at_point(px, py) is not None for px, py in pts):
                return
            mon = (monitor_at_point(e.x_root, e.y_root, nearest=True)
                   or monitor_work_area(self.root))
            mx, my, mw, mh = mon
            nx = max(mx, min(x, mx + mw - w))
            ny = max(my, min(y, my + mh - h))
            if (nx, ny) != (x, y):
                self._move_to(nx, ny)
        except Exception:
            pass

    def _resize_start(self, e):
        self._rz = (e.x_root, e.y_root,
                    self.root.winfo_width(), self.root.winfo_height())

    def _resize_move(self, e):
        if not self._rz:
            return
        x0, y0, w0, h0 = self._rz
        nw = max(WIN_MIN_W, w0 + e.x_root - x0)
        nh = max(WIN_MIN_H, h0 + e.y_root - y0)
        self.root.geometry("%dx%d" % (nw, nh))

    def _near_edge_on(self, mon):
        """窗口相对指定显示器工作区是否贴近某个边缘。"""
        x, y = self._pos
        w, h = self.root.winfo_width(), self.root.winfo_height()
        mx, my, mw, mh = mon
        if x - mx <= EDGE_MARGIN:
            return "left"
        if mx + mw - (x + w) <= EDGE_MARGIN:
            return "right"
        if y - my <= EDGE_MARGIN:
            return "top"
        return None

    def _near_edge(self):
        return self._near_edge_on(monitor_work_area(self.root))

    def _near_specific_edge(self, edge):
        mon = self.saved_mon or monitor_work_area(self.root)
        x, y = self._pos
        w, h = self.root.winfo_width(), self.root.winfo_height()
        mx, my, mw, mh = mon
        if edge == "left":
            return x - mx <= EDGE_MARGIN
        if edge == "right":
            return mx + mw - (x + w) <= EDGE_MARGIN
        if edge == "top":
            return y - my <= EDGE_MARGIN
        return False

    def _edge_is_outer(self, edge, mon):
        """检查某边缘外侧是否为真实的屏幕外沿。

        两块显示器的交界处外侧还有另一块屏幕，若在此收起，
        窗口主体会完整显示到邻屏上，因此交界处不算可收起的
        "屏幕边缘"。在边缘外侧的近端与远端多处探测，
        兼容错位/部分重叠排列的屏幕。
        """
        x, y = self._pos
        w, h = self.root.winfo_width(), self.root.winfo_height()
        mx, my, mw, mh = mon
        probes = []
        if edge == "left":
            for py in (y + 4, y + h // 2, y + h - 4):
                probes += [(mx - 5, py), (mx - w + 4, py)]
        elif edge == "right":
            for py in (y + 4, y + h // 2, y + h - 4):
                probes += [(mx + mw + 5, py), (mx + mw + w - 4, py)]
        else:  # top
            for px in (x + 4, x + w // 2, x + w - 4):
                probes += [(px, my - 5), (px, my - h + 4)]
        for px, py in probes:
            if monitor_at_point(px, py) is not None:
                return False
        return True

    def snap_check(self, mx=None, my=None):
        """检测是否贴到可收起的屏幕边缘。

        参考显示器取鼠标所在屏（拖拽松手时鼠标必然在真实屏幕上），
        只有该边缘外侧确实没有其他显示器时才收起。
        """
        if self.animating or self.collapsed_edge:
            return
        if mx is not None:
            mon = (monitor_at_point(mx, my, nearest=True)
                   or monitor_work_area(self.root))
        else:
            mon = monitor_work_area(self.root)
        edge = self._near_edge_on(mon)
        if edge and self._edge_is_outer(edge, mon):
            self.collapse(edge, mon)

    def collapse(self, edge, mon=None):
        if self.collapsed_edge == edge:
            return
        self.saved_geo = [self._pos[0], self._pos[1],
                          self.root.winfo_width(), self.root.winfo_height()]
        # 记录收起时所在的显示器，展开时严格按原屏还原，绝不跳屏
        self.saved_mon = mon or monitor_work_area(self.root)
        self.collapsed_edge = edge
        self.last_edge = edge
        x, y, w, h = self.saved_geo
        mx, my, mw, mh = self.saved_mon
        if edge == "left":
            tx, ty = mx - w + STRIP, y
        elif edge == "right":
            tx, ty = mx + mw - STRIP, y
        else:  # top
            tx, ty = x, my - h + STRIP
        self._anim_to(tx, ty)

    def expand(self):
        if not self.collapsed_edge:
            return
        self.collapsed_edge = None
        self.expanded_from_edge = True
        x, y, w, h = self.saved_geo
        # 还原到收起前的原始屏幕和位置（按收起时记录的显示器夹紧，
        # 而不是按当前最近显示器——收起时窗口大半在屏幕外，
        # 最近显示器可能已变成邻屏，那样会造成跳屏）
        mon = self.saved_mon or monitor_work_area(self.root)
        mx, my, mw, mh = mon
        x = max(mx, min(x, mx + mw - w))
        y = max(my, min(y, my + mh - h))
        self._anim_to(x, y)

    def _anim_to(self, tx, ty, on_done=None):
        if self._anim_id is not None:
            self.root.after_cancel(self._anim_id)
            self._anim_id = None
        self.animating = True

        def step():
            cx, cy = self._pos
            dx, dy = tx - cx, ty - cy
            if abs(dx) <= ANIM_STEP_PX and abs(dy) <= ANIM_STEP_PX:
                self._move_to(tx, ty)
                self.animating = False
                self._anim_id = None
                # 强制完成重绘：无装饰窗口从屏幕外滑回时，
                # 新暴露区域可能不会自动重画，这里显式刷新
                try:
                    self.root.update_idletasks()
                except Exception:
                    pass
                if on_done:
                    on_done()
                return
            mx = max(-ANIM_STEP_PX, min(ANIM_STEP_PX, dx))
            my = max(-ANIM_STEP_PX, min(ANIM_STEP_PX, dy))
            self._move_to(cx + mx, cy + my)
            self._anim_id = self.root.after(ANIM_STEP_MS, step)

        step()

    def _in_window(self, px, py):
        x, y = self._pos
        return (x <= px <= x + self.root.winfo_width()
                and y <= py <= y + self.root.winfo_height())

    def _in_strip(self, px, py):
        """鼠标是否在收起边条（屏幕边缘条带区）上。

        始终按"收起时所在显示器的屏幕边缘"计算，收起与展开两种
        状态下一致：展开后鼠标仍停在边缘条带区内时不应触发再收起，
        否则会出现展开/收起的无限振荡。
        """
        edge = self.collapsed_edge or self.last_edge
        if not edge:
            return False
        mon = self.saved_mon or monitor_work_area(self.root)
        mx, my, mw, mh = mon
        x, y = self._pos
        w, h = self.root.winfo_width(), self.root.winfo_height()
        pad = 6  # 略微放宽命中范围，便于悬停
        if edge == "left":
            rx, ry, rw, rh = mx - pad, y, STRIP + pad, h
        elif edge == "right":
            rx, ry, rw, rh = mx + mw - STRIP, y, STRIP + pad, h
        else:
            rx, ry, rw, rh = x, my - pad, w, STRIP + pad
        return rx <= px <= rx + rw and ry <= py <= ry + rh

    def _hover_loop(self):
        if self.collapsed_edge:
            px, py = self.root.winfo_pointerxy()
            if self._in_strip(px, py):
                self.expand()
        elif (self.expanded_from_edge and not self.animating
              and self.last_edge):
            px, py = self.root.winfo_pointerxy()
            if (not self._in_window(px, py)
                    and not self._in_strip(px, py)
                    and self._near_specific_edge(self.last_edge)):
                self.collapse(self.last_edge)
        self.root.after(HOVER_POLL_MS, self._hover_loop)

    # ---------------- 定时刷新 ----------------
    def _tick(self):
        if today_str() != self.last_date:
            self.last_date = today_str()
            self._refresh_date()
            self.render()
        self.root.after(REFRESH_MS, self._tick)

    def _refresh_date(self):
        d = dt.date.today()
        self.date_lbl.configure(text="%d月%d日 %s" % (d.month, d.day,
                                                      WEEK_CN[d.weekday()]))

    # ---------------- 设置持久化 ----------------
    def _current_geo(self):
        if self.collapsed_edge and self.saved_geo:
            return self.saved_geo
        return [self._pos[0], self._pos[1],
                self.root.winfo_width(), self.root.winfo_height()]

    def _schedule_save_settings(self):
        if self._save_geo_id is not None:
            self.root.after_cancel(self._save_geo_id)
        self._save_geo_id = self.root.after(400, self.save_settings)

    def save_settings(self):
        save_json(SETTINGS_FILE, {
            "pinned": self.pinned,
            "auto_start": self.auto_start,
            "geometry": self._current_geo(),
        })

    def on_close(self):
        self.save_settings()
        save_todos(self.todos)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TodoApp(root)
    root.update_idletasks()
    app._refresh_date()
    app._refresh_pin_btn()
    app.render()
    app._hover_loop()
    app._tick()
    root.mainloop()


if __name__ == "__main__":
    main()
