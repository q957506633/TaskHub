#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""i18n.py —— TaskHub GUI 双语文案层（中文 / English）。

设计要点
--------
1. **只翻译「显示层」**：数据库里存的值（状态 待办/进行中/已搁置/已完成、
   任务类型 客诉处理/…、优先级 高/中/低、项目 M006(YL055)/…）一律不改。
   英文模式下通过 `dstatus / dtype / dpriority / dproject` 做**显示映射**，
   筛选、写入、排序、CLI 输出仍使用中文原值——CLI 输出契约不受影响。
2. **语言偏好持久化在 JSON 文件**（不改数据库 schema）：
   `<应用基准目录>/data/lang.json`，形如 `{"lang": "zh"}`。
   读/写全部 try/except 兜底，文件缺失或损坏时回落中文。
3. **缺失键不抛异常**：`tr()` 依次尝试 当前语言 → 中文 → `default` → 键名本身。

对外 API
--------
    tr(key, lang=None, default=None, **kw) -> str   # 文案取词（支持 str.format）
    set_lang(v) -> str                              # 切换并持久化语言
    get_lang() -> str                               # 当前语言（"zh" / "en"）
    load_lang() -> str                              # 从 lang.json 重新载入
    lang_path() -> str                              # lang.json 绝对路径
    dstatus(v, lang=None) -> str                    # 状态显示值
    dtype(v, lang=None) -> str                      # 任务类型显示值
    dpriority(v, lang=None) -> str                  # 优先级显示值
    dproject(v, lang=None) -> str                   # 项目显示值（不翻译）
    dfilter(v, lang=None) -> str                    # 筛选项显示值（全部/未完结/…）
    month_name(m, lang=None) -> str                 # 月份名
    weekday_name(idx, lang=None) -> str             # 星期名（idx=0 表示周一）
    missing_keys() -> dict                          # 自检：各语言缺失的键
"""

from __future__ import annotations

import json
import os

__all__ = [
    "LANGS", "DEFAULT_LANG", "STRINGS",
    "STATUS_DISPLAY", "PRIORITY_DISPLAY", "FILTER_DISPLAY",
    "tr", "set_lang", "get_lang", "load_lang", "lang_path",
    "dstatus", "dpriority", "dproject", "dfilter",
    "month_name", "weekday_name", "missing_keys",
]

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"

_HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 文案字典：语义化英文键名 → zh / en 文案
# 约定：占位符使用 str.format 语法（{name}）；两份字典的键必须一一对应。
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    "zh": {
        # ---- 应用壳层 / 侧栏 / 顶栏 -------------------------------------
        "app_title": "工作任务跟踪台 · TaskHub",
        "brand_name": "任务中枢",
        "brand_logo": "任",
        "workspace": "工作区",
        "nav_dashboard": "仪表盘",
        "nav_board": "任务看板",
        "nav_ledger": "任务台账",
        "nav_calendar": "日程月历",
        "view_dashboard": "综述仪表盘",
        "view_board": "任务看板",
        "view_ledger": "任务台账",
        "view_calendar": "日程月历",
        "tip_theme": "切换亮/暗主题",
        "tip_refresh": "刷新 (读取最新数据)",
        "tip_language": "切换中文 / English",
        "search_hint": "搜索任务名称 / 详情",
        "btn_new_task": "新增任务",
        "btn_refresh": "刷新",
        "lang_switch_to": "EN",
        "stat_left": "共 {total} 条任务 · 未完结 {open} 条 · 逾期 {overdue} 条",
        "stat_right": "数据库 {db} · 更新于 {time}",
        "nav_stat": "未完结 {open} 项 · 逾期 {overdue} 项\n共 {total} 项任务",

        # ---- 仪表盘 ------------------------------------------------------
        "kpi_overdue": "逾期未完成",
        "kpi_today": "今日到期",
        "kpi_doing": "进行中",
        "kpi_todo": "待办",
        "kpi_month": "本月完成",
        "dash_status_dist": "状态分布",
        "dash_status_hint": "点击图例下钻台账",
        "dash_all_tasks": "全部任务",
        "dash_project_dist": "项目分布",
        "dash_type_dist": "任务类型分布",
        "dash_bar_hint": "按任务数",
        "dash_no_data": "暂无数据",
        "dash_empty_value": "（空）",
        "dash_focus_title": "近期关注",
        "dash_focus_count": "{n} 项",
        "dash_focus_sub": "逾期 / 今日到期 / 7 天内到期，点击可直接处理",
        "dash_focus_none1": "近期没有逾期或临期任务",
        "dash_focus_none2": "节奏保持得不错",
        "tag_overdue": "逾期",
        "tag_today": "今天",
        "tag_soon": "临近",
        "focus_overdue": "逾期 {n} 天 · 截止 {date}",
        "focus_today": "今日到期 · {date}",
        "focus_soon": "还剩 {n} 天 · 截止 {date}",

        # ---- 筛选区 ------------------------------------------------------
        "flt_status": "状态",
        "flt_project": "项目",
        "flt_type": "类型",
        "flt_priority": "优先级",
        "flt_quick": "快捷",
        "flt_keyword": "关键字",
        "flt_only_overdue": "仅看逾期",
        "flt_clear": "清除",
        "flt_clear_filters": "清除筛选",
        "flt_sort": "排序",
        "flt_all": "全部",
        "status_open": "未完结",
        "quick_overdue": "逾期",
        "quick_today": "今日到期",
        "quick_7d": "7天内到期",
        "quick_month": "本月完成",
        "sort_created_at": "录入时间",
        "sort_deadline": "截止日期",
        "sort_priority": "优先级",
        "sort_status": "状态",
        "sort_title": "任务名称",
        "sort_project": "所属项目",
        "sort_start_date": "开始日期",
        "sort_finish_date": "完成日期",

        # ---- 台账表头 / 分页 ---------------------------------------------
        "col_title": "任务名称",
        "col_project": "所属项目",
        "col_task_type": "任务类型",
        "col_priority": "优先级",
        "col_status": "状态",
        "col_start_date": "开始日期",
        "col_deadline": "截止日期",
        "col_finish_date": "完成日期",
        "col_record_id": "记录ID",
        "btn_asc": "↑ 升序",
        "btn_desc": "↓ 降序",
        "btn_export_csv": "导出 CSV",
        "ledger_empty1": "没有符合当前筛选的任务",
        "ledger_empty2": "可调整筛选条件，或点击「清除」重置",
        "pager_info": "共 {n} 条 · 第 {cur}/{total} 页",
        "pager_empty": "没有符合当前筛选的任务",
        "pager_size": "条/页",
        "page_prev": "‹ 上一页",
        "page_next": "下一页 ›",

        # ---- 导出 CSV ----------------------------------------------------
        "csv_dialog_title": "导出为 CSV",
        "csv_filetype": "CSV 文件",
        "csv_all_files": "所有文件",
        "csv_none": "当前筛选结果为空，无可导出数据",
        "csv_fail": "导出失败：{err}",
        "csv_ok": "已导出 {n} 条到 CSV",

        # ---- 看板 --------------------------------------------------------
        "board_done_more": "仅显示最近 {limit} 条 · 还有 {n} 条已完成",
        "board_empty1": "暂无任务",
        "board_empty2": "点右上角「{new}」创建",
        "board_new_in": "在「{st}」新建",
        "tile_done_on": "完成于 {date}",
        "tile_no_deadline": "无截止日期",
        "tile_overdue": "逾期 {n} 天 · {date}",
        "tile_left": "剩 {n} 天 · {date}",

        # ---- 月历 --------------------------------------------------------
        "cal_title": "{y} 年 {m} 月",
        "cal_legend_deadline": "截止",
        "cal_legend_start": "开始",
        "cal_legend_finish": "完成",
        "cal_prev": "上月",
        "cal_next": "下月",
        "cal_today": "回到今天",
        "wd_mon": "周一", "wd_tue": "周二", "wd_wed": "周三", "wd_thu": "周四",
        "wd_fri": "周五", "wd_sat": "周六", "wd_sun": "周日",
        "cal_more": "还有 {n} 项…",
        "cal_day_title": "{date}（周{wd}）· {n} 项",
        "cal_day_fallback": "当日任务",
        "cal_no_task": "当天没有任务安排",

        # ---- 详情弹窗 ----------------------------------------------------
        "tip_switch_status": "点击切换状态",
        "status_to": "状态 → {st}",
        "dlg_close_tooltip": "关闭 (Esc)",
        "fld_project": "所属项目",
        "fld_task_type": "任务类型",
        "fld_priority": "优先级",
        "fld_start_date": "开始日期",
        "fld_deadline": "截止日期",
        "fld_finish_date": "完成日期",
        "fld_result": "结果结论",
        "fld_detail": "任务详情 / 进度备注",
        "fld_no_detail": "（无详情）",
        "btn_start": "开始",
        "btn_hold": "搁置",
        "btn_edit": "编辑",
        "btn_close": "完成关闭",
        "btn_delete": "删除",
        "rec_id": "记录 ID：{rid}",
        "note_hint": "追加进度备注（回车或点按钮，不覆盖历史）",
        "btn_add_note": "追加进度",
        "hint_no_deadline": "未设置截止日期，建议补充以便排序与提醒",
        "hint_overdue": "已逾期 {n} 天（截止 {date}），建议尽快处理或调整截止日期",
        "hint_due_today": "今天到期（{date}）",
        "hint_left": "距截止还有 {n} 天（{date}）",

        # ---- 新建 / 编辑 / 完成 / 删除 弹窗 ------------------------------
        "dlg_new_task": "新建任务",
        "dlg_edit_task": "编辑任务",
        "dlg_finish_task": "完成任务",
        "dlg_delete_task": "删除任务",
        "new_title_hint": "任务名称（必填，同名未完结会自动查重跳过）",
        "new_start_hint": "YYYY-MM-DD（默认今天）",
        "new_deadline_hint": "YYYY-MM-DD（可空）",
        "new_source_hint": "可选，写入详情首行 [来源:xxx]",
        "new_detail_hint": "任务详情（可空）",
        "fld_title_req": "任务名称 *",
        "fld_source": "来源标记",
        "fld_detail_label": "任务详情",
        "edit_title_fixed": "任务名称（业务主键，暂不支持改名）",
        "edit_deadline_hint": "YYYY-MM-DD（留空表示不修改）",
        "edit_result_hint": "结果结论（留空表示不修改）",
        "edit_incremental_note": "按字段增量保存，进度备注不会被覆盖",

        # ---- 任务类型（数据库托管，用户自定义，不做中英文映射） --------
        "manage_type_sentinel": "➕ 管理任务类型",
        "manage_type_title": "管理任务类型",
        "manage_type_list_hint": "数据库托管，可自由增删；已使用的类型删除后历史任务仍保留其文本",
        "manage_type_new_hint": "输入新任务类型名称",
        "manage_type_delete": "删除该类型",
        "toast_type_name_required": "任务类型名称不能为空",
        "toast_type_added": "已新增任务类型「{name}」",
        "toast_type_deleted": "已删除任务类型「{name}」",

        # ---- 所属项目（数据库托管，用户自定义，不做中英文映射） --------
        "manage_proj_sentinel": "➕ 管理所属项目",
        "manage_proj_title": "管理所属项目",
        "add_proj_btn": "新增项目",
        "add_type_btn": "新增任务类型",
        "manage_proj_list_hint": "数据库托管，可自由增删；已使用的项目删除后历史任务仍保留其文本",
        "manage_proj_new_hint": "输入新所属项目名称",
        "manage_proj_delete": "删除该项目",
        "toast_proj_name_required": "所属项目名称不能为空",
        "toast_proj_added": "已新增所属项目「{name}」",
        "toast_proj_deleted": "已删除所属项目「{name}」",
        "close_result_hint": "结果结论（必填，与 CLI close --result 规则一致）",
        "fld_result_req": "结果结论 *",
        "fld_finish_default": "完成日期（默认今天）",
        "delete_confirm": "确认删除任务「{title}」？",
        "delete_warning": "删除后不可恢复（CLI 无此能力，GUI 专属操作）",
        "btn_cancel": "取消",
        "btn_add": "新增",
        "btn_close_dlg": "关闭",
        "btn_create": "创建任务",
        "btn_save": "保存修改",
        "btn_confirm_finish": "确认完成",
        "btn_confirm_delete": "删除",

        # ---- Toast 提示 --------------------------------------------------
        "toast_title_required": "任务名称不能为空",
        "toast_task_created": "已新增任务「{title}」",
        "toast_duplicate_skipped": "同名未完结任务已存在，已跳过",
        "toast_saved": "修改已保存",
        "toast_already_done": "该任务已完成，无需再次关闭",
        "toast_result_required": "结果结论必填",
        "toast_op_failed": "操作失败：{err}",
        "toast_note_empty": "请输入进度备注内容",
        "toast_note_added": "进度备注已追加",
        "toast_already_status": "任务已是「{st}」",
        "toast_status_updated": "状态已更新为「{st}」",
        "toast_task_closed": "任务已关闭",
        "toast_task_deleted": "任务已删除",
        "toast_lang_switched": "界面语言已切换",

        # ---- 通用 --------------------------------------------------------
        "ph_empty": "—",
        "app_rail": "应用启动器",
        "app_no_apps_yet": "暂无应用",
        "app_btn_add": "添加应用",
        "app_field_name": "名称",
        "app_field_path": "可执行路径",
        "app_field_args": "启动参数（可选）",
        "app_field_icon": "图标路径（可选）",
        "app_btn_pick_file": "选择文件…",
        "app_btn_pick_icon": "选择图标…",
        "app_btn_save": "保存",
        "app_btn_launch": "启动",
        "app_btn_edit": "编辑",
        "app_btn_delete": "删除",
        "app_btn_move_up": "上移",
        "app_btn_move_down": "下移",
        "app_title_add": "添加应用",
        "app_title_edit": "编辑应用",
        "app_confirm_delete": "确认删除应用「{name}」？",
        "app_toast_added": "已添加「{name}」",
        "app_toast_updated": "已更新「{name}」",
        "app_toast_deleted": "已删除「{name}」",
        "app_toast_moved_up": "已上移「{name}」",
        "app_toast_moved_down": "已下移「{name}」",
        "app_launch_ok": "已启动「{name}」",
        "app_launch_failed": "启动失败：{err}",
        "app_path_required": "可执行路径必填",
        "app_name_required": "名称必填",
        "app_tip_add": "添加桌面应用",

    },

    "en": {
        # ---- App shell / sidebar / topbar --------------------------------
        "app_title": "Task Tracker · TaskHub",
        "brand_name": "Task Hub",
        "brand_logo": "T",
        "workspace": "WORKSPACE",
        "nav_dashboard": "Dashboard",
        "nav_board": "Kanban",
        "nav_ledger": "Ledger",
        "nav_calendar": "Calendar",
        "view_dashboard": "Dashboard",
        "view_board": "Kanban Board",
        "view_ledger": "Task Ledger",
        "view_calendar": "Monthly Calendar",
        "tip_theme": "Toggle light / dark theme",
        "tip_refresh": "Refresh (reload latest data)",
        "tip_language": "Switch 中文 / English",
        "search_hint": "Search title / details",
        "btn_new_task": "New Task",
        "btn_refresh": "Refresh",
        "lang_switch_to": "中",
        "stat_left": "{total} tasks · {open} open · {overdue} overdue",
        "stat_right": "DB {db} · updated {time}",
        "nav_stat": "{open} open · {overdue} overdue\n{total} tasks in total",

        # ---- Dashboard ---------------------------------------------------
        "kpi_overdue": "Overdue",
        "kpi_today": "Due Today",
        "kpi_doing": "In Progress",
        "kpi_todo": "Pending",
        "kpi_month": "Done This Month",
        "dash_status_dist": "Status Breakdown",
        "dash_status_hint": "Click a legend item to drill down",
        "dash_all_tasks": "All Tasks",
        "dash_project_dist": "By Project",
        "dash_type_dist": "By Task Type",
        "dash_bar_hint": "by task count",
        "dash_no_data": "No data",
        "dash_empty_value": "(empty)",
        "dash_focus_title": "Needs Attention",
        "dash_focus_count": "{n}",
        "dash_focus_sub": "Overdue / due today / due within 7 days — click to act",
        "dash_focus_none1": "No overdue or upcoming tasks",
        "dash_focus_none2": "Nicely on track",
        "tag_overdue": "Overdue",
        "tag_today": "Today",
        "tag_soon": "Soon",
        "focus_overdue": "{n}d overdue · due {date}",
        "focus_today": "Due today · {date}",
        "focus_soon": "{n}d left · due {date}",

        # ---- Filters -----------------------------------------------------
        "flt_status": "Status",
        "flt_project": "Project",
        "flt_type": "Type",
        "flt_priority": "Priority",
        "flt_quick": "Quick",
        "flt_keyword": "Keyword",
        "flt_only_overdue": "Overdue only",
        "flt_clear": "Clear",
        "flt_clear_filters": "Clear filters",
        "flt_sort": "Sort by",
        "flt_all": "All",
        "status_open": "Open",
        "quick_overdue": "Overdue",
        "quick_today": "Due today",
        "quick_7d": "Due in 7 days",
        "quick_month": "Done this month",
        "sort_created_at": "Created",
        "sort_deadline": "Deadline",
        "sort_priority": "Priority",
        "sort_status": "Status",
        "sort_title": "Title",
        "sort_project": "Project",
        "sort_start_date": "Start date",
        "sort_finish_date": "Finish date",

        # ---- Ledger columns / pager --------------------------------------
        "col_title": "Title",
        "col_project": "Project",
        "col_task_type": "Task Type",
        "col_priority": "Priority",
        "col_status": "Status",
        "col_start_date": "Start",
        "col_deadline": "Deadline",
        "col_finish_date": "Finished",
        "col_record_id": "Record ID",
        "btn_asc": "↑ Asc",
        "btn_desc": "↓ Desc",
        "btn_export_csv": "Export CSV",
        "ledger_empty1": "No tasks match the current filters",
        "ledger_empty2": "Adjust the filters, or click Clear to reset",
        "pager_info": "{n} tasks · page {cur}/{total}",
        "pager_empty": "No tasks match the current filters",
        "pager_size": "per page",
        "page_prev": "‹ Prev",
        "page_next": "Next ›",

        # ---- Export CSV ---------------------------------------------------
        "csv_dialog_title": "Export as CSV",
        "csv_filetype": "CSV files",
        "csv_all_files": "All files",
        "csv_none": "Nothing to export — the current filter returns no rows",
        "csv_fail": "Export failed: {err}",
        "csv_ok": "Exported {n} rows to CSV",

        # ---- Kanban -------------------------------------------------------
        "board_done_more": "Latest {limit} shown · {n} more completed",
        "board_empty1": "No tasks",
        "board_empty2": 'Click "{new}" at the top right',
        "board_new_in": 'New in "{st}"',
        "tile_done_on": "Done {date}",
        "tile_no_deadline": "No deadline",
        "tile_overdue": "{n}d overdue · {date}",
        "tile_left": "{n}d left · {date}",

        # ---- Calendar -----------------------------------------------------
        "cal_title": "{m} {y}",
        "cal_legend_deadline": "Deadline",
        "cal_legend_start": "Start",
        "cal_legend_finish": "Done",
        "cal_prev": "Previous month",
        "cal_next": "Next month",
        "cal_today": "Back to today",
        "wd_mon": "Mon", "wd_tue": "Tue", "wd_wed": "Wed", "wd_thu": "Thu",
        "wd_fri": "Fri", "wd_sat": "Sat", "wd_sun": "Sun",
        "cal_more": "{n} more…",
        "cal_day_title": "{date} ({wd}) · {n} items",
        "cal_day_fallback": "Selected day",
        "cal_no_task": "Nothing scheduled for this day",

        # ---- Detail dialog ------------------------------------------------
        "tip_switch_status": "Click to change status",
        "status_to": "Status → {st}",
        "dlg_close_tooltip": "Close (Esc)",
        "fld_project": "Project",
        "fld_task_type": "Task Type",
        "fld_priority": "Priority",
        "fld_start_date": "Start Date",
        "fld_deadline": "Deadline",
        "fld_finish_date": "Finish Date",
        "fld_result": "Result",
        "fld_detail": "Details / Progress Notes",
        "fld_no_detail": "(no details)",
        "btn_start": "Start",
        "btn_hold": "Hold",
        "btn_edit": "Edit",
        "btn_close": "Complete",
        "btn_delete": "Delete",
        "rec_id": "Record ID: {rid}",
        "note_hint": "Add a progress note (Enter or click; history is preserved)",
        "btn_add_note": "Add Note",
        "hint_no_deadline": "No deadline set — add one for sorting and reminders",
        "hint_overdue": "{n}d overdue (due {date}) — handle it or move the deadline",
        "hint_due_today": "Due today ({date})",
        "hint_left": "{n}d until {date}",

        # ---- New / Edit / Complete / Delete dialogs -----------------------
        "dlg_new_task": "New Task",
        "dlg_edit_task": "Edit Task",
        "dlg_finish_task": "Complete Task",
        "dlg_delete_task": "Delete Task",
        "new_title_hint": "Task title (required; duplicates of open tasks are skipped)",
        "new_start_hint": "YYYY-MM-DD (defaults to today)",
        "new_deadline_hint": "YYYY-MM-DD (optional)",
        "new_source_hint": "Optional; written as the first line [source:xxx]",
        "new_detail_hint": "Details (optional)",
        "fld_title_req": "Task Title *",
        "fld_source": "Source Tag",
        "fld_detail_label": "Details",
        "edit_title_fixed": "Task title (business key — renaming is unsupported)",
        "edit_deadline_hint": "YYYY-MM-DD (leave blank to keep unchanged)",
        "edit_result_hint": "Result (leave blank to keep unchanged)",
        "edit_incremental_note": "Saved per field; progress notes are never overwritten",

        # ---- Task Types (DB-backed, user-defined; no zh/en mapping) ------
        "manage_type_sentinel": "➕ Manage Types",
        "manage_type_title": "Manage Task Types",
        "manage_type_list_hint": "Stored in the database; add or remove freely. Removing a type keeps its text on historical tasks.",
        "manage_type_new_hint": "Enter a new task type name",
        "manage_type_delete": "Delete this type",
        "toast_type_name_required": "Task type name cannot be empty",
        "toast_type_added": 'Task type "{name}" added',
        "toast_type_deleted": 'Task type "{name}" deleted',

        # ---- Projects (DB-backed, user-defined; no zh/en mapping) --------
        "manage_proj_sentinel": "➕ Manage Projects",
        "manage_proj_title": "Manage Projects",
        "add_proj_btn": "New Project",
        "add_type_btn": "New Task Type",
        "manage_proj_list_hint": "Stored in the database; add or remove freely. Removing a project keeps its text on historical tasks.",
        "manage_proj_new_hint": "Enter a new project name",
        "manage_proj_delete": "Delete this project",
        "toast_proj_name_required": "Project name cannot be empty",
        "toast_proj_added": 'Project "{name}" added',
        "toast_proj_deleted": 'Project "{name}" deleted',
        "close_result_hint": "Result (required — same rule as CLI close --result)",
        "fld_result_req": "Result *",
        "fld_finish_default": "Finish date (defaults to today)",
        "delete_confirm": 'Delete task "{title}"?',
        "delete_warning": "This cannot be undone (GUI-only; the CLI has no delete)",
        "btn_cancel": "Cancel",
        "btn_add": "Add",
        "btn_close_dlg": "Close",
        "btn_create": "Create Task",
        "btn_save": "Save Changes",
        "btn_confirm_finish": "Confirm",
        "btn_confirm_delete": "Delete",

        # ---- Toasts -------------------------------------------------------
        "toast_title_required": "Task title cannot be empty",
        "toast_task_created": 'Task "{title}" created',
        "toast_duplicate_skipped": "Skipped: an open task with the same title exists",
        "toast_saved": "Changes saved",
        "toast_already_done": "Already completed — nothing to close",
        "toast_result_required": "Result is required",
        "toast_op_failed": "Operation failed: {err}",
        "toast_note_empty": "Please enter a progress note",
        "toast_note_added": "Progress note appended",
        "toast_already_status": 'Task is already "{st}"',
        "toast_status_updated": 'Status updated to "{st}"',
        "toast_task_closed": "Task closed",
        "toast_task_deleted": "Task deleted",
        "toast_lang_switched": "Language switched",

        # ---- Common -------------------------------------------------------
        "ph_empty": "—",
        "app_rail": "App Launchers",
        "app_no_apps_yet": "No apps yet",
        "app_btn_add": "Add App",
        "app_field_name": "Name",
        "app_field_path": "Executable path",
        "app_field_args": "Args (optional)",
        "app_field_icon": "Icon path (optional)",
        "app_btn_pick_file": "Pick file…",
        "app_btn_pick_icon": "Pick icon…",
        "app_btn_save": "Save",
        "app_btn_launch": "Launch",
        "app_btn_edit": "Edit",
        "app_btn_delete": "Delete",
        "app_btn_move_up": "Move up",
        "app_btn_move_down": "Move down",
        "app_title_add": "Add Application",
        "app_title_edit": "Edit Application",
        "app_confirm_delete": "Delete app \"{name}\"?",
        "app_toast_added": 'Added "{name}"',
        "app_toast_updated": 'Updated "{name}"',
        "app_toast_deleted": 'Deleted "{name}"',
        "app_toast_moved_up": 'Moved up "{name}"',
        "app_toast_moved_down": 'Moved down "{name}"',
        "app_launch_ok": 'Launched "{name}"',
        "app_launch_failed": 'Launch failed: {err}',
        "app_path_required": 'Executable path is required',
        "app_name_required": 'Name is required',
        "app_tip_add": 'Add a desktop app',

    },
}

# ---------------------------------------------------------------------------
# 数据值显示映射（仅显示层；数据库 / CLI / 筛选逻辑仍用中文原值）
# ---------------------------------------------------------------------------

STATUS_DISPLAY: dict[str, dict[str, str]] = {
    "zh": {"待办": "待办", "进行中": "进行中", "已搁置": "已搁置",
           "已完成": "已完成"},
    "en": {"待办": "Pending", "进行中": "In Progress", "已搁置": "On Hold",
           "已完成": "Completed"},
}

# 任务类型改为数据库托管、用户自定义（不再做中英文映射），故移除 TYPE_DISPLAY。

PRIORITY_DISPLAY: dict[str, dict[str, str]] = {
    "zh": {"高": "高", "中": "中", "低": "低"},
    "en": {"高": "High", "中": "Medium", "低": "Low"},
}

# 项目名（M006(YL055)、M007(YL057)…）是数据库原值，英文模式下原样显示
PROJECT_DISPLAY: dict[str, dict[str, str]] = {
    "zh": {},
    "en": {},
}

# 筛选项（非数据库值，仅 GUI 内部口径）显示映射
FILTER_DISPLAY: dict[str, dict[str, str]] = {
    "zh": {"全部": "全部", "未完结": "未完结", "逾期": "逾期",
           "今日到期": "今日到期", "7天内到期": "7天内到期", "本月完成": "本月完成"},
    "en": {"全部": "All", "未完结": "Open", "逾期": "Overdue",
           "今日到期": "Due today", "7天内到期": "Due in 7 days",
           "本月完成": "Done this month"},
}

MONTH_NAMES: dict[str, list[str]] = {
    "zh": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
}

WEEKDAY_NAMES: dict[str, list[str]] = {
    "zh": ["一", "二", "三", "四", "五", "六", "日"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}


# ---------------------------------------------------------------------------
# 语言偏好持久化（data/lang.json）
# ---------------------------------------------------------------------------

def _app_base_dir() -> str:
    """应用基准目录：打包后为 exe 所在目录，源码运行为脚本目录。

    优先复用 taskhub._app_base_dir()（同一套定位逻辑），
    任何异常都回退到本文件所在目录，保证 i18n 永不因路径问题崩溃。
    """
    try:
        import taskhub  # 局部导入：避免与业务层形成模块级循环依赖

        return taskhub._app_base_dir()
    except Exception:
        return _HERE


def lang_path() -> str:
    """语言偏好文件绝对路径：`<应用基准目录>/data/lang.json`。"""
    try:
        return os.path.join(_app_base_dir(), "data", "lang.json")
    except Exception:
        return os.path.join(_HERE, "data", "lang.json")


def load_lang() -> str:
    """从 lang.json 载入语言；文件缺失 / 损坏 / 值非法时回落中文。"""
    try:
        with open(lang_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            value = str(data.get("lang", "") or "").strip().lower()
            if value in LANGS:
                return value
    except Exception:
        pass
    return DEFAULT_LANG


_lang_cache: str = DEFAULT_LANG
_lang_loaded: bool = False


def get_lang() -> str:
    """当前语言（首次调用时从 lang.json 载入并缓存）。"""
    global _lang_cache, _lang_loaded
    if not _lang_loaded:
        _lang_cache = load_lang()
        _lang_loaded = True
    return _lang_cache


def set_lang(value: str) -> str:
    """切换并持久化语言；非法值回落中文。返回实际生效的语言。"""
    global _lang_cache, _lang_loaded
    lang = str(value or "").strip().lower()
    if lang not in LANGS:
        lang = DEFAULT_LANG
    _lang_cache = lang
    _lang_loaded = True
    try:
        path = lang_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"lang": lang}, handle, ensure_ascii=False)
    except Exception:
        # 持久化失败不影响本次会话的界面语言
        pass
    return lang


# ---------------------------------------------------------------------------
# 取词 / 显示映射
# ---------------------------------------------------------------------------

def _table(lang: str) -> dict[str, str]:
    """取指定语言的文案表；未知语言回落中文。"""
    return STRINGS.get(lang) or STRINGS[DEFAULT_LANG]


def tr(key: str, lang: str = None, default: str = None, **kw) -> str:
    """取文案：当前语言 → 中文 → default → 键名本身；支持 str.format 占位符。

    缺失键永不抛异常，保证新增文案只加一边也不会让界面崩溃。
    """
    current = lang or get_lang()
    value = _table(current).get(key)
    if value is None and current != DEFAULT_LANG:
        value = _table(DEFAULT_LANG).get(key)
    if value is None:
        value = default if default is not None else key
    if kw:
        try:
            value = value.format(**kw)
        except Exception:
            pass
    return value


def _map(table: dict[str, dict[str, str]], value, lang: str = None) -> str:
    """通用显示映射：未知值原样返回（不翻译、不报错）。"""
    text = "" if value is None else str(value)
    if not text:
        return text
    current = lang or get_lang()
    mapped = table.get(current, {}).get(text)
    if mapped is None and current != DEFAULT_LANG:
        mapped = table.get(DEFAULT_LANG, {}).get(text)
    return mapped if mapped is not None else text


def dstatus(value, lang: str = None) -> str:
    """状态显示值（待办 → Pending）。"""
    return _map(STATUS_DISPLAY, value, lang)


def dpriority(value, lang: str = None) -> str:
    """优先级显示值（高 → High）。"""
    return _map(PRIORITY_DISPLAY, value, lang)


def dproject(value, lang: str = None) -> str:
    """项目显示值：项目名为数据库原值，原样返回（M006(YL055) 不翻译）。"""
    return _map(PROJECT_DISPLAY, value, lang)


def dfilter(value, lang: str = None) -> str:
    """筛选项显示值（全部 → All，未完结 → Open）。"""
    return _map(FILTER_DISPLAY, value, lang)


def month_name(month: int, lang: str = None) -> str:
    """月份名：中文返回数字串（用于「2026 年 9 月」），英文返回月份全名。"""
    current = lang or get_lang()
    names = MONTH_NAMES.get(current) or MONTH_NAMES[DEFAULT_LANG]
    try:
        index = int(month) - 1
    except (TypeError, ValueError):
        return str(month)
    if 0 <= index < len(names):
        return names[index]
    return str(month)


def weekday_name(index: int, lang: str = None) -> str:
    """星期名：index=0 表示周一。"""
    current = lang or get_lang()
    names = WEEKDAY_NAMES.get(current) or WEEKDAY_NAMES[DEFAULT_LANG]
    try:
        pos = int(index)
    except (TypeError, ValueError):
        return str(index)
    if 0 <= pos < len(names):
        return names[pos]
    return str(index)


def missing_keys() -> dict[str, list[str]]:
    """自检：返回各语言相对中文缺失的键（正常应全为空列表）。"""
    base = set(STRINGS[DEFAULT_LANG])
    return {lang: sorted(base - set(_table(lang)))
            for lang in LANGS if lang != DEFAULT_LANG}
