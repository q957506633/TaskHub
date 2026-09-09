#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""taskhub_gui_flet.py —— 工作任务跟踪台 v4（Flet / Flutter 渲染）。

对标 QQ 桌面端的圆角现代布局：暗色/亮色双主题、卡片化四视图、
对话框居中 + 内容滚动、DPI 无损。业务规则完全复用 taskhub.py，
与 CLI 共用同一 SQLite 库。

用法：
  python taskhub_gui_flet.py                 # 正常启动
  python taskhub_gui_flet.py --smoke [视图]  # 冒烟自检：渲染后自动退出
依赖：flet >= 0.86、flet-charts；业务层仅标准库。
"""

from __future__ import annotations

import datetime
import taskhub as th
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import flet as ft
except ImportError:  # pragma: no cover —— 无 flet 时由 run.py 决定回退
    ft = None

try:
    import flet_charts as fc
except ImportError:
    fc = None

import taskhub  # noqa: E402  业务层
import i18n  # noqa: E402  GUI 双语文案层（仅显示层，不动 CLI / 数据契约）
from i18n import (  # noqa: E402
    dpriority, dstatus, dfilter, get_lang, month_name, set_lang, tr,
    weekday_name,
)

APP_VERSION = "TaskHub v4.9"

# ---------------------------------------------------------------------------
# Apple 设计语言令牌（视觉宪法，2026-09-09 重构）
# 单一点缀色 Action Blue + 大留白 + 负字距标题 + 表面色彩做分区
# 权威来源：SKILL flet-desktop-ui → references/apple-design-tokens.md
# ---------------------------------------------------------------------------

# ---------- Apple 颜色（规范原值，勿改 hex） ----------
A = {
    "primary": "#0066cc", "primary_focus": "#0071e3", "primary_on_dark": "#2997ff",
    "ink": "#1d1d1f", "body_muted": "#cccccc", "ink80": "#333333", "ink48": "#7a7a7a",
    "divider_soft": "#f0f0f0", "hairline": "#e0e0e0",
    "canvas": "#ffffff", "parchment": "#f5f5f7", "pearl": "#fafafc",
    "tile1": "#272729", "tile2": "#2a2a2c", "tile3": "#252527",
    "black": "#000000", "chip": "#d2d2d7",
    # 语义色（补充，非规范）：仅作状态色，禁止当交互色
    "success": "#34c759", "warn": "#ff9f0a", "danger": "#ff3b30",
}

# ---------- 主题表（明暗；所有控件取色必须走 T，禁止硬编码） ----------
def _apple_theme(dark: bool) -> dict:
    if dark:
        return {
            "bg": A["black"], "surface": A["tile1"], "surface2": A["tile2"],
            "surface3": A["tile3"],
            "border": "#3a3a3c", "divider": "#333335",
            "hover": "#1f1f21", "tint": "#2e2997ff", "track": A["tile2"],
            "text": "#ffffff", "sub": A["body_muted"], "faint": A["ink48"],
            "accent": A["primary_on_dark"], "on_accent": "#ffffff",
            "st_text": {"待办": "#7fb3e0", "进行中": "#f0bc72",
                        "已搁置": "#efe29a", "已完成": "#7cbe81"},
            "pr_text": {"高": "#e58a6f", "中": "#f0bc72", "低": "#9aa599"},
        }
    return {
        "bg": A["parchment"], "surface": A["canvas"], "surface2": A["parchment"],
        "surface3": A["pearl"],
        "border": A["hairline"], "divider": A["divider_soft"],
        "hover": A["parchment"], "tint": "#1a0066cc", "track": A["divider_soft"],
        "text": A["ink"], "sub": A["ink80"], "faint": A["ink48"],
        "accent": A["primary"], "on_accent": "#ffffff",
        "st_text": {"待办": "#48628a", "进行中": "#9a6210",
                    "已搁置": "#7e6c10", "已完成": "#3f7d45"},
        "pr_text": {"高": A["danger"], "中": A["warn"], "低": "#6b756a"},
    }

# 旧别名（过渡期兼容引用，新代码用 T["accent"]）
_LIGHT = _apple_theme(False)
_DARK  = _apple_theme(True)

# ---------- 圆角 / 间距 ----------
R = {"none": 0, "xs": 5, "sm": 8, "md": 11, "lg": 18, "pill": 9999}
S = {"xxs": 4, "xs": 8, "sm": 12, "md": 16, "lg": 24, "xl": 32}

# ---------- 字体 ----------
FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"

def _ts(size, weight=400, height=None, ls=None):
    """Apple 排版工厂：字重只取 300/400/600/700。"""
    return ft.TextStyle(
        font_family=FONT_FAMILY,
        size=size,
        weight=getattr(ft.FontWeight, f"W_{weight}", ft.FontWeight.W_400),
        height=height, letter_spacing=ls,
    )

# 桌面降档字号（web → 桌面）
TYPE = {
    "body":           dict(size=13, weight=400, height=1.47, ls=-0.29),
    "body_strong":    dict(size=13, weight=600, height=1.24, ls=-0.29),
    "caption":        dict(size=12, weight=400, height=1.43, ls=-0.19),
    "caption_strong": dict(size=12, weight=600, height=1.29, ls=-0.19),
    "fine":           dict(size=11, weight=400, height=1.0,  ls=0.0),
    "tagline":        dict(size=16, weight=600, height=1.19, ls=0.18),
    "display":        dict(size=20, weight=600, height=1.10, ls=0.0),
}

# ---------- 按钮样式工厂（elevation=0 是硬要求） ----------
def _btn_style_token(T, kind="primary"):
    if kind == "primary":
        return ft.ButtonStyle(
            shape=ft.StadiumBorder(),
            bgcolor=T["accent"], color="#ffffff",
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            elevation=0,
            text_style=_ts(**TYPE["caption_strong"]),
        )
    if kind == "secondary":
        return ft.ButtonStyle(
            shape=ft.StadiumBorder(),
            bgcolor=ft.Colors.TRANSPARENT, color=T["accent"],
            side={ft.ControlState.DEFAULT: ft.BorderSide(1, T["accent"])},
            padding=ft.Padding.symmetric(horizontal=16, vertical=8),
            elevation=0,
            text_style=_ts(**TYPE["caption_strong"]),
        )
    # utility：surface3 底 + 主题描边 + 主题文字
    return ft.ButtonStyle(
        shape=ft.StadiumBorder(),
        bgcolor=T["surface3"], color=T["text"],
        side={ft.ControlState.DEFAULT: ft.BorderSide(1, T["border"])},
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        elevation=0,
        text_style=_ts(**TYPE["caption"]),
    )

# ---------- 语义状态色（图表/徽章/状态指示，禁止当交互色） ----------
ST_FILL = {"待办": "#7d9dc6", "进行中": "#eca23f",
           "已搁置": "#efdb56", "已完成": "#59a55d"}
PR_FILL = {"高": "#ca4d2a", "中": "#eca23f", "低": "#8a94a0"}
OK_GREEN = A["success"]
DANGER = A["danger"]
WARN = A["warn"]
BAR_PALETTE = ["#59a55d", "#7d9dc6", "#eca23f", "#efdb56", "#ca4d2a",
               "#4c9051", "#9fb9dc", "#8a94a0"]

# 导航项：第二个元素为 i18n 文案键（改文案只动 i18n.py）
VIEW_DEFS = [
    ("dash", "nav_dashboard", "dashboard_outlined"),
    ("board", "nav_board", "view_kanban_outlined"),
    ("ledger", "nav_ledger", "table_rows_outlined"),
    ("cal", "nav_calendar", "calendar_month_outlined"),
]
VIEW_TITLE_KEYS = {"dash": "view_dashboard", "board": "view_board",
                   "ledger": "view_ledger", "cal": "view_calendar"}

BOARD_DONE_LIMIT = 5  # 看板「已完成」列仅展示最近 N 条

# 台账排序字段：全部是 tasks 表的真实列名（内部值，不随语言变化）
SORT_FIELDS = ["created_at", "deadline", "priority", "status", "title",
               "project", "start_date", "finish_date"]
# 排序字段 → 排序下拉框文案键（`sort_<字段名>`）
SORT_LABEL_KEYS = {f: "sort_" + f for f in SORT_FIELDS}

# 月历日程类型（内部中文值）→ 文案键：截止 / 开始 / 完成
CAL_KIND_KEYS = {"截止": "cal_legend_deadline", "开始": "cal_legend_start",
                 "完成": "cal_legend_finish"}


def radius(v):
    """圆角（0.86 单值构造；旧版四值构造兜底）。"""
    try:
        return ft.BorderRadius(v)
    except (TypeError, ValueError):
        return ft.BorderRadius(v, v, v, v)


def icon(name: str) -> str:
    """图标名转 0.86 枚举值；缺失时回退到通用图标。"""
    try:
        return getattr(ft.Icons, name.upper())
    except AttributeError:
        return getattr(ft.Icons, "CIRCLE")


# 筛选区控件统一规格（Apple 密集筛选栏降档）：120×36 圆角8 浅灰底 同色描边，
# 按钮自适应宽度（去固定宽），解决窄窗口下最右按钮被截断的问题。
_FILTER_W = 120
_FILTER_H = 36
_FILTER_PAD = ft.Padding.symmetric(horizontal=10, vertical=6)


def _filter_dd_factory(T, values, value, on_change, width=_FILTER_W, fmt=None,
                       menu_height=None):
    """统一规格的筛选下拉框：宽 120 高 36，圆角 8，浅灰底，与文本框同款。

    ⚠️ Flet 0.86 新版 M3 Dropdown 的 height 属性压不矮字段（GitHub #5215，
    dense 也只能到 ~46），唯一可靠做法：Container(固定宽高) +
    Dropdown(dense=True, expand=True)，由 Container 裁掉 M3 溢出。

    fmt：内部值 → 显示文案的映射函数（i18n 显示层翻译用）。
    Dropdown.value 取的是 option 的 **key**（内部中文原值），text 仅用于
    展示，因此筛选 / 写入 / 排序逻辑拿到的仍是中文原值。
    """
    options = []
    for v in values:
        options.append(ft.dropdown.Option(key=v, text=(fmt(v) if fmt else v)))
    return ft.Container(
        width=width, height=_FILTER_H,
        content=ft.Dropdown(
            value=value, dense=True, expand=True, text_size=12,
            border_radius=radius(8), border_color=T["border"], border_width=1,
            focused_border_color=T["accent"],
            filled=True, fill_color=T["surface2"],
            menu_height=menu_height,
            menu_style=ft.MenuStyle(
                bgcolor=ft.Colors.with_opacity(0.82, T["surface"]),
                elevation=0,
                shape=ft.RoundedRectangleBorder(radius=radius(8)),
                side=ft.BorderSide(1, T["border"])),
            content_padding=ft.Padding.symmetric(horizontal=10, vertical=2),
            options=options,
            on_select=on_change,
        ),
    )


def _filter_tf_factory(T, value, hint_text, on_change, width=_FILTER_W):
    """统一规格的筛选文本框：与下拉框完全同款——120×36、圆角 8、浅灰底、
    1px 描边；焦点时主题色描边、光标主题色，保证两者等宽等高、行内居中对齐。"""
    return ft.TextField(
        value=value, width=width, height=_FILTER_H, text_size=12,
        border_radius=radius(8), border_color=T["border"], border_width=1,
        focused_border_color=T["accent"], cursor_color=T["accent"],
        filled=True, fill_color=T["surface2"],
        content_padding=_FILTER_PAD,
        hint_text=hint_text,
        on_change=on_change,
    )


def _filter_btn_factory(T, label, icon_name, on_click, *, width=None,
                        primary=False):
    """统一规格的筛选按钮：胶囊形（StadiumBorder）、utility 描边、自适应
    宽度（content+padding），高 36 与下拉/文本框同排对齐。
    primary=True 时为 Action Blue 主按钮。"""
    btn_inner = ft.Row([
        ft.Icon(icon(icon_name), size=14,
                color=T["on_accent"] if primary else T["text"])
        if icon_name else ft.Container(),
        ft.Container(width=4) if icon_name else ft.Container(),
        ft.Text(label, size=12,
                weight=ft.FontWeight.W_600,
                color=T["on_accent"] if primary else T["text"],
                no_wrap=True),
    ], tight=True, spacing=2)
    style = _btn_style_token(T, "primary" if primary else "utility")
    return (ft.FilledButton if primary else ft.OutlinedButton)(
        content=btn_inner, width=width, height=_FILTER_H,
        style=style, on_click=on_click)


# 筛选下拉里「非数据值」的固定项：先走 dfilter（全部 → All），
# 其余（状态 / 类型 / 优先级 / 项目）走各自显示映射。
_FIXED_FILTER_ITEMS = ("全部", "未完结", "逾期", "今日到期", "7天内到期",
                       "本月完成")


def _opt_label(value: str, mapper=None) -> str:
    """下拉项显示文案。

    固定筛选项（全部 / 未完结 / 快捷口径）→ dfilter；
    数据值 → 传入的 mapper（dstatus / dtype / dpriority / dproject）。
    下拉的 **value 仍是中文原值**，仅显示层翻译。
    """
    if value in _FIXED_FILTER_ITEMS:
        return dfilter(value)
    return mapper(value) if mapper else value


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------

class TaskHubFlet:

    def __init__(self, page: "ft.Page", smoke_view: str = ""):
        self.page = page
        self.dark = False
        self.rows: list[dict] = []
        self.view = "dash"
        self.smoke_view = smoke_view
        if smoke_view:
            # 冒烟模式：无论后续是否异常都保证进程退出
            threading.Timer(6.0, lambda: os._exit(0)).start()

        # 看板筛选
        self.bf_proj, self.bf_pri, self.bf_type = "全部", "全部", "全部"
        self.bf_kw = ""
        # 台账筛选
        self.lt_status, self.lt_proj = "全部", "全部"
        self.lt_type, self.lt_pri, self.lt_quick = "全部", "全部", "全部"
        self.lt_kw, self.lt_overdue = "", False
        # 默认排序：录入时间降序（最新录入在前），与「近期关注」卡片一致。
        # lt_sort 存 tasks 表列名（内部值，不随语言变化）
        self.lt_sort, self.lt_asc = "created_at", False
        self.lt_page, self.lt_pagesize = 1, 50
        # 月历
        today = datetime.date.today()
        self.cal_year, self.cal_month = today.year, today.month
        self.cal_sel = today.isoformat()

        self.is_desktop = "--desktop" in sys.argv

        def on_key(e: "ft.KeyboardEvent"):
            if e.key == "Escape":
                self._pop_dlg()
            elif e.key == "F5":
                self.refresh()

        try:
            self.page.on_keyboard_event = on_key
        except Exception:
            pass
        self._detail_rid = None
        self._detail_open = False
        self._ttypes: list[str] = []      # 用户自定义任务类型（数据库托管）
        self._projects: list[str] = []    # 用户自定义所属项目（数据库托管）
        self._last_type: str = "日常事务"  # 类型下拉上次合法值（哨兵还原用）
        self._last_proj: str = "其他"      # 项目下拉上次合法值（哨兵还原用）
        self._apps: list[dict] = []
        self._ctx_app: dict | None = None
        self._load_apps()  # 须在 _build_shell 之前：应用侧栏首屏渲染依赖 _apps
        self._setup_page()
        self._build_shell()
        self._load_task_types()
        self.load_rows(render=True)
        # 壳层就绪后再最大化（默认全屏，窗口化被 w.on_event 拉回）
        try:
            self.page.window.maximized = True
            self.page.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 主题 / 页面
    # ------------------------------------------------------------------

    @property
    def T(self) -> dict:
        return _DARK if self.dark else _LIGHT

    def _apply_theme(self):
        # 全局字体：微软雅黑（theme + theme_dark 都设置，
        # 否则暗色模式回退 Flutter 默认字体）。
        # 注意：0.86 的 ColorScheme 没有 seed_color 字段，误传会让整个
        # 主题赋值抛 TypeError —— 此处若被 try/except 吞掉，字体即失效。
        p = self.page
        theme = ft.Theme(
            font_family=FONT_FAMILY,
            color_scheme=ft.ColorScheme(
                primary=self.T["accent"], surface=self.T["surface"]),
        )
        p.theme = theme
        p.theme_dark = theme

    def _setup_page(self):
        p, w = self.page, self.page.window
        p.title = tr("app_title")
        p.padding = 0
        p.bgcolor = self.T["bg"]
        p.theme_mode = ft.ThemeMode.LIGHT
        try:
            self._apply_theme()
        except Exception:
            pass
        try:
            # 小窗下限；最大化放到壳层构建完成之后（见 __init__ 末尾），
            # 否则 maximized 触发的 resized 事件会在壳层就绪前触发重排
            w.min_width, w.min_height = 900, 620
            p.update()
        except Exception:
            pass
        # 禁止窗口化：仅在被还原/取消最大化时一次性拉回最大化，
        # 边缘触发（最大化动作本身产生的是 MAXIMIZE 事件，不会再进这里）。
        # 不监听 on_resized / MAXIMIZE —— 任何后续重排都会拖垮后端。
        try:
            def _win_event(e):
                try:
                    t = getattr(e, "type", None)
                    if t in (ft.WindowEventType.UNMAXIMIZE,
                             ft.WindowEventType.RESTORE):
                        if getattr(self, "content_area", None) is not None:
                            w.maximized = True
                            p.update()
                except Exception:
                    pass
            w.on_event = _win_event
        except Exception:
            pass

    def toggle_theme(self, _e=None):
        self.dark = not self.dark
        p = self.page
        p.theme_mode = ft.ThemeMode.DARK if self.dark else ft.ThemeMode.LIGHT
        p.bgcolor = self.T["bg"]
        try:
            self._apply_theme()
        except Exception:
            pass
        # 全量重建壳层（令牌随主题切换）
        self._rebuild_shell()

    # ------------------------------------------------------------------
    # 语言：中 / 英 切换（写 data/lang.json，随后整界面重建）
    # ------------------------------------------------------------------

    @property
    def lang(self) -> str:
        """当前界面语言（"zh" / "en"）。"""
        return get_lang()

    def toggle_lang(self, _e=None):
        """切换中/英并全量重建界面；持久化到 data/lang.json。"""
        set_lang("en" if get_lang() == "zh" else "zh")
        self._rebuild_shell()
        self._toast(tr("toast_lang_switched"), "ok")

    def _rebuild_shell(self):
        """清空页面控件并重建侧栏 / 顶栏 / 内容区 / 统计文案。

        与 toggle_theme 同一套路：controls.clear() → _build_shell() →
        重渲染当前视图 → 回填统计 → update()，保证不残留旧控件。
        """
        p = self.page
        p.controls.clear()
        self._build_shell()
        self._render_view()
        self._update_stats()
        p.update()

    # ------------------------------------------------------------------
    # 壳层：侧栏 + 主区
    # ------------------------------------------------------------------

    def _build_shell(self):
        self.content_area = ft.Container(expand=True)
        self.topbar_title = ft.Text("", size=20, weight=ft.FontWeight.W_600,
                                    color=self.T["text"])
        self.stat_left = ft.Text("", size=12, color=self.T["sub"])
        self.stat_right = ft.Text("", size=12, color=self.T["faint"])
        self.nav_box = ft.Column(spacing=2)
        self.nav_stat = ft.Text("", size=12, color=self.T["faint"], selectable=False)

        # 侧栏确定性高度：本机 1280×800 逻辑屏最大化后的客户区约 756，
        # 侧栏底部组（统计 + 主题/刷新）随之下沉到与状态栏基线对齐。
        # 不做运行时重排 —— flet 0.86 桌面端任何异步/线程重排都会
        # 拖垮后端（多次实测）；窗口锁定最大化后高度恒定。
        sidebar = ft.Container(
            width=232, height=756,
            bgcolor=self.T["surface"],
            padding=ft.Padding.only(left=12, right=12, top=16, bottom=16),
            content=ft.Column(spacing=0, controls=[
                self._brand(),
                ft.Container(height=14),
                ft.Text(tr("workspace"), size=12, color=self.T["faint"],
                        weight=ft.FontWeight.W_600),
                ft.Container(height=6),
                self.nav_box,
                ft.Container(expand=True),
                self.nav_stat,
                ft.Container(height=8),
                ft.Row([
                    ft.IconButton(icon=icon("dark_mode"), tooltip=tr("tip_theme"),
                                  icon_size=18, icon_color=self.T["sub"],
                                  on_click=self.toggle_theme),
                    ft.IconButton(icon=icon("refresh"), tooltip=tr("tip_refresh"),
                                  icon_size=18, icon_color=self.T["sub"],
                                  on_click=lambda e: self.refresh()),
                ], spacing=2),
            ]),
        )
        self.search_field = ft.TextField(
            width=220, height=36, text_size=13, hint_text=tr("search_hint"),
            value=self.lt_kw,
            prefix_icon=icon("search"), border_radius=radius(R["pill"]),
            border_color=self.T["border"], filled=True,
            fill_color=self.T["surface2"],
            cursor_color=self.T["accent"], content_padding=ft.Padding.only(left=8, right=12),
            on_submit=lambda e: self._search_submit(e.control.value),
        )
        topbar = ft.Container(
            padding=ft.Padding.only(left=24, right=24, top=16, bottom=8),
            content=ft.Row([
                self.topbar_title,
                ft.Container(expand=True),
                self.search_field,
                ft.Container(width=8),
                ft.FilledButton(
                    tr("btn_new_task"), icon=icon("add"),
                    style=self._btn_style(fill=True),
                    on_click=lambda e: self._dlg_add()),
                ft.OutlinedButton(
                    tr("btn_refresh"), icon=icon("autorenew"),
                    style=self._btn_style(fill=False),
                    on_click=lambda e: self.refresh()),
                self._lang_button(),
            ], spacing=8),
        )

        statusbar = ft.Column(spacing=0, controls=[
            ft.Container(height=1, bgcolor=self.T["border"],
                         margin=ft.Margin.symmetric(horizontal=24)),
            ft.Container(
                padding=ft.Padding.only(left=24, right=24, top=12, bottom=12),
                content=ft.Row([self.stat_left,
                                ft.Container(expand=True),
                                self.stat_right]),
            ),
        ])

        self.page.add(ft.Row(spacing=0, expand=True, vertical_alignment=(
            ft.CrossAxisAlignment.STRETCH), controls=[
            self._build_app_rail(),
            ft.Container(width=1, bgcolor=self.T["border"]),
            sidebar,
            ft.Container(width=1, bgcolor=self.T["border"]),
            ft.Container(
                expand=True, content=ft.Column(spacing=0, controls=[
                    topbar,
                    self.content_area,
                    statusbar,
                ]),
            ),
        ]))
        self.topbar_title.value = tr(VIEW_TITLE_KEYS.get(self.view, "app_title"))
        self._render_nav()

    def _lang_button(self):
        """顶栏语言胶囊：显示「将要切换到的语言」，与「刷新」同款描边风格。"""
        T = self.T
        return ft.OutlinedButton(
            content=ft.Row([
                ft.Icon(icon("translate"), size=16),
                ft.Container(width=4),
                ft.Text(tr("lang_switch_to"), size=13,
                        weight=ft.FontWeight.W_600, no_wrap=True),
            ], tight=True, spacing=2),
            height=36,
            tooltip=tr("tip_language"),
            style=ft.ButtonStyle(
                shape=ft.StadiumBorder(),
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                side={ft.ControlState.DEFAULT: ft.BorderSide(1, T["border"])},
                color={ft.ControlState.DEFAULT: T["text"]},
                bgcolor={ft.ControlState.DEFAULT: T["surface"]},
                text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600),
            ),
            on_click=self.toggle_lang,
        )

    def _brand(self):
        logo = ft.Container(
            width=38, height=38, border_radius=radius(11), bgcolor=self.T["accent"],
            alignment=ft.Alignment.CENTER,
            content=ft.Text(tr("brand_logo"), color="white", size=16,
                            weight=ft.FontWeight.W_600),
        )
        return ft.Container(
            padding=ft.Padding.only(left=8, bottom=16),
            content=ft.Row([
                logo,
                ft.Container(width=10),
                ft.Column([ft.Text(tr("brand_name"), size=16,
                                   weight=ft.FontWeight.W_600,
                                   color=self.T["text"]),
                           ft.Text(APP_VERSION, size=11, color=self.T["faint"])],
                          spacing=1),
            ]),
        )

    def _render_nav(self):
        self.nav_box.controls.clear()
        for vid, key, ico in VIEW_DEFS:
            selected = vid == self.view
            self.nav_box.controls.append(
                ft.Container(
                    width=208, border_radius=radius(8),
                    bgcolor=self.T["tint"] if selected else None,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    on_click=lambda e, v=vid: self.set_view(v),
                    on_hover=lambda e, v=vid: self._nav_hover(e, v),
                    content=ft.Row([
                        ft.Icon(icon(ico), size=16,
                                color=self.T["accent"] if selected else self.T["sub"]),
                        ft.Container(width=10),
                        ft.Text(tr(key), size=13,
                                weight=ft.FontWeight.W_600 if selected
                                else ft.FontWeight.W_400,
                                color=self.T["accent"] if selected else self.T["text"]),
                    ]),
                ))
        self.page.update()

    def _nav_hover(self, e, vid):
        if vid == self.view:
            return
        hot = e.data in (True, "true", "True")
        e.control.bgcolor = self.T["hover"] if hot else None
        self.page.update()

    def set_view(self, vid):
        self.view = vid
        self._render_nav()
        self.topbar_title.value = tr(VIEW_TITLE_KEYS.get(vid, "app_title"))
        self._render_view()

    def _btn_style(self, fill: bool):
        """主按钮=Action Blue pill；次要=utility（surface3+描边）。elevation=0。"""
        return _btn_style_token(self.T, "primary" if fill else "utility")

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def load_rows(self, render: bool = True):
        conn = taskhub.open_db()
        try:
            _t, rows, _m = taskhub.query_tasks(conn, "全部", "", "", limit=1000000)
        finally:
            conn.close()
        self.rows = [dict(r) for r in rows]
        today = taskhub.today_str()
        open_cnt = sum(1 for r in self.rows if r["status"] in taskhub.OPEN_STATUSES)
        overdue = sum(1 for r in self.rows
                      if r["status"] != "已完成" and r["deadline"]
                      and r["deadline"] < today)
        self._update_stats()
        if render:
            self._render_view()

    def _update_stats(self):
        """按当前 rows 回填侧栏统计与状态栏文字（整壳重建后需重调）。"""
        today = taskhub.today_str()
        open_cnt = sum(1 for r in self.rows if r["status"] in taskhub.OPEN_STATUSES)
        overdue = sum(1 for r in self.rows
                      if r["status"] != "已完成" and r["deadline"]
                      and r["deadline"] < today)
        self.stat_left.value = tr("stat_left", total=len(self.rows),
                                  open=open_cnt, overdue=overdue)
        self.stat_right.value = tr(
            "stat_right", db=taskhub.db_path(),
            time=datetime.datetime.now().strftime("%H:%M:%S"))
        self.nav_stat.value = tr("nav_stat", total=len(self.rows),
                                 open=open_cnt, overdue=overdue)

    def refresh(self, _e=None):
        self.load_rows(render=True)

    def _render_view(self):
        builders = {"dash": self.view_dash, "board": self.view_board,
                    "ledger": self.view_ledger, "cal": self.view_cal}
        self.content_area.content = builders[self.view]()
        self.page.update()

    def _row_by_id(self, rid):
        return next((r for r in self.rows if r["record_id"] == rid), None)

    # ------------------------------------------------------------------
    # 用户自定义字典（任务类型 / 所属项目：数据库托管，替代硬编码常量）
    # ------------------------------------------------------------------

    # kind → (缓存属性, 哨兵i18n键, 默认回落值, 是否在下拉末尾追加哨兵)
    # proj 的哨兵已移至台账工具栏按钮（manage_proj_title），下拉内不再显示
    _DICTS = {
        "type": ("_ttypes", "manage_type_sentinel", "日常事务", True),
        "proj": ("_projects", "manage_proj_sentinel", "其他", False),
    }

    def _sentinel(self, kind: str) -> str:
        """字典下拉末尾的「管理」哨兵项文案（双语）。"""
        return tr(self._DICTS[kind][1])

    def _load_task_types(self):
        """从数据库读取任务类型与所属项目；失败兜底为空列表（用户自建）。"""
        try:
            conn = taskhub.open_db(create=True)
            try:
                taskhub.ensure_schema(conn)
                self._ttypes = taskhub.list_task_types(conn)
                self._projects = taskhub.list_projects(conn)
            finally:
                conn.close()
        except Exception:
            self._ttypes = []
            self._projects = []

    def _load_apps(self):
        try:
            conn = th.open_db()
        except Exception:
            self._apps = []
            return
        try:
            self._apps = th.list_apps(conn)
        finally:
            conn.close()

    def _app_avatar_color(self, name: str) -> str:
        palette = ["#59A55D", "#EFDB56", "#7D9DC6", "#ECA23F", "#CA4D2A"]
        h = sum(ord(c) for c in (name or "")) or 0
        return palette[h % len(palette)]

    def _app_avatar(self, app: dict, size: int = 44):
        icon = (app.get("icon_path") or "").strip()
        if icon and os.path.isfile(icon):
            return ft.Container(
                width=size, height=size, border_radius=radius(R["md"]),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=icon, width=size, height=size,
                                  fit=ft.ImageFit.CONTAIN),
            )
        letter = (app.get("name") or "?").strip()[:2] or "?"
        return ft.Container(
            width=size, height=size, border_radius=radius(R["md"]),
            bgcolor=self._app_avatar_color(app.get("name", "")),
            alignment=ft.Alignment.CENTER,
            content=ft.Text(letter, color="white", size=16,
                                weight=ft.FontWeight.W_600),
        )

    def _build_app_rail(self):
        T = self.T
        items = [ft.Container(
            width=56, height=56, border_radius=radius(R["md"]),
            bgcolor=T["surface2"], alignment=ft.Alignment.CENTER,
            content=ft.Icon(icon("add"), size=22, color=T["sub"]),
            on_click=lambda e: self._dlg_app_edit(),
            tooltip=tr("app_btn_add"),
        ), ft.Container(height=6)]
        if not self._apps:
            items.append(ft.Container(
                width=56, padding=ft.Padding.symmetric(vertical=6, horizontal=4),
                content=ft.Text(tr("app_no_apps_yet"), size=11,
                                 color=T["faint"],
                                 text_align=ft.TextAlign.CENTER),
            ))
        for a in self._apps:
            app_id = a["id"]
            cell = ft.Container(
                width=56, padding=ft.Padding.symmetric(vertical=2),
                alignment=ft.Alignment.CENTER,
                content=self._app_avatar(a),
                on_click=lambda e, aid=app_id: self._on_app_launch(aid),
                on_secondary_tap=lambda e, app=a: self._open_app_ctx_menu(e, app),
                tooltip=a.get("name", ""),
            )
            items.append(cell)
        return ft.Container(
            width=72,
            bgcolor=T["surface"],
            padding=ft.Padding.only(top=12, bottom=12, left=8, right=8),
            content=ft.Column(items, spacing=4,
                              scroll=ft.ScrollMode.AUTO, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _on_app_launch(self, app_id: int):
        app = next((a for a in self._apps if a["id"] == app_id), None)
        if not app:
            self._toast(tr("app_launch_failed", err=f"id={app_id} 不存在"), "err")
            return
        try:
            th.launch_app(app)
            self._toast(tr("app_launch_ok", name=app["name"]), "ok")
        except Exception as exc:
            self._toast(tr("app_launch_failed", err=str(exc)), "err")

    def _open_app_ctx_menu(self, e, app: dict):
        self._ctx_app = app
        def do_edit(_):
            self._pop_dlg()
            self._dlg_app_edit(app=app)
        def do_delete(_):
            self._pop_dlg()
            self._dlg_app_confirm_delete(app)
        def do_up(_):
            self._pop_dlg()
            self._move_app(app, "up")
        def do_down(_):
            self._pop_dlg()
            self._move_app(app, "down")
        dlg = ft.AlertDialog(
            modal=False, title=ft.Text(app.get("name", "")),
            content=ft.Column([
                ft.TextButton(tr("app_btn_edit"), on_click=do_edit),
                ft.TextButton(tr("app_btn_delete"), on_click=do_delete),
                ft.TextButton(tr("app_btn_move_up"), on_click=do_up),
                ft.TextButton(tr("app_btn_move_down"), on_click=do_down),
            ], tight=True, spacing=2),
        )
        self._show_dlg(dlg)

    def _move_app(self, app: dict, direction: str):
        try:
            conn = th.open_db(create=True)
            try:
                th.move_app(conn, app["id"], direction)
            finally:
                conn.close()
        except Exception as exc:
            self._toast(str(exc), "err")
            return
        self._load_apps()
        self._toast(tr(f"app_toast_moved_{direction}", name=app["name"]), "ok")
        self._rebuild_shell()

    def _dlg_app_confirm_delete(self, app: dict):
        def do_delete(_):
            self._pop_dlg()
            try:
                conn = th.open_db()
                try:
                    th.delete_app(conn, app["id"])
                finally:
                    conn.close()
            except Exception as exc:
                self._toast(str(exc), "err")
                return
            self._load_apps()
            self._toast(tr("app_toast_deleted", name=app["name"]), "ok")
            self._rebuild_shell()
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(tr("app_btn_delete")),
            content=ft.Text(tr("app_confirm_delete", name=app.get("name", ""))),
            actions=[
                ft.TextButton(tr("btn_cancel"), on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("app_btn_delete"), on_click=do_delete),
            ],
        )
        self._show_dlg(dlg)

    def _ensure_pickers(self):
        """懒创建并缓存 FilePicker（0.86: Service 控件严禁挂 page.overlay——
        会被客户端当可视控件渲染，报 Unknown control）。
        构造时若 context 已绑定页面会自动注册；未绑定时显式补注册。"""
        pickers = getattr(self, "_cached_pickers", None)
        if pickers is None:
            pickers = []
            for _ in range(2):
                p = ft.FilePicker()
                try:
                    reg = self.page._services._services
                    if not any(p is x for x in reg):
                        self.page._services.register_service(p)
                except Exception:
                    pass
                pickers.append(p)
            self._cached_pickers = tuple(pickers)
        return self._cached_pickers

    def _dlg_app_edit(self, app: dict | None = None):
        is_edit = bool(app)
        app = app or {}
        file_picker, icon_picker = self._ensure_pickers()
        path_field = ft.TextField(
            label=tr("app_field_path"), value=app.get("path", ""),
            width=420, border_color=self.T["border"], filled=True,
            fill_color=self.T["surface2"],
        )
        async def pick_file(_):
            files = await file_picker.pick_files(
                allow_multiple=False,
                dialog_title=tr("app_btn_pick_file"))
            if files:
                path_field.value = files[0].path or ""
                self.page.update()
        name_field = ft.TextField(
            label=tr("app_field_name"), value=app.get("name", ""),
            width=420, border_color=self.T["border"], filled=True,
            fill_color=self.T["surface2"],
        )
        args_field = ft.TextField(
            label=tr("app_field_args"), value=app.get("args", ""),
            width=420, border_color=self.T["border"], filled=True,
            fill_color=self.T["surface2"],
        )
        icon_field = ft.TextField(
            label=tr("app_field_icon"), value=app.get("icon_path", ""),
            width=300, border_color=self.T["border"], filled=True,
            fill_color=self.T["surface2"],
        )
        async def pick_icon(_):
            files = await icon_picker.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.IMAGE,
                dialog_title=tr("app_btn_pick_icon"))
            if files:
                icon_field.value = files[0].path or ""
                self.page.update()
        def do_save(_):
            n = (name_field.value or "").strip()
            p = (path_field.value or "").strip()
            if not n:
                self._toast(tr("app_name_required"), "err"); return
            if not p:
                self._toast(tr("app_path_required"), "err"); return
            try:
                conn = th.open_db(create=True)
                try:
                    if is_edit:
                        th.update_app(conn, app["id"], n, p,
                                      args_field.value or "",
                                      icon_field.value or "")
                        msg = tr("app_toast_updated", name=n)
                    else:
                        th.add_app(conn, n, p,
                                    args_field.value or "",
                                    icon_field.value or "")
                        msg = tr("app_toast_added", name=n)
                finally:
                    conn.close()
            except Exception as exc:
                self._toast(str(exc), "err"); return
            self._load_apps()
            self._toast(msg, "ok")
            self._pop_dlg()
            self._rebuild_shell()
        dlg = ft.AlertDialog(
            modal=False,
            title=ft.Text(tr("app_title_edit" if is_edit else "app_title_add")),
            content=ft.Container(
                width=480,
                content=ft.Column([
                    name_field,
                    ft.Container(height=8),
                    ft.Row([path_field], wrap=True),
                    ft.TextButton(tr("app_btn_pick_file"), on_click=pick_file),
                    ft.Container(height=8),
                    args_field,
                    ft.Container(height=8),
                    ft.Row([icon_field,
                            ft.IconButton(icon=icon("image"),
                                          tooltip=tr("app_btn_pick_icon"),
                                          on_click=pick_icon)], spacing=4),
                ], tight=True, spacing=0, scroll=ft.ScrollMode.AUTO),
            ),
            actions=[
                ft.TextButton(tr("btn_cancel"), on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("app_btn_save"), on_click=do_save),
            ],
        )
        self._show_dlg(dlg)


    def _options_for(self, kind: str, current: str = None) -> list[str]:
        """字典下拉选项：库内值 + 当前值（若不在库内）+ 末尾管理哨兵。"""
        opts = list(getattr(self, self._DICTS[kind][0]))
        if current and current not in opts:
            opts.append(current)
        if self._DICTS[kind][3]:
            opts.append(self._sentinel(kind))
        return opts

    def _on_dict_change(self, kind: str, dd, e):
        if dd.value == self._sentinel(kind):
            # 还原为上次合法值，再打开管理弹窗
            dd.value = getattr(self, f"_last_{kind}", self._DICTS[kind][2])
            self._safe_update()
            self._open_manage_options(kind, dd)
        else:
            setattr(self, f"_last_{kind}", dd.value)

    def _open_manage_options(self, kind: str, target_dd=None):
        """管理字典项（type=任务类型 / proj=所属项目）：列出/新增/删除；
        实时同步来源下拉框。"""
        T = self.T
        if kind == "type":
            list_fn = taskhub.list_task_types
            add_fn = taskhub.add_task_type
            del_fn = taskhub.delete_task_type
        else:
            list_fn = taskhub.list_projects
            add_fn = taskhub.add_project
            del_fn = taskhub.delete_project
        new_tf = self._tf("", tr(f"manage_{kind}_new_hint"))
        list_col = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=260)

        def rebuild():
            list_col.controls = []
            for name in getattr(self, self._DICTS[kind][0]):
                list_col.controls.append(ft.Row([
                    ft.Text(name, size=13, color=T["text"], expand=True),
                    ft.IconButton(icon("delete"), icon_size=16,
                                  tooltip=tr(f"manage_{kind}_delete"),
                                  on_click=lambda e, n=name: do_delete(n)),
                ], spacing=8))
            self._safe_update()

        def refresh_target():
            if target_dd is not None:
                target_dd.options = [ft.dropdown.Option(v) for v in
                                     self._options_for(kind)]
                self._safe_update()

        def do_add(_e):
            name = (new_tf.value or "").strip()
            if not name:
                self._toast(tr(f"toast_{kind}_name_required"), "warn")
                return
            try:
                conn = taskhub.open_db(create=True)
                try:
                    taskhub.ensure_schema(conn)
                    add_fn(conn, name)
                finally:
                    conn.close()
            except (taskhub.UsageError, taskhub.RunError) as exc:
                self._toast(str(exc), "err")
                return
            self._load_task_types()
            rebuild()
            refresh_target()
            if target_dd is not None:
                target_dd.value = name
                self._safe_update()
            new_tf.value = ""
            self._safe_update()
            self._toast(tr(f"toast_{kind}_added", name=name), "ok")

        def do_delete(name):
            try:
                conn = taskhub.open_db()
                try:
                    del_fn(conn, name)
                finally:
                    conn.close()
            except (taskhub.UsageError, taskhub.RunError) as exc:
                self._toast(str(exc), "err")
                return
            self._load_task_types()
            rebuild()
            refresh_target()
            if target_dd is not None and target_dd.value == name:
                target_dd.value = self._DICTS[kind][2]
                self._safe_update()
            self._toast(tr(f"toast_{kind}_deleted", name=name), "ok")

        dlg = ft.AlertDialog(
            modal=True, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr(f"manage_{kind}_title"), size=16,
                          weight=ft.FontWeight.W_600, color=T["text"]),
            content=ft.Container(width=420, content=ft.Column([
                ft.Text(tr(f"manage_{kind}_list_hint"), size=12, color=T["sub"]),
                list_col,
                ft.Divider(height=1, color=T["border"]),
                ft.Row([
                    ft.Container(content=new_tf, expand=True),
                    ft.FilledButton(tr("btn_add"), icon=icon("add"),
                                    style=self._btn_style(True), on_click=do_add),
                ], spacing=8),
            ], spacing=12, tight=True)),
            actions=[
                ft.OutlinedButton(tr("btn_close_dlg"),
                                  style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        rebuild()
        self._show_dlg(dlg)

    def _open_add_dict(self, kind: str):
        """快速新增字典项（kind=type 任务类型 / proj 所属项目）。

        台账顶栏「新增项目 / 新增任务类型」按钮的弹窗：输入 + 确认，
        点遮罩可关（modal=False，与新建任务弹窗一致）。
        """
        T = self.T
        add_fn = (taskhub.add_task_type if kind == "type"
                  else taskhub.add_project)
        new_tf = self._tf("", tr(f"manage_{kind}_new_hint"))

        def do_add(_e=None):
            name = (new_tf.value or "").strip()
            if not name:
                self._toast(tr(f"toast_{kind}_name_required"), "warn")
                return
            try:
                conn = taskhub.open_db(create=True)
                try:
                    taskhub.ensure_schema(conn)
                    add_fn(conn, name)
                finally:
                    conn.close()
            except (taskhub.UsageError, taskhub.RunError) as exc:
                self._toast(str(exc), "err")
                return
            self._load_task_types()
            self._pop_dlg()
            self._toast(tr(f"toast_{kind}_added", name=name), "ok")

        new_tf.on_submit = do_add
        dlg = ft.AlertDialog(
            modal=False, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr(f"add_{kind}_btn"), size=16,
                          weight=ft.FontWeight.W_600, color=T["text"]),
            content=ft.Container(width=420, content=ft.Column([
                ft.Text(tr(f"manage_{kind}_list_hint"), size=12,
                        color=T["sub"]),
                new_tf,
            ], spacing=12, tight=True)),
            actions=[
                ft.OutlinedButton(tr("btn_cancel"),
                                  style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("btn_add"), icon=icon("add"),
                                style=self._btn_style(True), on_click=do_add),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dlg(dlg)

    # ------------------------------------------------------------------
    # 视图 1：仪表盘
    # ------------------------------------------------------------------

    def view_dash(self):
        T = self.T
        today = taskhub.today_str()
        now_m = today[:7]
        ov = today_cnt = doing = todo = month_done = 0
        for r in self.rows:
            st, dl = r["status"], r["deadline"]
            if st != "已完成":
                if dl:
                    if dl < today:
                        ov += 1
                    elif dl == today:
                        today_cnt += 1
                if st == "进行中":
                    doing += 1
                elif st == "待办":
                    todo += 1
            elif (r["finish_date"] or "").startswith(now_m):
                month_done += 1
        total = max(1, len(self.rows))
        kpis = [
            # (下钻 key, 文案键, 数值, 圆点/进度条用色板原色, 数字用深化变体)
            ("overdue", "kpi_overdue", ov, DANGER, DANGER),
            ("today", "kpi_today", today_cnt, WARN, WARN),
            ("doing", "kpi_doing", doing,
             ST_FILL["进行中"], self.T["st_text"]["进行中"]),
            ("todo", "kpi_todo", todo,
             ST_FILL["待办"], self.T["st_text"]["待办"]),
            ("month", "kpi_month", month_done,
             ST_FILL["已完成"], self.T["st_text"]["已完成"]),
        ]
        kpi_row = ft.Row(spacing=12, controls=[
            self._kpi_card(key, label_key, val, dot, num, total)
            for key, label_key, val, dot, num in kpis
        ])
        return ft.Column(spacing=12, expand=True,
                         controls=[
            ft.Container(padding=ft.Padding.only(left=24, right=24, top=2),
                         content=kpi_row),
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         expand=True, content=ft.Row(spacing=12, controls=[
                self._donut_card(), self._focus_card(),
            ], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)),
            ft.Container(padding=ft.Padding.only(left=24, right=24, bottom=16),
                         expand=True, content=ft.Row(spacing=12, controls=[
                self._bars_card("dash_project_dist", "project"),
                self._bars_card("dash_type_dist", "task_type"),
            ], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)),
        ])

    def _kpi_card(self, key, label, val, dot, num, total):
        T = self.T
        pct = min(100, max(2, round(val / total * 100)))
        return ft.Container(
            expand=True, bgcolor=T["surface"], border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            padding=16, on_click=lambda e, k=key: self._drill_kpi(k),
            on_hover=lambda e, c=None: self._card_hover(e),
            content=ft.Column(spacing=8, controls=[
                ft.Row([ft.Container(width=9, height=9, border_radius=radius(4),
                                     bgcolor=dot),
                        ft.Container(width=6),
                        ft.Text(tr(label), size=12, color=T["sub"])]),
                ft.Text(str(val), size=20, weight=ft.FontWeight.W_600,
                        color=num),
                ft.Row(spacing=0, controls=[
                    ft.Container(height=5, border_radius=radius(4),
                                 bgcolor=dot, expand=pct),
                    ft.Container(height=5, expand=100 - pct),
                ]),
            ]),
        )

    def _card_hover(self, e):
        hot = e.data in (True, "true", "True")
        T = self.T
        e.control.shadow = None
        e.control.border = ft.Border(*[ft.BorderSide(
            1, T["accent"] if hot else T["border"])] * 4)
        self.page.update()

    def _card_shell(self, title, hint, content, height=None, expand=None):
        T = self.T
        return ft.Container(
            expand=expand, height=height, bgcolor=T["surface"],
            border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            padding=ft.Padding.only(left=16, right=16, top=16, bottom=16),
            content=ft.Column(spacing=8, controls=[
                ft.Row([ft.Text(title, size=13, weight=ft.FontWeight.W_600,
                                color=T["text"]),
                        ft.Container(expand=True),
                        ft.Text(hint, size=12, color=T["faint"])]),
                content,
            ]),
        )

    def _donut_card(self):
        T = self.T
        counts = {s: 0 for s in taskhub.VALID_STATUSES}
        for r in self.rows:
            if r["status"] in counts:
                counts[r["status"]] += 1
        total = sum(counts.values())

        legend = ft.Column(spacing=8)
        for st in taskhub.VALID_STATUSES:
            cnt = counts[st]
            pct = round(cnt / total * 100) if total else 0
            legend.controls.append(
                ft.Container(
                    border_radius=radius(8), padding=ft.Padding.symmetric(
                        horizontal=8, vertical=4),
                    on_click=lambda e, s=st: self._drill_status(s),
                    on_hover=lambda e: self._row_hover(e, self.T["tint"]),
                    content=ft.Row([
                        ft.Container(width=8, height=8, border_radius=radius(4),
                                     bgcolor=ST_FILL[st]),
                        ft.Container(width=6),
                        ft.Text(dstatus(st), size=12, color=T["text"],
                                expand=True, max_lines=1, no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"{cnt} · {pct}%", size=12, color=T["sub"],
                                no_wrap=True),
                    ]),
                ))

        if fc is not None and total:
            chart = fc.PieChart(
                sections=[
                    fc.PieChartSection(
                        value=max(1, cnt), color=ST_FILL[st], radius=44,
                        border_side=ft.BorderSide(2, T["surface"]))
                    for st, cnt in counts.items() if cnt
                ],
                sections_space=2,
                center_space_color=T["surface"],
                width=190, height=190,
            )
            center = ft.Container(
                width=190, height=190, alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Text(str(total), size=20, weight=ft.FontWeight.W_600,
                            color=T["text"]),
                    ft.Text(tr("dash_all_tasks"), size=11, color=T["sub"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=0, tight=True),
            )
            chart_box = ft.Stack([chart, center])
        else:
            chart_box = ft.Container(
                width=190, height=190, border_radius=radius(R["pill"]),
                bgcolor=T["track"], alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Text(str(total), size=20, weight=ft.FontWeight.W_600,
                            color=T["text"]),
                    ft.Text(tr("dash_all_tasks"), size=11, color=T["sub"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=0, tight=True))

        prio = ft.Row(spacing=8, wrap=True, run_spacing=4)
        pr_counts = {"高": 0, "中": 0, "低": 0}
        for r in self.rows:
            if r["priority"] in pr_counts:
                pr_counts[r["priority"]] += 1
        for pri, cnt in pr_counts.items():
            prio.controls.append(
                ft.Row([ft.Container(width=7, height=7, border_radius=radius(4),
                                     bgcolor=PR_FILL[pri]),
                        ft.Container(width=3),
                        ft.Text(f"{dpriority(pri)} {cnt}", size=12,
                                color=T["sub"])],
                       tight=True))

        content = ft.Row([
            ft.Container(chart_box, alignment=ft.Alignment.CENTER, expand=True),
            # 190px：完整容纳英文状态名（In Progress/Completed）与计数
            ft.Container(width=190, content=ft.Column(
                [legend, ft.Container(height=8, ), prio], spacing=4)),
        ], expand=True)
        return self._card_shell(tr("dash_status_dist"), tr("dash_status_hint"),
                                content, expand=5)

    def _row_hover(self, e, hot_color):
        hot = e.data in (True, "true", "True")
        e.control.bgcolor = hot_color if hot else None
        self.page.update()

    def _focus_card(self):
        T = self.T
        today = datetime.date.today()
        focus = []
        for r in self.rows:
            if r["status"] == "已完成" or not r["deadline"]:
                continue
            try:
                left = (datetime.date.fromisoformat(r["deadline"]) - today).days
            except ValueError:
                continue
            if left < 0:
                focus.append((0, left, r))
            elif left == 0:
                focus.append((1, left, r))
            elif left <= 7:
                focus.append((2, left, r))
        # 默认按录入时间降序（最新录入在前，与台账默认一致）；
        # 逾期/今天/临近 的分类色标仍在，仅不再参与排序。
        focus.sort(key=lambda t: (t[2].get("created_at") or ""), reverse=True)

        head = ft.Row([ft.Text(tr("dash_focus_title"), size=13,
                               weight=ft.FontWeight.W_600, color=T["text"]),
                       ft.Container(expand=True),
                       ft.Container(
                           bgcolor=ft.Colors.with_opacity(0.12, DANGER),
                           border_radius=radius(R["pill"]),
                           padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                           content=ft.Text(tr("dash_focus_count", n=len(focus)),
                                           size=12, color=DANGER,
                                           weight=ft.FontWeight.W_600))])

        if not focus:
            body: ft.Control = ft.Container(
                alignment=ft.Alignment.CENTER, expand=True,
                content=ft.Column([
                    ft.Text(tr("dash_focus_none1"), size=13,
                            weight=ft.FontWeight.W_600, color=OK_GREEN),
                    ft.Text(tr("dash_focus_none2"), size=12, color=T["faint"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        else:
            items = []
            label_keys = ("tag_overdue", "tag_today", "tag_soon")
            meta_keys = ("focus_overdue", "focus_today", "focus_soon")
            for cat, left, r in focus[:60]:
                color = (DANGER, WARN, self.T["accent"])[cat]
                label = tr(label_keys[cat])
                meta = tr(meta_keys[cat], n=(-left if cat == 0 else left),
                          date=r["deadline"])
                items.append(self._focus_row(r, color, label, meta))
            body = ft.ListView(expand=True, spacing=4, controls=items)

        return ft.Container(
            expand=7, height=208, bgcolor=T["surface"], border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            padding=ft.Padding.only(left=16, right=16, top=16, bottom=16),
            content=ft.Column([head, ft.Text(tr("dash_focus_sub"), size=12,
                                             color=T["faint"]), body],
                              spacing=8))

    def _focus_row(self, r, color, label, meta):
        T = self.T
        return ft.Container(
            border_radius=radius(8), padding=ft.Padding.symmetric(
                horizontal=12, vertical=8),
            on_click=lambda e, rid=r["record_id"]: self._open_detail(rid),
            on_hover=lambda e: self._row_hover(e, T["hover"]),
            content=ft.Row([
                ft.Container(width=3, height=34, border_radius=radius(2),
                             bgcolor=color),
                ft.Container(width=8),
                ft.Column([ft.Text(r["title"], size=13,
                                   weight=ft.FontWeight.W_600, color=T["text"],
                                   max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS,
                                   expand=True),
                           ft.Text(f"{meta} · {r['project']} · "
                                   f"{dstatus(r['status'])}",
                                   size=11, color=T["sub"], max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS,
                                   expand=True)],
                          spacing=2, expand=True),
                ft.Container(width=6),
                ft.Container(bgcolor=color, border_radius=radius(4),
                             padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                             content=ft.Text(label, size=11, color="white",
                                             weight=ft.FontWeight.W_600)),
            ]),
        )

    def _bars_card(self, title_key, field, expand=1):
        """分布条图卡片。

        title_key 为 i18n 文案键；条目标签按字段走显示映射
        （任务类型英文模式下译出，项目名原样显示）。
        """
        T = self.T
        counts: dict[str, int] = {}
        for r in self.rows:
            key = r[field] or tr("dash_empty_value")
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            body = ft.Container(alignment=ft.Alignment.CENTER, expand=True,
                                content=ft.Text(tr("dash_no_data"), size=12,
                                                color=T["faint"]))
        else:
            items = sorted(counts.items(), key=lambda kv: -kv[1])[:8]
            palette = BAR_PALETTE
            max_v = max(1, items[0][1])
            rows = []
            for i, (name, cnt) in enumerate(items):
                pct = max(2, round(cnt / max_v * 100))
                rows.append(ft.Row([
                    ft.Container(width=104, content=ft.Text(
                        name,
                        size=12, color=T["text"], max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.Container(expand=True,
                                 content=ft.Row(spacing=0, controls=[
                                     ft.Container(height=8, border_radius=radius(4),
                                                  bgcolor=palette[i % 8], expand=pct),
                                     ft.Container(height=8, expand=100 - pct),
                                 ])),
                    ft.Container(width=30, content=ft.Text(
                        str(cnt), size=12, color=T["sub"],
                        text_align=ft.TextAlign.RIGHT)),
                ]))
            body = ft.ListView(rows, spacing=8, expand=True)
        return self._card_shell(tr(title_key), tr("dash_bar_hint"), body,
                                expand=expand)

    def _drill_kpi(self, key):
        mapping = {"overdue": ("未完结", "逾期"), "today": ("未完结", "今日到期"),
                   "doing": ("进行中", "全部"), "todo": ("待办", "全部"),
                   "month": ("已完成", "本月完成")}
        status, quick = mapping.get(key, ("全部", "全部"))
        self.lt_status, self.lt_quick = status, quick
        self.lt_proj = self.lt_type = self.lt_pri = "全部"
        self.lt_overdue = False
        self.lt_page = 1
        self.set_view("ledger")

    def _drill_status(self, status):
        self.lt_status = status
        self.lt_quick = self.lt_proj = self.lt_type = "全部"
        self.lt_pri = "全部"
        self.lt_overdue = False
        self.lt_page = 1
        self.set_view("ledger")

    def _search_submit(self, kw):
        kw = (kw or "").strip()
        if not kw:
            return
        self.lt_kw = kw
        self.lt_page = 1
        self.set_view("ledger")

    # ------------------------------------------------------------------
    # 视图 2：看板
    # ------------------------------------------------------------------

    def view_board(self):
        T = self.T

        def bf_dd(label_key, values, value, on_select, fmt=None,
                  menu_height=None):
            # 左右布局：标签居左 + 统一规格下拉框（140×44）
            return ft.Row([
                ft.Text(tr(label_key), size=12, color=T["sub"],
                        weight=ft.FontWeight.W_600),
                _filter_dd_factory(T, values, value, on_select, fmt=fmt,
                                   menu_height=menu_height),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.bf_proj_ctl = bf_dd(
            "flt_project", ["全部"] + self._projects, self.bf_proj,
            lambda e: self._board_filter("proj", e.control.value),
            fmt=dfilter,   # 项目名原样显示，仅「全部」→ All
            menu_height=225)
        self.bf_pri_ctl = bf_dd(
            "flt_priority", ["全部", "高", "中", "低"], self.bf_pri,
            lambda e: self._board_filter("pri", e.control.value),
            fmt=lambda v: _opt_label(v, dpriority))
        self.bf_type_ctl = bf_dd(
            "flt_type", ["全部"] + self._ttypes, self.bf_type,
            lambda e: self._board_filter("type", e.control.value),
            fmt=lambda v: dfilter(v) if v == "全部" else v,
            menu_height=225)
        self.bf_kw_ctl = _filter_tf_factory(
            T, self.bf_kw, tr("flt_keyword"),
            lambda e: self._board_filter("kw", e.control.value))

        filter_bar = ft.Row([
            self.bf_proj_ctl, self.bf_pri_ctl, self.bf_type_ctl,
            self.bf_kw_ctl,
            _filter_btn_factory(
                T, tr("flt_clear_filters"), "filter_alt_off",
                lambda e: self._board_clear()),
        ], spacing=10, scroll=ft.ScrollMode.AUTO,
           vertical_alignment=ft.CrossAxisAlignment.CENTER)

        cols = []
        # 看板列采用确定性高度：按实时窗口高度计算（expand 链在
        # Flet 客户端里会把整块列渲染成空白，不能用）；
        # 窗口尺寸变化由 on_resized 触发重排。
        for st in taskhub.VALID_STATUSES:
            cols.append(self._board_column(st))
        return ft.Column(spacing=8, controls=[
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=filter_bar),
            ft.Container(padding=ft.Padding.only(left=24, right=24, bottom=16),
                         content=ft.Row(spacing=12, controls=cols, expand=True)),
        ])

    def _board_filter(self, which, value):
        setattr(self, {"proj": "bf_proj", "pri": "bf_pri",
                       "type": "bf_type", "kw": "bf_kw"}[which], value)
        self._render_view()

    def _board_clear(self):
        self.bf_proj = self.bf_pri = self.bf_type = "全部"
        self.bf_kw = ""
        self._render_view()

    def _board_column(self, st, col_h=None):
        T = self.T
        if col_h is None:
            # 顶部导航+筛选+状态栏+内边距合计约 185 逻辑像素
            try:
                win_h = int(self.page.window.height or 740)
            except Exception:
                win_h = 740
            col_h = max(420, min(880, win_h - 208))
        kw = taskhub.norm_text(self.bf_kw)
        arr = []
        for r in self.rows:
            if r["status"] != st:
                continue
            if self.bf_proj != "全部" and r["project"] != self.bf_proj:
                continue
            if self.bf_pri != "全部" and r["priority"] != self.bf_pri:
                continue
            if self.bf_type != "全部" and r["task_type"] != self.bf_type:
                continue
            if kw and kw not in taskhub.norm_text(r["title"]) \
                    and kw not in taskhub.norm_text(r["detail"]):
                continue
            arr.append(r)

        if st == "已完成":
            arr.sort(key=lambda r: (r["finish_date"] or "", r["updated_at"] or ""),
                     reverse=True)
            shown, hidden = arr[:BOARD_DONE_LIMIT], len(arr) - min(
                BOARD_DONE_LIMIT, len(arr))
        else:
            arr.sort(key=lambda r: (r["deadline"] or "9999-12-31",
                                    {"高": 0, "中": 1, "低": 2}.get(r["priority"], 3)))
            shown, hidden = arr, 0

        tiles = [self._board_tile(r) for r in shown]
        if hidden > 0:
            tiles.append(ft.Container(
                alignment=ft.Alignment.CENTER, padding=6,
                on_click=lambda e: self._drill_status("已完成"),
                on_hover=lambda e: self._row_hover(e, T["hover"]),
                border_radius=radius(8),
                content=ft.Text(tr("board_done_more", limit=BOARD_DONE_LIMIT,
                                   n=hidden),
                                size=12, color=self.T["accent"],
                                weight=ft.FontWeight.W_600)))
        if not arr:
            tiles.append(ft.Container(
                alignment=ft.Alignment.CENTER, expand=True,
                content=ft.Column([
                    ft.Text(tr("board_empty1"), size=12, color=T["faint"]),
                    ft.Text(tr("board_empty2", new=tr("btn_new_task")),
                            size=11, color=T["faint"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2)))

        header = ft.Container(
            padding=ft.Padding.only(left=12, right=8, top=12, bottom=8),
            content=ft.Row([
                ft.Container(width=8, height=8, border_radius=radius(4),
                             bgcolor=ST_FILL[st]),
                ft.Container(width=6),
                ft.Text(dstatus(st), size=13, weight=ft.FontWeight.W_600,
                        color=T["text"]),
                ft.Container(expand=True),
                ft.Container(bgcolor=ft.Colors.with_opacity(0.12, ST_FILL[st]),
                             border_radius=radius(R["pill"]),
                             padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                             content=ft.Text(str(len(arr)), size=12,
                                             color=T["st_text"][st],
                                             weight=ft.FontWeight.W_600)),
                ft.IconButton(icon=icon("add_small"), icon_size=16,
                              icon_color=T["sub"],
                              tooltip=tr("board_new_in", st=dstatus(st)),
                              on_click=lambda e, s=st: self._dlg_add(status=s)),
            ]),
        )
        return ft.Container(
            expand=True, height=col_h, bgcolor=T["surface"],
            border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            content=ft.Column([header,
                               ft.ListView(expand=True, spacing=8,
                                           padding=ft.Padding.only(
                                               left=8, right=8, bottom=12),
                                           controls=tiles)], expand=True))

    def _board_tile(self, r):
        T = self.T
        today = datetime.date.today()
        dl = r["deadline"]
        if r["status"] == "已完成":
            dtxt, dcolor = tr("tile_done_on",
                              date=r["finish_date"] or tr("ph_empty")), T["faint"]
        elif not dl:
            dtxt, dcolor = tr("tile_no_deadline"), T["faint"]
        else:
            try:
                left = (datetime.date.fromisoformat(dl) - today).days
            except ValueError:
                left = None
            if left is None:
                dtxt, dcolor = dl, T["sub"]
            elif left < 0:
                dtxt, dcolor = tr("tile_overdue", n=-left, date=dl), DANGER
            elif left <= 3:
                dtxt, dcolor = tr("tile_left", n=left, date=dl), WARN
            elif left <= 7:
                dtxt, dcolor = tr("tile_left", n=left, date=dl), self.T["accent"]
            else:
                dtxt, dcolor = dl, T["sub"]

        chips = ft.Row(spacing=4, wrap=False)
        for text, bg, fg in (
                (r["project"], T["track"], T["sub"]),
                (r["task_type"], ft.Colors.with_opacity(0.10, self.T["accent"]),
                 self.T["accent"]),
                (dpriority(r["priority"]),
                 ft.Colors.with_opacity(0.10, PR_FILL[r["priority"]]),
                 T["pr_text"][r["priority"]])):
            chips.controls.append(ft.Container(
                bgcolor=bg, border_radius=radius(4),
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                content=ft.Text(text, size=11, color=fg, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS)))

        return ft.Container(
            bgcolor=T["surface2"], border_radius=radius(R["md"]), padding=10,
            border=ft.Border.all(1, T["border"]),
            on_click=lambda e, rid=r["record_id"]: self._open_detail(rid),
            on_hover=lambda e: self._tile_hover(e),
            content=ft.Column(spacing=8, controls=[
                ft.Text(r["title"], size=13, weight=ft.FontWeight.W_600,
                        color=T["text"], max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                chips,
                ft.Text(dtxt, size=12, color=dcolor),
            ]),
        )

    def _tile_hover(self, e):
        hot = e.data in (True, "true", "True")
        T = self.T
        e.control.bgcolor = T["tint"] if hot else T["surface2"]
        e.control.border = ft.Border(*[ft.BorderSide(
            1, T["accent"] if hot else T["border"])] * 4)
        self.page.update()

    # ------------------------------------------------------------------
    # 视图 3：台账
    # ------------------------------------------------------------------

    # (tasks 表列名, 列宽)；表头文案 = tr("col_<列名>")
    # 列宽按英文文案（i18n）预留：Batch Inspection/In Progress/2026-09-03 等
    # 均不折行；表头与数据行共用本表（数据行经 _ledger_table 内 col_w 引用）
    LT_COLS = [("title", None), ("project", 116), ("task_type", 130),
               ("priority", 84), ("status", 106), ("start_date", 104),
               ("deadline", 104), ("finish_date", 104)]

    def view_ledger(self):
        T = self.T

        def dd(label_key, values, value, on_change, fmt=None,
               menu_height=None):
            # 左右布局：标签居左 + 统一规格下拉框（140×44）
            return ft.Row([
                ft.Text(tr(label_key), size=12, color=T["sub"],
                        weight=ft.FontWeight.W_600),
                _filter_dd_factory(T, values, value, on_change, fmt=fmt,
                                   menu_height=menu_height),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        f_status = dd("flt_status", ["全部", "未完结"] + taskhub.VALID_STATUSES,
                      self.lt_status,
                      lambda e: self._lt_filter("status", e.control.value),
                      fmt=lambda v: _opt_label(v, dstatus))
        f_proj = dd("flt_project", ["全部"] + self._projects,
                    self.lt_proj,
                    lambda e: self._lt_filter("proj", e.control.value),
                    fmt=dfilter,   # 项目名原样显示，仅「全部」→ All
                    menu_height=225)
        f_type = dd("flt_type", ["全部"] + self._ttypes, self.lt_type,
                    lambda e: self._lt_filter("type", e.control.value),
                    fmt=lambda v: dfilter(v) if v == "全部" else v,
                    menu_height=225)
        f_pri = dd("flt_priority", ["全部", "高", "中", "低"], self.lt_pri,
                   lambda e: self._lt_filter("pri", e.control.value),
                   fmt=lambda v: _opt_label(v, dpriority))
        f_quick = dd("flt_quick", ["全部", "逾期", "今日到期", "7天内到期",
                                   "本月完成"],
                     self.lt_quick,
                     lambda e: self._lt_filter("quick", e.control.value),
                     fmt=dfilter)
        kw = _filter_tf_factory(
            T, self.lt_kw, tr("flt_keyword"),
            lambda e: self._lt_filter("kw", e.control.value))
        overdue_chk = ft.Checkbox(
            label=tr("flt_only_overdue"), value=self.lt_overdue,
            label_style=ft.TextStyle(size=12),
            label_position=ft.LabelPosition.RIGHT, active_color=self.T["accent"],
            on_change=lambda e: self._lt_filter("overdue", e.control.value))
        clear_btn = _filter_btn_factory(
            T, tr("flt_clear"), "filter_alt_off", lambda e: self._lt_clear())
        # 排序下拉：value 是表列名（内部值），显示走 sort_<列名> 文案键
        sort_dd = dd("flt_sort", SORT_FIELDS, self.lt_sort,
                     lambda e: self._lt_sort(e.control.value, None),
                     fmt=lambda v: tr(SORT_LABEL_KEYS.get(v, "flt_sort")))
        # 升序 / 导出按钮：与筛选行同高 44，胶囊同款（同「刷新」），避免视觉错落
        dir_btn = _filter_btn_factory(
            T, (tr("btn_asc") if self.lt_asc else tr("btn_desc")), "sort",
            lambda e: self._lt_sort(None, not self.lt_asc))
        export_btn = _filter_btn_factory(
            T, tr("btn_export_csv"), "download",
            lambda e: self._export_csv())
        # 「新增项目 / 新增任务类型」快捷入口：台账顶栏（导出 CSV 左侧）
        add_proj_btn = _filter_btn_factory(
            T, tr("add_proj_btn"), "folder_open",
            lambda e: self._open_add_dict("proj"))
        add_type_btn = _filter_btn_factory(
            T, tr("add_type_btn"), "label",
            lambda e: self._open_add_dict("type"))

        filter_bar = ft.Row([
            f_status, f_proj, f_type, f_pri, f_quick,
            ft.Container(expand=True), export_btn,
        ], spacing=10, scroll=ft.ScrollMode.AUTO,
           vertical_alignment=ft.CrossAxisAlignment.CENTER)
        sort_bar = ft.Row([
            sort_dd, kw, overdue_chk, clear_btn,
            ft.Container(expand=True), dir_btn, add_proj_btn, add_type_btn,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        table_card = ft.Container(
            expand=True, bgcolor=T["surface"], border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            padding=ft.Padding.only(left=8, right=8, top=8, bottom=8),
            content=self._ledger_table(),
        )
        pager = ft.Container(
            padding=ft.Padding.symmetric(horizontal=24),
            content=self._ledger_pager())
        return ft.Column(spacing=8, controls=[
            ft.Container(padding=ft.Padding.only(left=24, right=24, top=2),
                         content=filter_bar),
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=sort_bar),
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=table_card, expand=True),
            pager,
        ])

    def _lt_filter(self, which, value):
        attr = {"status": "lt_status", "proj": "lt_proj", "type": "lt_type",
                "pri": "lt_pri", "quick": "lt_quick", "kw": "lt_kw",
                "overdue": "lt_overdue"}[which]
        setattr(self, attr, value)
        self.lt_page = 1
        self._render_view()

    def _lt_clear(self):
        self.lt_status = self.lt_proj = self.lt_type = "全部"
        self.lt_pri = self.lt_quick = "全部"
        self.lt_kw, self.lt_overdue = "", False
        self.lt_page = 1
        self._render_view()

    def _lt_sort(self, label, asc):
        if label is not None:
            if self.lt_sort == label:
                self.lt_asc = not self.lt_asc
            else:
                self.lt_sort, self.lt_asc = label, True
        elif asc is not None:
            self.lt_asc = asc
        self._render_view()

    def _ledger_filtered(self):
        today = taskhub.today_str()
        now_m = today[:7]
        kw = taskhub.norm_text(self.lt_kw)
        out = []
        for r in self.rows:
            st = r["status"]
            if self.lt_status == "未完结":
                if st not in taskhub.OPEN_STATUSES:
                    continue
            elif self.lt_status != "全部" and st != self.lt_status:
                continue
            if self.lt_proj != "全部" and r["project"] != self.lt_proj:
                continue
            if self.lt_type != "全部" and r["task_type"] != self.lt_type:
                continue
            if self.lt_pri != "全部" and r["priority"] != self.lt_pri:
                continue
            dl = r["deadline"]
            if self.lt_quick == "逾期":
                if st == "已完成" or not dl or dl >= today:
                    continue
            elif self.lt_quick == "今日到期":
                if st == "已完成" or dl != today:
                    continue
            elif self.lt_quick == "7天内到期":
                if st == "已完成" or not dl or dl < today:
                    continue
                try:
                    if (datetime.date.fromisoformat(dl)
                            - datetime.date.today()).days > 7:
                        continue
                except ValueError:
                    continue
            elif self.lt_quick == "本月完成":
                if not (r["finish_date"] or "").startswith(now_m):
                    continue
            if self.lt_overdue and (st == "已完成" or not dl or dl >= today):
                continue
            if kw and kw not in taskhub.norm_text(r["title"]) \
                    and kw not in taskhub.norm_text(r["detail"]):
                continue
            out.append(r)
        # self.lt_sort 直接就是 tasks 表列名；白名单兜底防未知列 KeyError
        # （曾因表头「完成日期」不在映射里导致点击即崩溃，2026-09-08 修复）
        key = self.lt_sort if self.lt_sort in SORT_FIELDS else "created_at"
        rev = not self.lt_asc
        if key == "priority":
            order = {"高": 0, "中": 1, "低": 2}
            out.sort(key=lambda r: (order.get(r["priority"], 3),
                                    r["deadline"] or "9999-12-31"), reverse=rev)
        elif key == "status":
            order = {s: i for i, s in enumerate(taskhub.VALID_STATUSES)}
            out.sort(key=lambda r: (order.get(r["status"], 9),
                                    r["deadline"] or "9999-12-31"), reverse=rev)
        elif key in ("deadline", "finish_date", "created_at"):
            # 日期/时间列：空值（未完成/未记录）恒排最后，再按值升降
            out.sort(key=lambda r: r[key] or "", reverse=rev)
            out.sort(key=lambda r: not r[key])
        else:
            out.sort(key=lambda r: r[key] or "", reverse=rev)
        return out

    def _ledger_table(self):
        T = self.T
        rows = self._ledger_filtered()
        size = max(1, self.lt_pagesize)
        page_count = max(1, -(-len(rows) // size))
        self.lt_page = max(1, min(self.lt_page, page_count))
        start = (self.lt_page - 1) * size
        page_rows = rows[start:start + size]
        self._lt_page_rows = rows

        header_cells = []
        for key, width in self.LT_COLS:
            arrow = ""
            if self.lt_sort == key:
                arrow = " ↑" if self.lt_asc else " ↓"
            t = ft.Text(tr("col_" + key) + arrow, size=12,
                        weight=ft.FontWeight.W_600, color=T["sub"])
            cell = ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                width=width, expand=(width is None),
                on_click=lambda e, k=key: self._lt_sort(k, None),
                content=t)
            header_cells.append(cell)
        header = ft.Container(
            bgcolor=T["surface2"], border_radius=radius(8),
            content=ft.Row(header_cells, spacing=0))

        body_rows = []
        today = taskhub.today_str()
        if not page_rows:
            body_rows.append(ft.Container(
                padding=40, alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Icon(icon("search_off"), size=20, color=T["faint"]),
                    ft.Text(tr("ledger_empty1"), size=13, color=T["sub"]),
                    ft.Text(tr("ledger_empty2"), size=12, color=T["faint"]),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                   spacing=4)))
        for i, r in enumerate(page_rows):
            done = r["status"] == "已完成"
            ovd = (not done and r["deadline"] and r["deadline"] < today)
            st_color = (T["faint"] if done else T["st_text"].get(
                r["status"], T["sub"]))
            dl_color = DANGER if ovd else T["sub"]
            # 数据行列宽与表头共用 LT_COLS（单处维护，i18n 英文文案不折行）
            cw = {k: w for k, w in self.LT_COLS}
            cells = [
                ft.Container(width=None, expand=True, padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8),
                    content=ft.Text(r["title"], size=13,
                                    color=T["faint"] if done else T["text"],
                                    weight=ft.FontWeight.W_400,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=cw["project"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        r["project"], size=12, color=T["sub"], max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=cw["task_type"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        r["task_type"], size=12, color=T["sub"],
                        max_lines=1, no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=cw["priority"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        dpriority(r["priority"]), size=12,
                        color=T["pr_text"].get(r["priority"], T["sub"]),
                        weight=ft.FontWeight.W_600,
                        text_align=ft.TextAlign.CENTER, max_lines=1,
                        no_wrap=True)),
                ft.Container(width=cw["status"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        dstatus(r["status"]), size=12, color=st_color,
                        text_align=ft.TextAlign.CENTER, max_lines=1,
                        no_wrap=True)),
                ft.Container(width=cw["start_date"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        r["start_date"] or tr("ph_empty"), size=12,
                        color=T["sub"], text_align=ft.TextAlign.CENTER,
                        max_lines=1, no_wrap=True)),
                ft.Container(width=cw["deadline"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        r["deadline"] or tr("ph_empty"), size=12,
                        weight=ft.FontWeight.W_600 if ovd else None,
                        color=dl_color, text_align=ft.TextAlign.CENTER,
                        max_lines=1, no_wrap=True)),
                ft.Container(width=cw["finish_date"], padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8), content=ft.Text(
                        r["finish_date"] or tr("ph_empty"), size=12,
                        color=T["sub"], text_align=ft.TextAlign.CENTER,
                        max_lines=1, no_wrap=True)),
            ]
            body_rows.append(ft.Container(
                bgcolor=T["surface2"] if i % 2 else None,
                border_radius=radius(8),
                on_click=lambda e, rid=r["record_id"]: self._open_detail(rid),
                on_hover=lambda e: self._row_hover(e, T["hover"]),
                content=ft.Row(cells, spacing=0)))
        return ft.Column([header,
                          ft.Column(body_rows, spacing=2, scroll=ft.ScrollMode.AUTO,
                                    expand=True)],
                         spacing=4, expand=True)

    def _ledger_pager(self):
        T = self.T
        rows = getattr(self, "_lt_page_rows", [])
        size = max(1, self.lt_pagesize)
        page_count = max(1, -(-len(rows) // size))
        info = ft.Text(
            (tr("pager_info", n=len(rows), cur=self.lt_page, total=page_count)
             if rows else tr("pager_empty")),
            size=12, color=T["sub"])
        size_dd = ft.Container(
            width=86, height=36,
            content=ft.Dropdown(
                value=str(self.lt_pagesize), dense=True, expand=True,
                text_size=12,
                border_radius=radius(8), border_color=T["border"],
                filled=True, fill_color=T["surface2"],
                content_padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                options=[ft.dropdown.Option(str(v)) for v in (20, 50, 100, 200)],
                on_select=lambda e: self._lt_pagesize(int(e.control.value))),
        )
        return ft.Row([
            info, ft.Container(expand=True),
            ft.Text(tr("pager_size"), size=12, color=T["faint"]), size_dd,
            ft.OutlinedButton(tr("page_prev"), style=self._btn_style(False),
                              on_click=lambda e: self._lt_page(-1)),
            ft.OutlinedButton(tr("page_next"), style=self._btn_style(False),
                              on_click=lambda e: self._lt_page(1)),
        ], spacing=8)

    def _lt_pagesize(self, v):
        self.lt_pagesize = v
        self.lt_page = 1
        self._render_view()

    def _lt_page(self, delta):
        self.lt_page += delta
        self._render_view()

    def _export_csv(self, _e=None):
        import csv
        from tkinter import messagebox, filedialog  # 文件对话框沿用系统弹窗
        rows = getattr(self, "_lt_page_rows", None)
        if rows is None:
            rows = self._ledger_filtered()
        if not rows:
            self._toast(tr("csv_none"), "warn")
            return
        path = filedialog.asksaveasfilename(
            title=tr("csv_dialog_title"), defaultextension=".csv",
            initialfile=f"TaskHub_{taskhub.today_str()}.csv",
            filetypes=[(tr("csv_filetype"), "*.csv"),
                       (tr("csv_all_files"), "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                # 表头随界面语言；行内的状态/类型/优先级/项目仍写中文原值
                # （数据契约不变，英文只作用于显示层）
                writer.writerow([tr("col_title"), tr("col_project"),
                                 tr("col_task_type"), tr("col_priority"),
                                 tr("col_status"), tr("col_start_date"),
                                 tr("col_deadline"), tr("col_finish_date"),
                                 tr("fld_result"), tr("fld_detail_label"),
                                 tr("col_record_id")])
                for r in rows:
                    writer.writerow([r["title"], r["project"], r["task_type"],
                                     r["priority"], r["status"],
                                     r["start_date"], r["deadline"],
                                     r["finish_date"], r["result"],
                                     (r["detail"] or "").replace("\n", " / "),
                                     r["record_id"]])
        except OSError as exc:
            self._toast(tr("csv_fail", err=exc), "err")
            return
        self._toast(tr("csv_ok", n=len(rows)), "ok")

    # ------------------------------------------------------------------
    # 视图 4：月历
    # ------------------------------------------------------------------

    def view_cal(self):
        T = self.T
        title = ft.Container(
            width=130, alignment=ft.Alignment.CENTER,
            content=ft.Text(tr("cal_title", y=self.cal_year,
                               m=month_name(self.cal_month)), size=16,
                            weight=ft.FontWeight.W_600, color=T["text"]))
        legend = ft.Row(spacing=12)
        for kind_key, color in (("cal_legend_deadline", DANGER),
                                ("cal_legend_start", ST_FILL["待办"]),
                                ("cal_legend_finish", ST_FILL["已完成"])):
            legend.controls.append(ft.Row([
                ft.Container(width=8, height=8, border_radius=radius(4),
                             bgcolor=color),
                ft.Container(width=3),
                ft.Text(tr(kind_key), size=12, color=T["sub"]),
            ]))
        header = ft.Row([
            ft.IconButton(icon=icon("chevron_left"), tooltip=tr("cal_prev"),
                          on_click=lambda e: self._cal_shift(-1),
                          icon_color=T["sub"]),
            title,
            ft.IconButton(icon=icon("chevron_right"), tooltip=tr("cal_next"),
                          on_click=lambda e: self._cal_shift(1),
                          icon_color=T["sub"]),
            ft.Container(width=10), legend, ft.Container(expand=True),
            ft.FilledButton(tr("cal_today"), style=self._btn_style(True),
                            on_click=lambda e: self._cal_today()),
        ])

        week_row = ft.Row(spacing=8)
        wd_keys = ("wd_mon", "wd_tue", "wd_wed", "wd_thu", "wd_fri", "wd_sat",
                   "wd_sun")
        for i, d in enumerate([tr(k) for k in wd_keys]):
            week_row.controls.append(ft.Container(
                expand=True, alignment=ft.Alignment.CENTER,
                content=ft.Text(d, size=12, weight=ft.FontWeight.W_600,
                                color=DANGER if i >= 5 else T["sub"])))

        grid = self._cal_grid()
        day_panel = self._cal_day_panel()
        return ft.Column(spacing=8, controls=[
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=header),
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=week_row),
            ft.Container(padding=ft.Padding.symmetric(horizontal=24),
                         content=grid, expand=True),
            ft.Container(padding=ft.Padding.only(left=24, right=24, bottom=12),
                         content=day_panel),
        ])

    def _cal_date_hits(self):
        hits: dict[str, list] = {}
        for r in self.rows:
            for field, kind in (("deadline", "截止"), ("finish_date", "完成"),
                                ("start_date", "开始")):
                d = r[field]
                if not d:
                    continue
                if field == "start_date" and r["status"] != "待办":
                    continue
                hits.setdefault(d, []).append((kind, r))
        return hits

    def _cal_grid(self):
        T = self.T
        hits = self._cal_date_hits()
        today = datetime.date.today()
        first = datetime.date(self.cal_year, self.cal_month, 1)
        offset = first.weekday()
        days_in_month = (datetime.date(
            self.cal_year + (self.cal_month == 12),
            1 if self.cal_month == 12 else self.cal_month + 1, 1)
            - datetime.timedelta(days=1)).day
        prev_end = first - datetime.timedelta(days=1)

        # 只渲染需要的行数：9 月 2026（周二开头 30 天）= 5 行；
        # 个别月份确需 6 行时仍完整展示，不丢日期。
        needed = (offset + days_in_month + 6) // 7
        rows = []
        for row_i in range(needed):
            cells = []
            for col_i in range(7):
                idx = row_i * 7 + col_i
                if idx < offset:
                    dnum, date_obj = prev_end.day - offset + 1 + idx, None
                elif idx - offset < days_in_month:
                    dnum = idx - offset + 1
                    date_obj = datetime.date(self.cal_year, self.cal_month, dnum)
                else:
                    dnum, date_obj = idx - offset + 1 - days_in_month, None
                cells.append(self._cal_cell(dnum, date_obj, hits, today))
            rows.append(ft.Row(spacing=8, controls=cells, expand=True))
        return ft.Column(rows, spacing=8, expand=True)

    def _cal_cell(self, dnum, date_obj, hits, today):
        T = self.T
        muted = date_obj is None
        selected = (date_obj is not None
                    and date_obj.isoformat() == self.cal_sel)
        is_today = date_obj == today
        bg = T["tint"] if selected else T["surface"]
        border_c = T["accent"] if selected else T["border"]
        cell_items: list[ft.Control] = []
        day_hits: list = []
        if date_obj is not None:
            day_hits = hits.get(date_obj.isoformat(), [])
            # 等高插槽：每格恒为 日期行 + 2 个日程槽 + 计数槽，
            # 有无日程格子高度一致；槽位不足用占位补齐。
            for kind, r in day_hits[:2]:
                color = (T["st_text"]["已完成"] if kind == "完成"
                         else T["st_text"].get(r["status"], T["sub"]))
                cell_items.append(ft.Container(
                    height=16, alignment=ft.Alignment.CENTER_LEFT,
                    bgcolor=ft.Colors.with_opacity(0.14, color),
                    border_radius=radius(4),
                    padding=ft.Padding.symmetric(horizontal=4, vertical=1),
                    on_click=lambda e, d=date_obj.isoformat(), rid=r["record_id"]:
                    self._cal_open(d, rid),
                    content=ft.Text(
                        ("· " if kind != "截止" else "! ") + r["title"],
                        size=12, color=color, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS)))
        while len(cell_items) < 2:
            cell_items.append(ft.Container(height=16))
        more_n = len(day_hits) - 2
        cell_items.append(ft.Container(
            height=10, padding=ft.Padding.only(left=4),
            content=ft.Text(tr("cal_more", n=more_n), size=10, color=T["faint"])
            if more_n > 0 else None))
        day_head = ft.Row(spacing=4)
        if is_today:
            day_head.controls.append(ft.Container(
                width=18, height=18, border_radius=radius(R["sm"]), bgcolor=self.T["accent"],
                alignment=ft.Alignment.CENTER,
                content=ft.Text(str(dnum), size=11, color="white",
                                weight=ft.FontWeight.W_600)))
        else:
            day_head.controls.append(ft.Container(
                padding=ft.Padding.only(left=2),
                content=ft.Text(str(dnum), size=12,
                                color=T["faint"] if muted else T["text"],
                                weight=ft.FontWeight.W_600)))
        if date_obj is not None:
            n = len(hits.get(date_obj.isoformat(), []))
            if n:
                day_head.controls.append(ft.Container(expand=True))
                day_head.controls.append(ft.Text(str(n), size=11, color=self.T["accent"],
                                                 weight=ft.FontWeight.W_600))
        return ft.Container(
            expand=True, bgcolor=bg,
            border_radius=radius(8),
            border=ft.Border.all(1, border_c),
            padding=6, on_click=(lambda e, d=date_obj.isoformat():
                                 self._cal_pick(d)) if not muted else None,
            on_hover=(lambda e: self._cell_hover(e, bg)) if not muted else None,
            content=ft.Column([ft.Container(height=18, alignment=ft.Alignment.
                                            CENTER_LEFT, content=day_head)]
                              + cell_items, spacing=4, tight=True))

    def _cell_hover(self, e, base_bg):
        hot = e.data in (True, "true", "True")
        T = self.T
        e.control.bgcolor = T["hover"] if hot else base_bg
        self.page.update()

    def _cal_shift(self, delta):
        m, y = self.cal_month + delta, self.cal_year
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.cal_year, self.cal_month = y, m
        self._render_view()

    def _cal_today(self):
        now = datetime.date.today()
        self.cal_year, self.cal_month = now.year, now.month
        self.cal_sel = now.isoformat()
        self._render_view()

    def _cal_pick(self, dstr):
        self.cal_sel = dstr
        self._render_view()

    def _cal_open(self, dstr, rid):
        self.cal_sel = dstr
        self._open_detail(rid)

    def _cal_day_panel(self):
        T = self.T
        dstr = self.cal_sel
        hits = self._cal_date_hits()
        items = hits.get(dstr, [])
        try:
            d = datetime.date.fromisoformat(dstr)
            wd = weekday_name(d.weekday())
            title = tr("cal_day_title", date=dstr, wd=wd, n=len(items))
        except ValueError:
            title = tr("cal_day_fallback")
        if not items:
            body: ft.Control = ft.Container(
                alignment=ft.Alignment.CENTER, expand=True,
                content=ft.Text(tr("cal_no_task"), size=12,
                                color=T["faint"]))
        else:
            rows = []
            for kind, r in items:
                color = (T["st_text"]["已完成"] if kind == "完成"
                         else T["st_text"].get(r["status"], T["sub"]))
                rows.append(ft.Container(
                    border_radius=radius(8), padding=ft.Padding.symmetric(
                        horizontal=8, vertical=4),
                    on_click=lambda e, rid=r["record_id"]: self._open_detail(rid),
                    on_hover=lambda e: self._row_hover(e, T["hover"]),
                    content=ft.Row([
                        ft.Container(width=3, height=26, border_radius=radius(2),
                                     bgcolor=color),
                        ft.Container(width=8),
                        ft.Text(f"[{tr(CAL_KIND_KEYS[kind])}] {r['title']}",
                                size=12, color=T["text"], expand=True,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"{r['project']} · {dstatus(r['status'])}",
                                size=11, color=T["sub"]),
                    ])))
            body = ft.ListView(expand=True, spacing=4, controls=rows)
        return ft.Container(
            height=164, bgcolor=T["surface"], border_radius=radius(R["lg"]),
            border=ft.Border.all(1, T["border"]),
            padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
            content=ft.Column([
                ft.Text(title, size=13, weight=ft.FontWeight.W_600,
                        color=T["text"]),
                body,
            ], spacing=8))

    # ------------------------------------------------------------------
    # 对话框（居中 + 圆角 + 内容滚动）
    # ------------------------------------------------------------------

    def _show_dlg(self, dlg):
        self._detail_rid = None
        self._detail_open = True
        try:
            self.page.show_dialog(dlg)
        except AttributeError:
            self.page.overlay.append(dlg)
            dlg.open = True
        # AlertDialog 在 window.maximized 同一帧渲染时偶发首帧空白
        # （flet 0.86 已知问题）。立即 update 一次确保 dialog 入栈，
        # 再延迟 80ms update 一次覆盖 maximized 完成后的重排。
        # ⚠️ 延迟必须经 page.run_thread：裸 threading.Timer 线程里调
        # 页面 API 会静默失败（等于从来没生效过）。
        try:
            self.page.update()

            def _late():
                time.sleep(0.08)
                self._safe_update()

            self.page.run_thread(_late)
        except Exception:
            pass

    def _safe_update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def _pop_dlg(self):
        # 精确关闭最顶上的"业务弹窗"（跳过 toast）。
        # 不能用 page.pop_dialog()：它只弹最顶上 open 的对话框，若 toast
        # 恰好在栈顶（toast 与业务弹窗同走 _dialogs 路由栈），会把刚弹出
        # 的 toast 关掉而把业务弹窗留在栈里。
        try:
            toast = getattr(self, "_toast_dlg", None)
            for d in reversed(self.page._dialogs.controls):
                if d.open and d is not toast:
                    d.open = False
                    d.update()
                    break
        except Exception:
            pass
        try:
            self.page.update()
        except Exception:
            pass

    def _toast(self, message, kind="ok"):
        # 统一提示接口：底部悬浮 toast，2.4s 自动消失。
        #
        # 层级修复依据（flet 0.86 Dart 源码 snack_bar.dart / alert_dialog.dart，
        # github.com/flet-dev/flet）：SnackBar 在 Flutter 端永远经
        # ScaffoldMessenger.of(context).showSnackBar() 渲染，挂在与 Navigator
        # （对话框路由栈）之下的 Scaffold 里，必然被 AlertDialog 的遮罩层
        # 压住——无论 Python 端把 SnackBar 塞进 overlay 还是 _dialogs 都
        # 无法改变（Flutter 官方 issue #148198 同因）。
        #
        # 故改用 AlertDialog 充当 toast：它与业务弹窗同走 Navigator 路由栈，
        # 后推入者必然盖在先推入者之上；其遮罩在 Dart 端由对话框内部
        # IgnorePointer+ColoredBox 绘制、颜色完全由 barrier_color 控制，
        # 设为透明即无遮罩；alignment 定位到窗口底部居中，视觉等效 SnackBar。
        colors = {"ok": OK_GREEN, "warn": WARN, "err": DANGER,
                  "info": self.T["accent"]}
        # 连续 toast：先精确关掉上一个未消失的，避免同位置视觉重叠
        old = getattr(self, "_toast_dlg", None)
        if old is not None and getattr(old, "open", False):
            try:
                old.open = False
                old.update()
            except Exception:
                pass
        # v3 动态宽度：视觉宽度估算（中文/全角≈1 字宽=13px、ASCII≈0.55），
        # 文字区最大 320px，超出自动折行（最多 3 行、超出省略号兜底）；
        # 药丸宽度随消息内容自适应，文字上下左右居中（单行/多行一致）。
        vis = sum(1.0 if ord(ch) > 127 else 0.55 for ch in message)
        est_px = vis * 13
        text_max = 320
        lines = min(3, max(1, -(-int(est_px) // text_max)))
        text_w = max(80, min(text_max, -(-int(est_px) // lines)) + 14)
        # 药丸总宽 = 文字区 + 图标18 + 间距×2 + 关闭钮22 + 水平padding 14×2
        pill_w = text_w + 80
        toast = ft.AlertDialog(
            modal=False,
            barrier_color=ft.Colors.TRANSPARENT,
            alignment=ft.Alignment(0, 0.97),
            # 背景色必须挂在内容容器上：Flutter Dialog 源码对 AlertDialog
            # 表面硬编码 minWidth=280，bgcolor 挂表面时短消息最窄 280、无法
            # 贴内容；表面设透明后，可见"药丸"宽度完全由下方 width 决定。
            bgcolor=ft.Colors.TRANSPARENT,
            # 尺寸必须钉死：AlertDialog 的 content 处于 loose 高约束中，
            # 内容含 expand=True 的控件会被拉伸到接近窗口满高（本地 demo
            # 截图实测复现）。显式宽高 + Text 不用 expand。
            # ⚠️ flet 0.86 Row 默认 spacing=10：多子项时必须显式 spacing，
            # 否则默认间隙会把行撑爆、关闭按钮溢出容器（demo 实测复现）。
            content_padding=ft.Padding.all(0),
            content=ft.Container(
                width=pill_w,
                height=46 + 19 * (lines - 1),
                bgcolor=colors.get(kind, self.T["accent"]),
                border_radius=radius(R["md"]),
                padding=ft.Padding.symmetric(horizontal=14, vertical=6),
                alignment=ft.Alignment.CENTER,
                content=ft.Row(
                    [
                        ft.Icon(icon("check_circle") if kind == "ok" else
                                icon("info"), color="white", size=18),
                        ft.Container(
                            width=text_w,
                            alignment=ft.Alignment.CENTER,
                            content=ft.Text(
                                message, color="white", size=13,
                                text_align=ft.TextAlign.CENTER,
                                max_lines=lines,
                                overflow=ft.TextOverflow.ELLIPSIS)),
                        ft.Container(
                            width=22, height=22, border_radius=6,
                            alignment=ft.Alignment.CENTER,
                            # 不直接引用 toast 局部变量（构造表达式内尚未
                            # 赋值）；_toast_dlg 在构造完成后指向本 toast
                            on_click=lambda e: self._close_toast(
                                getattr(self, "_toast_dlg", None)),
                            on_hover=self._toast_close_hover,
                            content=ft.Icon(icon("close"), color="white",
                                            size=14)),
                    ],
                    tight=True,
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER)))
        self._toast_dlg = toast
        try:
            self.page.show_dialog(toast)
        except Exception:
            # 兜底路径（极老版本 flet 无 show_dialog 时退回 overlay）
            try:
                self.page.overlay.append(toast)
                toast.open = True
                toast.update()
            except Exception:
                pass
        try:
            self.page.update()
        except Exception:
            pass
        # 2.4s 后精确关闭本 toast（open=False 触发 Dart 端关闭路由；
        # 随后 dismiss 事件会让 flet 自动把它从 _dialogs 栈移除，无需
        # 手动清理。若用户提前点击 toast 外部关闭，此处 open 已为
        # False，直接跳过。Timer 绑定实例而非 self._toast_dlg，防止
        # 连续 toast 时误关新的那个）。
        import threading as _t
        _t.Timer(2.4, self._close_toast, args=(toast,)).start()

    def _close_toast(self, toast):
        try:
            if toast is not None and getattr(toast, "open", False):
                toast.open = False
                toast.update()
        except Exception:
            pass

    @staticmethod
    def _toast_close_hover(e):
        # toast 关闭钮悬停反馈：白色半透明底
        try:
            hovered = e.data in (True, "true")
            e.control.bgcolor = (ft.Colors.with_opacity(0.25, "#ffffff")
                                 if hovered else ft.Colors.TRANSPARENT)
            e.control.update()
        except Exception:
            pass

    def _labeled_box(self, label, value, value_color=None):
        T = self.T
        return ft.Container(
            expand=True, bgcolor=T["surface2"], border_radius=radius(8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            content=ft.Column([
                ft.Text(label, size=11, color=T["faint"]),
                ft.Text(value or tr("ph_empty"), size=13,
                        weight=ft.FontWeight.W_600,
                        color=value_color or T["text"], max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=1, tight=True))

    def _open_detail(self, rid):
        row = self._row_by_id(rid)
        if row is None:
            return
        self._pop_dlg()
        dlg = self._detail_dialog(rid)
        self._detail_dlg = dlg
        self._show_dlg(dlg)

    def _detail_dialog(self, rid):
        row = self._row_by_id(rid)
        if row is None:
            return None
        T = self.T
        st = row["status"]

        ph = tr("ph_empty")
        chip = ft.PopupMenuButton(
            tooltip=tr("tip_switch_status"),
            content=ft.Container(
                bgcolor=ft.Colors.with_opacity(0.14, ST_FILL[st]),
                border_radius=radius(R["pill"]),
                padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                content=ft.Row([ft.Container(width=8, height=8,
                                             border_radius=radius(4),
                                             bgcolor=ST_FILL[st]),
                                ft.Container(width=5),
                                ft.Text(dstatus(st), size=12,
                                        color=T["st_text"].get(st, T["text"]),
                                        weight=ft.FontWeight.W_600)], tight=True)),
            items=[ft.PopupMenuItem(
                       content=ft.Text(tr("status_to", st=dstatus(s)), size=12),
                       on_click=lambda e, s=s: self._do_status(rid, s))
                   for s in taskhub.VALID_STATUSES if s != st])

        hint = self._deadline_hint(row)
        meta = ft.Row(spacing=8, controls=[
            self._labeled_box(tr("fld_project"), row["project"]),
            self._labeled_box(tr("fld_task_type"), row["task_type"]),
            self._labeled_box(tr("fld_priority"), dpriority(row["priority"]),
                              T["pr_text"].get(row["priority"])),
        ])
        meta2 = ft.Row(spacing=8, controls=[
            self._labeled_box(tr("fld_start_date"), row["start_date"] or ph),
            self._labeled_box(tr("fld_deadline"), row["deadline"] or ph),
            self._labeled_box(tr("fld_finish_date"), row["finish_date"] or ph),
        ])

        body_controls = [
            ft.Row([chip, ft.Container(expand=True),
                    ft.IconButton(icon=icon("close"), icon_size=18,
                                  icon_color=T["faint"],
                                  tooltip=tr("dlg_close_tooltip"),
                                  on_click=lambda e: self._pop_dlg())]),
            ft.Text(row["title"], size=20, weight=ft.FontWeight.W_600,
                    color=T["text"]),
            meta, meta2,
        ]
        if hint:
            body_controls.append(ft.Text(hint[0], size=12, color=hint[1],
                                         weight=ft.FontWeight.W_600))
        if row["result"]:
            body_controls.append(ft.Container(
                bgcolor=ft.Colors.with_opacity(0.10, OK_GREEN),
                border_radius=radius(8), padding=12,
                content=ft.Column([
                    ft.Text(tr("fld_result"), size=11, color=OK_GREEN,
                            weight=ft.FontWeight.W_600),
                    ft.Text(row["result"], size=13, color=T["text"]),
                ], spacing=4)))
        body_controls.append(ft.Container(
            bgcolor=T["surface2"], border_radius=radius(8), padding=12,
            content=ft.Column([
                ft.Text(tr("fld_detail"), size=11, color=T["sub"],
                        weight=ft.FontWeight.W_600),
                ft.Container(height=2),
                ft.Text(row["detail"] or tr("fld_no_detail"), size=13,
                        color=T["text"], selectable=True),
            ], spacing=2)))

        self.var_note = ft.TextField(
            hint_text=tr("note_hint"), text_size=13,
            border_radius=radius(8), border_color=T["border"], filled=True,
            fill_color=T["surface2"], expand=True, dense=True,
            on_submit=lambda e: self._do_note(rid))
        body_controls.append(ft.Row([
            self.var_note,
            ft.FilledButton(tr("btn_add_note"), style=self._btn_style(True),
                            on_click=lambda e: self._do_note(rid)),
        ]))
        body_controls.append(ft.Row([
            ft.OutlinedButton(tr("btn_start"), style=self._btn_style(False),
                              on_click=lambda e: self._do_status(rid, "进行中",
                                                                 confirm=True)),
            ft.OutlinedButton(tr("btn_hold"), style=self._btn_style(False),
                              on_click=lambda e: self._do_status(rid, "已搁置",
                                                                 confirm=True)),
            ft.OutlinedButton(tr("btn_edit"), style=self._btn_style(False),
                              on_click=lambda e: self._dlg_edit(rid)),
            ft.Container(expand=True),
            ft.FilledButton(tr("btn_close"), icon=icon("check"),
                            style=ft.ButtonStyle(
                                shape=ft.StadiumBorder(),
                                padding=ft.Padding.symmetric(
                                    horizontal=16, vertical=16),
                                bgcolor={ft.ControlState.DEFAULT: OK_GREEN},
                                color={ft.ControlState.DEFAULT: "white"},
                                text_style=ft.TextStyle(
                                    size=13, weight=ft.FontWeight.W_600)),
                            on_click=lambda e: self._dlg_close_task(rid)),
            ft.OutlinedButton(tr("btn_delete"), style=ft.ButtonStyle(
                shape=ft.StadiumBorder(),
                padding=ft.Padding.symmetric(horizontal=16, vertical=16),
                bgcolor={ft.ControlState.DEFAULT:
                         ft.Colors.with_opacity(0.10, DANGER)},
                color={ft.ControlState.DEFAULT: DANGER},
                text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600)),
                on_click=lambda e: self._dlg_delete(rid)),
        ], spacing=8))
        body_controls.append(ft.Text(tr("rec_id", rid=row["record_id"]),
                                     size=11, color=T["faint"]))

        # 高度按内容自适应：详情/元数据/结论/备注 + 长度因子，上限 760
        detail_lines = max(1, len((row["detail"] or "").splitlines()))
        est_h = (365 + min(240, detail_lines * 19)
                 + (92 if row["result"] else 0)
                 + (26 if hint else 0))
        # 状态流转提示条（每次构建局部实例；⚠️ 不能由 _show_dlg 事后赋值
        # self._detail_banner——首次打开时该属性尚为 None，会被塞进
        # Column.controls 导致 Flutter 端渲染异常、弹窗整块灰屏，
        # 关闭重开才因引用了上次创建的实例而"自愈"（2026-09-07 实证））
        banner = ft.Container(
            visible=False, border_radius=radius(8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8))
        dlg = ft.AlertDialog(
            modal=False, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            content=ft.Container(
                width=760, height=min(760, max(425, est_h)),
                content=ft.Column([banner] + body_controls,
                                  spacing=12, scroll=ft.ScrollMode.AUTO,
                                  tight=True)),
        )
        return dlg

    def _refresh_detail(self, rid):
        # 状态流转后原地刷新打开中的详情弹窗（不销毁重建，避免闪烁）
        dlg = getattr(self, "_detail_dlg", None)
        if dlg is None or not getattr(self, "_detail_open", False):
            self._open_detail(rid)
            return
        dlg.content = self._detail_dialog(rid).content
        self.page.update()

    def _deadline_hint(self, row):
        T = self.T
        if row["status"] == "已完成":
            return None
        dl = row["deadline"]
        if not dl:
            return (tr("hint_no_deadline"), T["faint"])
        try:
            left = (datetime.date.fromisoformat(dl)
                    - datetime.date.today()).days
        except ValueError:
            return None
        if left < 0:
            return (tr("hint_overdue", n=-left, date=dl), DANGER)
        if left == 0:
            return (tr("hint_due_today", date=dl), WARN)
        if left <= 7:
            return (tr("hint_left", n=left, date=dl), self.T["accent"])
        return (tr("hint_left", n=left, date=dl), T["sub"])

    def _form_field(self, label, control):
        T = self.T
        return ft.Column([
            ft.Text(label, size=12, color=T["sub"],
                    weight=ft.FontWeight.W_600),
            ft.Container(height=2),
            control,
        ], spacing=0, tight=True)

    def _dd(self, values, value, width=None, expand=False, on_change=None,
            menu_height=None):
        T = self.T
        return ft.Dropdown(
            value=value, width=width, expand=expand, text_size=13, dense=True,
            border_radius=radius(8), border_color=T["border"],
            filled=True, fill_color=T["surface2"],
            menu_height=menu_height,
            menu_style=ft.MenuStyle(
                bgcolor=ft.Colors.with_opacity(0.82, T["surface"]),
                elevation=0,
                shape=ft.RoundedRectangleBorder(radius=radius(8)),
                side=ft.BorderSide(1, T["border"])),
            options=[ft.dropdown.Option(v) for v in values],
            on_select=on_change)

    def _tf(self, value="", hint="", multiline=False, expand=False,
            readonly=False, on_submit=None, width=None,
            min_lines=None, max_lines=None):
        T = self.T
        kw = dict(value=value, hint_text=hint, text_size=13, dense=True,
                  border_radius=radius(8), border_color=T["border"],
                  filled=True, fill_color=T["surface2"], expand=expand,
                  read_only=readonly, cursor_color=self.T["accent"])
        if width:
            kw["width"] = width
        if multiline:
            kw.update(min_lines=min_lines or 3, max_lines=max_lines or 7,
                      multiline=True)
        if on_submit:
            kw["on_submit"] = on_submit
        return ft.TextField(**kw)

    def _dlg_add(self, status: str = "待办"):
        T = self.T
        # 弹窗内容固定宽 600：单字段 600、行内三等分 193、两等分 295。
        # 定宽绕开 Flet 0.86 弹性布局在 AlertDialog 内的渲染错乱。
        f_title = self._tf(hint=tr("new_title_hint"), width=600)
        f_proj = self._dd(self._options_for("proj", "其他"), "其他", width=193,
                          menu_height=225)
        f_type = self._dd(self._options_for("type", "日常事务"), "日常事务",
                          width=193, menu_height=225)
        f_proj.on_select = lambda e: self._on_dict_change("proj", f_proj, e)
        f_type.on_select = lambda e: self._on_dict_change("type", f_type, e)
        f_pri = self._dd(taskhub.VALID_PRIORITIES, "中", width=193)
        f_start = self._tf(taskhub.today_str(), tr("new_start_hint"), width=193)
        f_dl = self._tf("", tr("new_deadline_hint"), width=193)
        f_src = self._tf("", tr("new_source_hint"), width=193)
        f_detail = self._tf("", tr("new_detail_hint"), multiline=True,
                            width=600, min_lines=8, max_lines=12)

        def save(_e=None):
            title = (f_title.value or "").strip()
            if not title:
                self._toast(tr("toast_title_required"), "warn")
                return
            data = {"title": title, "project": (f_proj.value if f_proj.value
                    != self._sentinel("proj") else "其他"),
                    "task_type": (f_type.value if f_type.value
                                  != self._sentinel("type") else "日常事务"),
                    "priority": f_pri.value,
                    "start": (f_start.value or "").strip(),
                    "deadline": (f_dl.value or "").strip(),
                    "detail": (f_detail.value or "").strip(),
                    "source": (f_src.value or "").strip()}
            try:
                conn = taskhub.open_db()
                try:
                    res = taskhub.add_task(
                        conn, title=data["title"], project=data["project"],
                        task_type=data["task_type"], priority=data["priority"],
                        start=data["start"], deadline=data["deadline"],
                        detail=data["detail"], source=data["source"])
                    if res["action"] == "created" and status != "待办":
                        taskhub.update_task(conn, res["record_id"], "",
                                            status, None, None, None, None, None)
                finally:
                    conn.close()
            except (taskhub.UsageError, taskhub.RunError) as exc:
                self._toast(str(exc), "err")
                return
            self._pop_dlg()
            if res["action"] == "created":
                self.load_rows(render=False)
                self._render_view()
                self._open_detail(res["record_id"])
                self._toast(tr("toast_task_created", title=res["title"][:18]),
                            "ok")
            else:
                self._toast(res.get("reason", tr("toast_duplicate_skipped")),
                            "warn")

        dlg = ft.AlertDialog(
            modal=False, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr("dlg_new_task"), size=16,
                          weight=ft.FontWeight.W_600, color=T["text"]),
            content=ft.Container(
                width=600,
                content=ft.Column([
                    self._form_field(tr("fld_title_req"), f_title),
                    ft.Row([self._form_field(tr("fld_project"), f_proj),
                            self._form_field(tr("fld_task_type"), f_type),
                            self._form_field(tr("fld_priority"), f_pri)],
                           spacing=8),
                    ft.Row([self._form_field(tr("fld_start_date"), f_start),
                            self._form_field(tr("fld_deadline"), f_dl),
                            self._form_field(tr("fld_source"), f_src)],
                           spacing=8),
                    self._form_field(tr("fld_detail_label"), f_detail),
                ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO,
                   height=440)),
            actions=[
                ft.OutlinedButton(tr("btn_cancel"), style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("btn_create"), icon=icon("check"),
                                style=self._btn_style(True), on_click=save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dlg(dlg)

    def _dlg_edit(self, rid):
        row = self._row_by_id(rid)
        if row is None:
            return
        self._pop_dlg()
        T = self.T
        f_title = self._tf(row["title"], readonly=True, width=600)
        f_proj = self._dd(self._options_for("proj", row["project"]),
                          row["project"], width=295, menu_height=225)
        f_type = self._dd(self._options_for("type", row["task_type"]),
                          row["task_type"], width=295, menu_height=225)
        f_proj.on_select = lambda e: self._on_dict_change("proj", f_proj, e)
        f_type.on_select = lambda e: self._on_dict_change("type", f_type, e)
        f_pri = self._dd(taskhub.VALID_PRIORITIES, row["priority"], width=295)
        f_status = self._dd(taskhub.VALID_STATUSES, row["status"], width=295)
        f_dl = self._tf(row["deadline"] or "", tr("edit_deadline_hint"),
                        width=295)
        f_result = self._tf(row["result"] or "", tr("edit_result_hint"),
                            width=295)

        def save(_e=None):
            def blank_to_none(v):
                v = (v or "").strip()
                return v if v else None
            d = {"project": (f_proj.value if f_proj.value
                             != self._sentinel("proj") else row["project"]),
                 "task_type": (f_type.value if f_type.value
                               != self._sentinel("type") else row["task_type"]),
                 "priority": f_pri.value, "status": f_status.value,
                 "deadline": blank_to_none(f_dl.value),
                 "result": blank_to_none(f_result.value)}

            def _apply(conn):
                taskhub.update_task(
                    conn, ref=rid, title="", status=d["status"],
                    priority=d["priority"], deadline=d["deadline"],
                    project=d["project"], result=d["result"], note=None,
                    task_type=d["task_type"])
            if not self._run_write(_apply, "toast_saved", rid, notify=False):
                return
            self._pop_dlg()
            self.load_rows(render=False)
            self._render_view()
            self._open_detail(rid)
            if getattr(self, "_pending", None):
                msg, kd = self._pending
                self._pending = None
                self._toast(msg, kd)

        dlg = ft.AlertDialog(
            modal=True, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr("dlg_edit_task"), size=16,
                          weight=ft.FontWeight.W_600, color=T["text"]),
            content=ft.Container(
                width=600,
                content=ft.Column([
                    self._form_field(tr("edit_title_fixed"), f_title),
                    ft.Row([self._form_field(tr("fld_project"), f_proj),
                            self._form_field(tr("fld_task_type"), f_type)],
                           spacing=8),
                    ft.Row([self._form_field(tr("fld_priority"), f_pri),
                            self._form_field(tr("col_status"), f_status)],
                           spacing=8),
                    ft.Row([self._form_field(tr("fld_deadline"), f_dl),
                            self._form_field(tr("fld_result"), f_result)],
                           spacing=8),
                    ft.Text(tr("edit_incremental_note"), size=12,
                            color=T["faint"]),
                ], spacing=12, tight=True)),
            actions=[
                ft.OutlinedButton(tr("btn_cancel"), style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("btn_save"), icon=icon("save"),
                                style=self._btn_style(True), on_click=save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dlg(dlg)

    def _dlg_close_task(self, rid):
        row = self._row_by_id(rid)
        if row is None:
            return
        if row["status"] == "已完成":
            self._toast(tr("toast_already_done"), "info")
            return
        self._pop_dlg()
        T = self.T
        f_result = self._tf("", tr("close_result_hint"), width=560)
        f_date = self._tf(taskhub.today_str(), tr("new_start_hint"),
                          width=560)

        def save(_e=None):
            result = (f_result.value or "").strip()
            if not result:
                self._toast(tr("toast_result_required"), "warn")
                return
            finish = (f_date.value or "").strip() or taskhub.today_str()

            def _apply(conn):
                taskhub.close_task(conn, rid, "", result, finish)
            if not self._run_write(_apply, "toast_task_closed", rid):
                return
            self._pop_dlg()
            self.load_rows(render=False)
            self._render_view()
            self._open_detail(rid)

        dlg = ft.AlertDialog(
            modal=True, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr("dlg_finish_task"), size=16,
                          weight=ft.FontWeight.W_600, color=T["text"]),
            content=ft.Container(width=560, content=ft.Column([
                ft.Text(row["title"], size=13, color=T["text"], max_lines=2),
                ft.Container(height=6),
                self._form_field(tr("fld_result_req"), f_result),
                self._form_field(tr("fld_finish_default"), f_date),
            ], spacing=12, tight=True)),
            actions=[
                ft.OutlinedButton(tr("btn_cancel"), style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("btn_confirm_finish"), icon=icon("check_circle"),
                                style=ft.ButtonStyle(
                                    shape=ft.StadiumBorder(),
                                    padding=ft.Padding.symmetric(
                                        horizontal=16, vertical=16),
                                    bgcolor={ft.ControlState.DEFAULT: OK_GREEN},
                                    color={ft.ControlState.DEFAULT: "white"},
                                    text_style=ft.TextStyle(
                                        size=13, weight=ft.FontWeight.W_600)),
                                on_click=save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dlg(dlg)

    def _dlg_delete(self, rid):
        row = self._row_by_id(rid)
        if row is None:
            return
        self._pop_dlg()
        T = self.T
        rid_ = rid

        def do_delete(_e=None):
            def _apply(conn):
                conn.execute("DELETE FROM tasks WHERE record_id = ?",
                             (rid_,))
                conn.commit()
            # 先销毁删除确认弹窗：执行结果 toast 延迟入栈后即顶层
            self._pop_dlg()
            if not self._run_write(_apply, "toast_task_deleted", None):
                return
            self.load_rows(render=False)
            self._render_view()

        dlg = ft.AlertDialog(
            modal=True, bgcolor=T["surface"],
            shape=ft.RoundedRectangleBorder(radius=20),
            title=ft.Text(tr("dlg_delete_task"), size=16,
                          weight=ft.FontWeight.W_600, color=DANGER),
            content=ft.Container(width=480, content=ft.Column([
                ft.Text(tr("delete_confirm", title=row["title"]), size=13,
                        color=T["text"]),
                ft.Text(tr("delete_warning"), size=12, color=T["sub"]),
            ], tight=True)),
            actions=[
                ft.OutlinedButton(tr("btn_cancel"), style=self._btn_style(False),
                                  on_click=lambda e: self._pop_dlg()),
                ft.FilledButton(tr("btn_confirm_delete"),
                                icon=icon("delete_outline"),
                                style=ft.ButtonStyle(
                                    shape=ft.StadiumBorder(),
                                    padding=ft.Padding.symmetric(
                                        horizontal=16, vertical=16),
                                    bgcolor={ft.ControlState.DEFAULT: DANGER},
                                    color={ft.ControlState.DEFAULT: "white"},
                                    text_style=ft.TextStyle(
                                        size=13, weight=ft.FontWeight.W_600)),
                                on_click=do_delete),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dlg(dlg)

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def _run_write(self, fn, ok_msg, rid=None, notify=True):
        try:
            conn = taskhub.open_db()
            try:
                fn(conn)
            finally:
                conn.close()
        except (taskhub.UsageError, taskhub.RunError) as exc:
            self._toast(tr("toast_op_failed", err=exc), "err")
            return False
        except Exception as exc:  # noqa: BLE001 —— 兜底避免静默失败
            self._toast(tr("toast_op_failed", err=exc), "err")
            return False
        if rid and getattr(self, "var_note", None) is not None:
            pass
        if notify:
            self._toast(ok_msg, "ok")
        self._pending = (ok_msg, "ok") if not notify else None
        return True

    def _do_note(self, rid):
        note = (getattr(self, "var_note", None) and self.var_note.value or "").strip()
        if not note:
            self._toast(tr("toast_note_empty"), "info")
            return

        def _apply(conn):
            taskhub.update_task(conn, rid, "", None, None, None, None,
                                None, note)
        if not self._run_write(_apply, "toast_note_added", rid):
            return
        self.load_rows(render=False)
        if self.view == "cal":
            self._cal_sel_keep()
        self._open_detail(rid)

    def _cal_sel_keep(self):
        self._render_view()

    def _do_status(self, rid, new_status, confirm=False):
        row = self._row_by_id(rid)
        if row is None:
            return
        if row["status"] == new_status:
            self._toast(tr("toast_already_status", st=dstatus(new_status)),
                        "info")
            return

        def _apply(conn):
            taskhub.update_task(conn, rid, "", new_status, None, None,
                                None, None, None)
        # 提示语含动态状态名：先翻译再传入（_run_write 对非键文案原样输出）
        if not self._run_write(
                _apply, tr("toast_status_updated", st=dstatus(new_status)),
                rid, notify=False):
            return
        self.load_rows(render=False)
        self._render_view()
        if getattr(self, "_detail_open", False):
            self._refresh_detail(rid)
        else:
            self._open_detail(rid)
        if getattr(self, "_pending", None):
            msg, kd = self._pending
            self._pending = None
            self._toast(msg, kd)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = ""
    if "--smoke" in argv:
        idx = argv.index("--smoke")
        smoke = argv[idx + 1] if len(argv) > idx + 1 else "dash"
        smoke = {"dash": "dash", "board": "board", "ledger": "ledger",
                 "cal": "cal"}.get(smoke, "dash")

    # 默认 Flet 原生桌面客户端（flet.exe 窗口）；--web 回退浏览器模式。
    # 桌面客户端已实机验证：真实用户会话中渲染正常。
    view = (ft.AppView.WEB_BROWSER if "--web" in argv
            else ft.AppView.FLET_APP)

    def session(page: "ft.Page"):
        app = TaskHubFlet(page, smoke_view=smoke)
        if smoke:
            app.set_view({"dash": "dash", "board": "board",
                          "ledger": "ledger", "cal": "cal"}.get(smoke, "dash"))

    runner = getattr(ft, "run", None) or ft.app
    runner(session, view=view)
    return 0


if __name__ == "__main__":
    sys.exit(main())
