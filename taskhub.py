#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""taskhub.py —— 工作任务跟踪台（本地 SQLite 版）单文件 CLI 应用。

由云端 WorkBuddy 资料库 database「工作任务跟踪台」（t1MXI312G1JPORf5qzoi4c）
重构而来：业务规则与 --json 输出契约保持兼容（每日自动化可无缝切换），
数据落地本地 SQLite，云端库只读不动。

子命令一览：
  init      初始化数据库（建表 + 索引，幂等）
  import    导入云端导出的 JSON（{"results": [...]} 中文字段名，按 record_id 幂等）
  list      查询任务（默认未完结；人类可读表格 / --json 机器可读单行）
  show      查看单条任务详情（含完整任务详情文本）
  add       新增任务（同名未完结任务自动查重跳过：skipped_duplicate）
  update    增量更新任务（--note 进度备注追加到任务详情末尾，不覆盖历史）
  close     关闭任务（状态→已完成 + 完成日期 + 结果结论）
  stats     统计（按状态 / 项目 / 优先级分组计数）
  projects  管理所属项目（数据库托管：列出 / 新增 / 删除）
  types     列出用户自定义任务类型（数据库托管）
  validate  自检（数据库存在、表结构、记录数）

退出码：0=成功（含业务跳过）；2=参数/校验错误；3=数据库/运行时错误。
环境变量 TASKHUB_DB 指定数据库路径（默认 <脚本目录>/data/taskhub.db）。
依赖：仅 Python 3.10+ 标准库（sqlite3/argparse/json/datetime/unicodedata/secrets）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import secrets
import sqlite3
import string
import subprocess
import sys
import unicodedata
from typing import Optional

# ---------------------------------------------------------------------------
# 常量：合法字段值 / 表结构 / 中英文语义映射
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _app_base_dir() -> str:
    """应用基准目录：打包成 exe 后为 exe 所在目录，脚本运行为脚本目录。

    PyInstaller onefile 模式下 __file__ 指向临时解压目录（随退出销毁），
    数据库必须落在 exe 旁边才能持久化。
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.dirname(os.path.abspath(sys.executable))
    return SCRIPT_DIR


DEFAULT_DB_PATH = os.path.join(_app_base_dir(), "data", "taskhub.db")

# select 字段合法值（与云端 schema 一致）
# 所属项目 / 任务类型为数据库托管字典，由用户自建，不再内置种子值
VALID_PRIORITIES = ["高", "中", "低"]
VALID_STATUSES = ["待办", "进行中", "已搁置", "已完成"]

# 未完结 = 待办 + 进行中 + 已搁置（list 默认过滤口径）
OPEN_STATUSES = {"待办", "进行中", "已搁置"}
# list --status 可选值
STATUS_FILTER_CHOICES = ["待办", "进行中", "已搁置", "已完成", "未完结", "全部"]

# record_id 生成：与云端风格一致的 22 位随机串（大小写字母 + 数字）
ID_ALPHABET = string.ascii_letters + string.digits
ID_LENGTH = 22

# 本地表结构（英文列名）
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    record_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    project     TEXT NOT NULL DEFAULT '其他',
    task_type   TEXT NOT NULL DEFAULT '日常事务',
    priority    TEXT NOT NULL DEFAULT '中',
    status      TEXT NOT NULL DEFAULT '待办',
    start_date  TEXT NOT NULL DEFAULT '',
    deadline    TEXT NOT NULL DEFAULT '',
    finish_date TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '',
    result      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks (project);
CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks (deadline);
CREATE TABLE IF NOT EXISTS task_types (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS projects (
    name       TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS app_launchers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    path       TEXT    NOT NULL,
    args       TEXT    NOT NULL DEFAULT '',
    icon_path  TEXT    NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT '',
    updated_at TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_app_launchers_sort ON app_launchers (sort_order, id);
"""

# validate 自检时要求存在的列
EXPECTED_COLUMNS = [
    "record_id", "title", "project", "task_type", "priority", "status",
    "start_date", "deadline", "finish_date", "detail", "result",
    "created_at", "updated_at",
]

# 云端导出 JSON（中文字段名）→ 本地表英文列
CLOUD_FIELD_MAP = {
    "任务名称": "title",
    "所属项目": "project",
    "任务类型": "task_type",
    "优先级": "priority",
    "状态": "status",
    "开始日期": "start_date",
    "截止日期": "deadline",
    "完成日期": "finish_date",
    "任务详情": "detail",
    "结果结论": "result",
}
DATE_COLUMNS = {"start_date", "deadline", "finish_date"}

# 英文列 → 中文语义（人类可读输出用）
COLUMN_LABELS = {
    "record_id": "记录ID",
    "title": "任务名称",
    "project": "所属项目",
    "task_type": "任务类型",
    "priority": "优先级",
    "status": "状态",
    "start_date": "开始日期",
    "deadline": "截止日期",
    "finish_date": "完成日期",
    "detail": "任务详情",
    "result": "结果结论",
}

# update changed_fields 用中文标签（与原 taskhub_ops.py 契约一致）
UPDATE_FIELD_LABELS = {
    "status": "状态",
    "priority": "优先级",
    "deadline": "截止日期",
    "project": "所属项目",
    "task_type": "任务类型",
    "result": "结果结论",
    "detail": "任务详情",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# 异常类型：决定退出码（UsageError→2，RunError→3）
# ---------------------------------------------------------------------------

class UsageError(Exception):
    """参数 / 校验错误（退出码 2）。"""


class RunError(Exception):
    """数据库 / 运行时错误（退出码 3）。"""


# ---------------------------------------------------------------------------
# 通用工具：归一化 / 日期 / 终端显示宽度
# ---------------------------------------------------------------------------

def norm_text(value) -> str:
    """归一化文本用于比较：NFKC（全角→半角）、去所有空白、转小写。

    用于任务名查重（add）与关键字模糊匹配（list），
    使「Ｍ006 客 诉」与「m006客诉」判定为相同。
    """
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return "".join(text.split()).lower()


def today_str() -> str:
    """今天的日期，YYYY-MM-DD。"""
    return datetime.date.today().isoformat()


def now_str() -> str:
    """当前本地时间戳，用于 created_at / updated_at 审计字段。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_stamp() -> str:
    """进度备注时间戳前缀格式：YYYY-MM-DD HH:MM。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def fmt_date(value) -> str:
    """云端日期（2026-09-05T00:00:00Z）截取为 YYYY-MM-DD；空值返回空串。"""
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text.split("T")[0] if "T" in text else text


def check_date(value: str, label: str) -> str:
    """校验日期严格为 YYYY-MM-DD 且真实存在，返回去空格后的串；非法抛 UsageError。"""
    text = (value or "").strip()
    if not text:
        raise UsageError(f"{label}不能为空（格式 YYYY-MM-DD）")
    if not DATE_RE.match(text):
        raise UsageError(f"{label}格式非法：{text}（要求 YYYY-MM-DD）")
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        raise UsageError(f"{label}格式非法：{text}（不是有效日期）") from None
    return text


def disp_width(text: str) -> int:
    """终端显示宽度：全角/宽字符（中文等）按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in str(text))


def pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格对齐。"""
    text = str(text)
    return text + " " * max(0, width - disp_width(text))


def cut_text(text: str, max_width: int) -> str:
    """按显示宽度截断字符串，超宽以 …（宽字符，计 2）结尾。"""
    text = str(text)
    if disp_width(text) <= max_width:
        return text
    out = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > max_width - 2:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def out_json(payload: dict) -> None:
    """按输出契约打印单行 JSON（ensure_ascii=False 保留中文）。"""
    print(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 数据库层
# ---------------------------------------------------------------------------

def db_path() -> str:
    """解析数据库路径：环境变量 TASKHUB_DB 优先，其次默认 data/taskhub.db。"""
    env = os.environ.get("TASKHUB_DB", "").strip()
    return env if env else DEFAULT_DB_PATH


def open_db(create: bool = False) -> sqlite3.Connection:
    """打开数据库连接。

    create=True 时自动创建父目录与文件（init / import 用）；
    否则要求文件已存在（未初始化时给出明确指引）。
    """
    path = db_path()
    if create:
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    elif not os.path.isfile(path):
        raise RunError(f"数据库不存在：{path}（请先运行 python taskhub.py init，"
                       f"或用环境变量 TASKHUB_DB 指定路径）")
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise RunError(f"打开数据库失败：{exc}") from exc
    conn.row_factory = sqlite3.Row
    # 幂等迁移：老库缺 task_types 表时自动建表 + 写入种子类型
    # （IF NOT EXISTS / 空表才播种，绝不覆盖用户增删）。
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表 + 索引（幂等，IF NOT EXISTS）。

    字典表（task_types / projects）不播种任何内置值，
    由用户自行新增（GUI 管理入口 / CLI projects|types --add / add 自由文本自动注册）。
    """
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# 用户自定义任务类型 / 所属项目（数据库托管字典，用户自建，无内置种子）
# ---------------------------------------------------------------------------

def list_task_types(conn: sqlite3.Connection) -> list[str]:
    """返回全部任务类型（按 sort_order 升序、同名稳定）。"""
    rows = conn.execute(
        "SELECT name FROM task_types ORDER BY sort_order, name").fetchall()
    return [r[0] for r in rows]


def add_task_type(conn: sqlite3.Connection, name: str) -> None:
    """新增一个任务类型（已存在则忽略，排序追加到末尾）。"""
    name = (name or "").strip()
    if not name:
        raise UsageError("任务类型名称不能为空")
    conn.execute(
        "INSERT OR IGNORE INTO task_types (name, sort_order) VALUES (?, "
        "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM task_types))",
        (name,))
    conn.commit()


def delete_task_type(conn: sqlite3.Connection, name: str) -> None:
    """删除一个任务类型（仅删字典项；仍被任务使用时不允许删除）。"""
    name = (name or "").strip()
    if not name:
        raise UsageError("任务类型名称不能为空")
    cnt = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE task_type = ?", (name,)).fetchone()[0]
    if cnt:
        raise UsageError(
            f"任务类型「{name}」仍被 {cnt} 条任务使用，不允许删除")
    conn.execute("DELETE FROM task_types WHERE name = ?", (name,))
    conn.commit()


def list_projects(conn: sqlite3.Connection) -> list[str]:
    """返回全部所属项目（按 sort_order 升序、同名稳定）。"""
    rows = conn.execute(
        "SELECT name FROM projects ORDER BY sort_order, name").fetchall()
    return [r[0] for r in rows]


def add_project(conn: sqlite3.Connection, name: str) -> None:
    """新增一个所属项目（已存在则忽略，排序追加到末尾）。"""
    name = (name or "").strip()
    if not name:
        raise UsageError("所属项目名称不能为空")
    conn.execute(
        "INSERT OR IGNORE INTO projects (name, sort_order) VALUES (?, "
        "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM projects))",
        (name,))
    conn.commit()


def delete_project(conn: sqlite3.Connection, name: str) -> None:
    """删除一个所属项目（仅删字典项；仍被任务使用时不允许删除）。"""
    name = (name or "").strip()
    if not name:
        raise UsageError("所属项目名称不能为空")
    cnt = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE project = ?", (name,)).fetchone()[0]
    if cnt:
        raise UsageError(
            f"所属项目「{name}」仍被 {cnt} 条任务使用，不允许删除")
    conn.execute("DELETE FROM projects WHERE name = ?", (name,))
    conn.commit()


# ---------------------------------------------------------------------------
# 桌面应用启动器（数据库托管，GUI 侧栏 + CLI apps 子命令共用）
# ---------------------------------------------------------------------------


def list_apps(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, name, path, args, icon_path, sort_order, created_at, updated_at "
        "FROM app_launchers ORDER BY sort_order, id").fetchall()
    return [dict(r) for r in rows]

def get_app(conn: sqlite3.Connection, app_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, name, path, args, icon_path, sort_order, created_at, updated_at "
        "FROM app_launchers WHERE id = ?", (app_id,)).fetchone()
    return dict(row) if row else None

def add_app(conn: sqlite3.Connection, name: str, path: str,
            args: str = "", icon_path: str = "") -> dict:
    name = (name or "").strip()
    path = (path or "").strip()
    args = (args or "").strip()
    icon_path = (icon_path or "").strip()
    if not name:
        raise UsageError("名称必填")
    if not path:
        raise UsageError("可执行路径必填")
    ts = now_str()
    cur = conn.execute(
        "INSERT INTO app_launchers (name, path, args, icon_path, sort_order, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, "
        "(SELECT COALESCE(MAX(sort_order), 0) + 1 FROM app_launchers), ?, ?)",
        (name, path, args, icon_path, ts, ts))
    conn.commit()
    return get_app(conn, cur.lastrowid)

def update_app(conn: sqlite3.Connection, app_id: int,
               name: str | None = None, path: str | None = None,
               args: str | None = None, icon_path: str | None = None) -> dict:
    if get_app(conn, app_id) is None:
        raise UsageError(f"应用 id={app_id} 不存在")
    sets, vals = [], []
    if name is not None:
        name = (name or "").strip()
        if not name:
            raise UsageError("名称必填")
        sets.append("name = ?"); vals.append(name)
    if path is not None:
        path = (path or "").strip()
        if not path:
            raise UsageError("可执行路径必填")
        sets.append("path = ?"); vals.append(path)
    if args is not None:
        sets.append("args = ?"); vals.append((args or "").strip())
    if icon_path is not None:
        sets.append("icon_path = ?"); vals.append((icon_path or "").strip())
    if not sets:
        raise UsageError("无可更新字段（至少指定一个）")
    sets.append("updated_at = ?"); vals.append(now_str())
    vals.append(app_id)
    conn.execute(f"UPDATE app_launchers SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    return get_app(conn, app_id)

def delete_app(conn: sqlite3.Connection, app_id: int) -> None:
    if get_app(conn, app_id) is None:
        raise UsageError(f"应用 id={app_id} 不存在")
    conn.execute("DELETE FROM app_launchers WHERE id = ?", (app_id,))
    conn.commit()

def move_app(conn: sqlite3.Connection, app_id: int, direction: str) -> dict | None:
    if direction not in ("up", "down"):
        raise UsageError("direction 须为 up 或 down")
    apps = list_apps(conn)
    idx = next((i for i, a in enumerate(apps) if a["id"] == app_id), -1)
    if idx < 0:
        raise UsageError(f"应用 id={app_id} 不存在")
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(apps):
        return get_app(conn, app_id)
    a, b = apps[idx], apps[swap]
    a_order, b_order = a["sort_order"], b["sort_order"]
    if a_order == b_order:
        b_order = a_order - 1 if direction == "up" else a_order + 1
    ts = now_str()
    conn.execute("UPDATE app_launchers SET sort_order=?, updated_at=? WHERE id=?",
                 (b_order, ts, a["id"]))
    conn.execute("UPDATE app_launchers SET sort_order=?, updated_at=? WHERE id=?",
                 (a_order, ts, b["id"]))
    conn.commit()
    return get_app(conn, app_id)

def launch_app(app: dict) -> None:
    path = (app.get("path") or "").strip()
    args_raw = (app.get("args") or "").strip()
    if not path:
        raise RunError("可执行路径为空")
    if not os.path.exists(path):
        raise RunError(f"路径不存在：{path}")
    args_list = [a for a in re.split(r"\s+", args_raw) if a] if args_raw else []
    try:
        if args_list:
            subprocess.Popen([path, *args_list])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception as exc:
        raise RunError(f"启动失败：{exc}") from exc


def new_record_id(conn: sqlite3.Connection) -> str:
    """生成 22 位随机 record_id（大小写字母 + 数字，与云端风格一致）。

    与库内现有 ID 冲突时重试，确保唯一。
    """
    existing = {row[0] for row in conn.execute("SELECT record_id FROM tasks")}
    while True:
        rid = "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if rid not in existing:
            return rid


def row_to_record(row: sqlite3.Row) -> dict:
    """sqlite3.Row → 中文键的完整记录（show / 契约输出用，任务详情不截断）。"""
    return {
        "record_id": row["record_id"],
        "任务名称": row["title"],
        "所属项目": row["project"],
        "任务类型": row["task_type"],
        "优先级": row["priority"],
        "状态": row["status"],
        "开始日期": row["start_date"],
        "截止日期": row["deadline"],
        "完成日期": row["finish_date"],
        "任务详情": row["detail"],
        "结果结论": row["result"],
    }


def row_to_list_item(row: sqlite3.Row) -> dict:
    """sqlite3.Row → list 契约条目（与原 taskhub_ops.py 字段一致，任务详情截前 200 字）。"""
    return {
        "record_id": row["record_id"],
        "任务名称": row["title"],
        "所属项目": row["project"],
        "任务类型": row["task_type"],
        "优先级": row["priority"],
        "状态": row["status"],
        "截止日期": row["deadline"],
        "任务详情": (row["detail"] or "")[:200],
    }


# ---------------------------------------------------------------------------
# 业务操作：查询 / 新增 / 更新 / 关闭 / 定位
# ---------------------------------------------------------------------------

def query_tasks(conn: sqlite3.Connection, status: str = "未完结",
                project: str = "", keyword: str = "", limit: int = 100):
    """查询任务列表。

    过滤：status（未完结=待办+进行中+已搁置；全部=不过滤）、project 精确、
    keyword 归一化模糊（忽略空格/全半角/大小写）。
    排序：截止日期升序，空截止排最后（同原契约；并列按 record_id 保证稳定）。
    返回 (total_in_db, 截取 limit 后的行列表, 过滤后总命中数)。
    """
    rows = conn.execute("SELECT * FROM tasks").fetchall()
    total = len(rows)
    keyword_norm = norm_text(keyword)
    hits = []
    for row in rows:
        row_status = (row["status"] or "").strip()
        if status == "未完结":
            if row_status not in OPEN_STATUSES:
                continue
        elif status not in ("", "全部"):
            if row_status != status:
                continue
        if project and (row["project"] or "").strip() != project:
            continue
        if keyword_norm and keyword_norm not in norm_text(row["title"] or ""):
            continue
        hits.append(row)
    # (是否空截止, 截止日期, record_id)：空截止排最后
    hits.sort(key=lambda r: (not (r["deadline"] or ""), r["deadline"] or "", r["record_id"]))
    return total, hits[:limit], len(hits)


def find_record(conn: sqlite3.Connection, ref: str, title: str) -> sqlite3.Row:
    """按 record_id 或任务名称定位任务（update / close / show 共用）。

    ref：先按 record_id 精确匹配，未命中再按任务名称（归一化）匹配；
    title：显式按任务名称（归一化）匹配。
    多条同名时：未完结优先，其次开始日期降序，取第一条（与原脚本一致）。
    """
    ref = (ref or "").strip()
    title = (title or "").strip()
    if not ref and not title:
        raise UsageError("必须提供 record_id 位置参数或 --title 之一")
    if ref:
        row = conn.execute("SELECT * FROM tasks WHERE record_id = ?", (ref,)).fetchone()
        if row is not None:
            return row
    name = title or ref  # ref 未命中 record_id 时兜底当作任务名
    rows = conn.execute("SELECT * FROM tasks").fetchall()
    matched = [r for r in rows if norm_text(r["title"]) == norm_text(name)]
    if not matched:
        raise UsageError(f"任务不存在：{name}（已按 record_id 与任务名称归一化查找）")
    if len(matched) > 1:
        open_hits = [r for r in matched if r["status"] in OPEN_STATUSES]
        pool = open_hits if open_hits else matched
        pool.sort(key=lambda r: r["start_date"] or "", reverse=True)
        return pool[0]
    return matched[0]


def add_task(conn: sqlite3.Connection, title: str, project: str, task_type: str,
             priority: str, start: str, deadline: str, detail: str, source: str) -> dict:
    """新增任务。

    业务规则（与云端脚本一致）：
      - title 必填（业务主键）；project 默认其他；type 默认日常事务；
        priority 默认中，非法值回落中；start 默认今天；deadline / detail / source 可空；
      - source 写入任务详情首行 [来源:xxx]；
      - 查重：同名（归一化比较）且状态为 待办/进行中/已搁置 → 跳过
        返回 action=skipped_duplicate（退出码仍为 0）；同名已完结则正常新增。
    """
    title = (title or "").strip()
    if not title:
        raise UsageError("add 必须提供非空 --title")
    project = (project or "").strip() or "其他"
    # 用户自定义所属项目：首次出现自动写入 projects 表（幂等，不拦截）。
    try:
        add_project(conn, project)
    except Exception:
        pass
    task_type = (task_type or "").strip() or "日常事务"
    # 用户自定义任务类型：首次出现自动写入 task_types 表（幂等，不拦截）。
    try:
        add_task_type(conn, task_type)
    except Exception:
        pass
    priority = (priority or "").strip()
    if priority not in VALID_PRIORITIES:
        priority = "中"  # 与原脚本一致：非法优先级回落「中」
    start = (start or "").strip() or today_str()
    check_date(start, "--start")
    deadline = (deadline or "").strip()
    if deadline:
        check_date(deadline, "--deadline")
    detail = (detail or "").strip()
    source = (source or "").strip()

    # 查重：同名（归一化）且未完结 → 跳过
    for row in conn.execute("SELECT record_id, title, status FROM tasks"):
        if (norm_text(row["title"]) == norm_text(title)
                and row["status"] in OPEN_STATUSES):
            return {
                "ok": True, "mode": "add", "action": "skipped_duplicate",
                "reason": f"已存在未完结同名任务 record_id={row['record_id']}",
                "record_id": row["record_id"], "title": title,
            }

    rid = new_record_id(conn)
    detail_lines = []
    if source:
        detail_lines.append(f"[来源:{source}]")
    if detail:
        detail_lines.append(detail)
    full_detail = "\n".join(detail_lines)
    ts = now_str()
    conn.execute(
        "INSERT INTO tasks (record_id, title, project, task_type, priority, status,"
        " start_date, deadline, finish_date, detail, result, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, title, project, task_type, priority, "待办",
         start, deadline, "", full_detail, "", ts, ts),
    )
    conn.commit()
    return {"ok": True, "mode": "add", "action": "created",
            "record_id": rid, "title": title}


def update_task(conn: sqlite3.Connection, ref: str, title: str,
                status: Optional[str] = None, priority: Optional[str] = None,
                deadline: Optional[str] = None, project: Optional[str] = None,
                result: Optional[str] = None, note: Optional[str] = None,
                task_type: Optional[str] = None) -> dict:
    """增量更新任务。

    所有字段参数均为「可选增量」：传 None 表示不修改该字段（GUI 按字段保存、
    CLI 只传变化项时都依赖这一语义）。

    - status 校验 4 值之一；priority 校验 高/中/低；project 校验 9 个合法项目；
      deadline 校验 YYYY-MM-DD；result 改写结果结论；
      task_type 校验 7 个合法任务类型（可选参数，CLI --task-type / GUI 编辑用）；
    - note（进度备注）追加到任务详情末尾，格式 [YYYY-MM-DD HH:MM] 备注，不覆盖历史；
    - 无任何可更新字段时报错（退出码 2）。
    """
    row = find_record(conn, ref, title)
    changes: dict[str, str] = {}  # 英文列 → 新值（插入顺序决定 changed_fields 顺序）

    if status is not None:
        s = status.strip()
        if s not in VALID_STATUSES:
            raise UsageError(f"非法状态值：{s}（合法值：{'/'.join(VALID_STATUSES)}）")
        changes["status"] = s
    if priority is not None:
        p = priority.strip()
        if p not in VALID_PRIORITIES:
            raise UsageError(f"非法优先级：{p}（合法值：{'/'.join(VALID_PRIORITIES)}）")
        changes["priority"] = p
    if deadline is not None:
        changes["deadline"] = check_date(deadline, "--deadline")
    if project is not None:
        pr = project.strip()
        if not pr:
            raise UsageError("所属项目不能为空")
        # 用户自定义所属项目：首次出现自动写入 projects 表（幂等，不拦截）。
        try:
            add_project(conn, pr)
        except Exception:
            pass
        changes["project"] = pr
    if task_type is not None:
        tt = task_type.strip()
        if not tt:
            raise UsageError("任务类型不能为空")
        # 用户自定义任务类型：首次出现自动写入 task_types 表（幂等，不拦截）。
        try:
            add_task_type(conn, tt)
        except Exception:
            pass
        changes["task_type"] = tt
    if result is not None and result.strip():
        changes["result"] = result.strip()
    if note is not None and note.strip():
        note_text = note.strip()
        old_detail = row["detail"] or ""
        new_detail = (f"{old_detail}\n[{now_stamp()}] {note_text}" if old_detail
                      else f"[{now_stamp()}] {note_text}")
        changes["detail"] = new_detail

    if not changes:
        raise UsageError("update 无可更新字段"
                         "（--status/--priority/--deadline/--project/--result/--note 至少一项）")

    changes["updated_at"] = now_str()
    set_clause = ", ".join(f"{col} = ?" for col in changes)
    params = list(changes.values()) + [row["record_id"]]
    conn.execute(f"UPDATE tasks SET {set_clause} WHERE record_id = ?", params)
    conn.commit()
    changed_fields = [UPDATE_FIELD_LABELS[c] for c in changes if c in UPDATE_FIELD_LABELS]
    return {"ok": True, "mode": "update", "action": "updated",
            "record_id": row["record_id"], "title": row["title"],
            "changed_fields": changed_fields}


def close_task(conn: sqlite3.Connection, ref: str, title: str,
               result: str, finish_date: str) -> dict:
    """关闭任务：状态→已完成 + 完成日期（默认今天）+ 结果结论。

    - result 必填（退出码 2）；
    - 已完成的任务再 close → action=skipped_already_done（退出码 0）。
    """
    result = (result or "").strip()
    if not result:
        raise UsageError("close 必须提供 --result（结果结论）")
    row = find_record(conn, ref, title)
    if row["status"] == "已完成":
        return {"ok": True, "mode": "close", "action": "skipped_already_done",
                "record_id": row["record_id"], "title": row["title"]}
    finish = (finish_date or "").strip() or today_str()
    check_date(finish, "--finish-date")
    conn.execute(
        "UPDATE tasks SET status = ?, finish_date = ?, result = ?, updated_at = ?"
        " WHERE record_id = ?",
        ("已完成", finish, result, now_str(), row["record_id"]),
    )
    conn.commit()
    return {"ok": True, "mode": "close", "action": "closed",
            "record_id": row["record_id"], "title": row["title"],
            "finish_date": finish}


def import_records(conn: sqlite3.Connection, file_path: str) -> dict:
    """导入云端导出的 JSON（{"results": [...]}，中文字段名）。

    - 日期截取 T 前段（2026-09-05T00:00:00Z → 2026-09-05），空值存空串；
    - 按 record_id 幂等：已存在则更新该行数据（保留 created_at），不存在则插入；
    - record_id 原样保留，便于与云端核对；
    - 缺 record_id / 任务名称的坏行跳过并记入 problems，不阻断整体导入。
    """
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        raise UsageError(f"导入文件不存在：{path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"读取导入文件失败：{exc}") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise UsageError("导入文件格式非法：需为 {\"results\": [...]} 结构")

    existing = {row[0] for row in conn.execute("SELECT record_id FROM tasks")}
    ts = now_str()
    inserted = updated = skipped = 0
    problems: list[str] = []
    for idx, raw in enumerate(results):
        try:
            rec = _map_cloud_record(raw)
        except UsageError as exc:
            skipped += 1
            problems.append(f"第 {idx + 1} 条：{exc}")
            continue
        rid = rec["record_id"]
        if rid in existing:
            conn.execute(
                "UPDATE tasks SET title = ?, project = ?, task_type = ?, priority = ?,"
                " status = ?, start_date = ?, deadline = ?, finish_date = ?,"
                " detail = ?, result = ?, updated_at = ? WHERE record_id = ?",
                (rec["title"], rec["project"], rec["task_type"], rec["priority"],
                 rec["status"], rec["start_date"], rec["deadline"], rec["finish_date"],
                 rec["detail"], rec["result"], ts, rid),
            )
            updated += 1
        else:
            conn.execute(
                "INSERT INTO tasks (record_id, title, project, task_type, priority,"
                " status, start_date, deadline, finish_date, detail, result,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, rec["title"], rec["project"], rec["task_type"], rec["priority"],
                 rec["status"], rec["start_date"], rec["deadline"], rec["finish_date"],
                 rec["detail"], rec["result"], ts, ts),
            )
            existing.add(rid)
            inserted += 1
    conn.commit()
    return {"ok": True, "mode": "import", "file": path, "total": len(results),
            "inserted": inserted, "updated": updated, "skipped": skipped,
            "problems": problems}


def _map_cloud_record(raw) -> dict:
    """云端单条记录（中文键）→ 本地列 dict；缺 record_id / 任务名称 时抛 UsageError。"""
    if not isinstance(raw, dict):
        raise UsageError("记录不是 JSON 对象")
    rid = str(raw.get("record_id") or "").strip()
    if not rid:
        raise UsageError("缺少 record_id")
    title = str(raw.get("任务名称") or "").strip()
    if not title:
        raise UsageError(f"record_id={rid} 缺少任务名称")
    rec = {"record_id": rid, "title": title}
    for cn_name, column in CLOUD_FIELD_MAP.items():
        if cn_name == "任务名称":
            continue
        value = raw.get(cn_name)
        if column in DATE_COLUMNS:
            rec[column] = fmt_date(value)
        else:
            rec[column] = "" if value is None else str(value).strip()
    return rec


def gather_stats(conn: sqlite3.Connection) -> dict:
    """按状态 / 项目 / 优先级分组计数（组内按数量降序、名称升序）。"""
    rows = conn.execute("SELECT status, project, priority FROM tasks").fetchall()

    def count_by(column: str) -> dict:
        counter: dict[str, int] = {}
        for row in rows:
            key = row[column] or "（空）"
            counter[key] = counter.get(key, 0) + 1
        return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))

    return {"total": len(rows),
            "by_status": count_by("status"),
            "by_project": count_by("project"),
            "by_priority": count_by("priority")}


def run_validate() -> tuple[list[str], int]:
    """自检：数据库文件存在、tasks 表结构完整、统计记录数。

    返回 (问题列表, 记录数)；问题列表为空即自检通过。
    """
    path = os.path.abspath(db_path())
    problems: list[str] = []
    if not os.path.isfile(path):
        return [f"数据库文件不存在：{path}（请先运行 init）"], 0
    count = 0
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            tables = [r[0] for r in
                      conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            if "tasks" not in tables:
                problems.append("缺少 tasks 表（请运行 init 建表）")
            else:
                columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
                missing = [c for c in EXPECTED_COLUMNS if c not in columns]
                if missing:
                    problems.append(f"tasks 表缺少列：{', '.join(missing)}")
                count = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RunError(f"读取数据库失败：{exc}") from exc
    return problems, count


# ---------------------------------------------------------------------------
# 人类可读输出
# ---------------------------------------------------------------------------

def print_tasks_human(rows: list, matched: int, total: int, desc: str, limit: int) -> None:
    """list 表格输出：中文表头、全角宽度对齐、超宽截断。"""
    extra = f"（限前 {limit} 条）" if matched > len(rows) else ""
    print(f"任务列表（{desc}）：匹配 {matched} 条，本次显示 {len(rows)} 条{extra}"
          f"，数据库共 {total} 条")
    if not rows:
        print("（无匹配记录）")
        return
    headers = ["记录ID", "任务名称", "所属项目", "任务类型", "优先级", "状态", "截止日期", "任务详情"]
    limits = [22, 30, 12, 10, 4, 6, 10, 36]
    table = []
    for row in rows:
        table.append([
            row["record_id"], row["title"], row["project"], row["task_type"],
            row["priority"], row["status"], row["deadline"] or "-",
            (row["detail"] or "").replace("\n", " "),
        ])
    table = [[cut_text(cell, w) for cell, w in zip(line, limits)] for line in table]
    widths = [disp_width(h) for h in headers]
    for line in table:
        for i, cell in enumerate(line):
            widths[i] = max(widths[i], disp_width(cell))
    header_line = "  ".join(pad(h, w) for h, w in zip(headers, widths))
    print(header_line)
    print("-" * disp_width(header_line))
    for line in table:
        print("  ".join(pad(c, w) for c, w in zip(line, widths)))


SHOW_FIELD_ORDER = [
    ("任务名称", "任务名称"),
    ("所属项目", "所属项目"),
    ("任务类型", "任务类型"),
    ("优先级", "优先级"),
    ("状态", "状态"),
    ("开始日期", "开始日期"),
    ("截止日期", "截止日期"),
    ("完成日期", "完成日期"),
    ("结果结论", "结果结论"),
]


def print_show_human(rec: dict) -> None:
    """show 逐字段输出（任务详情完整展示，不截断）。"""
    print(f"任务：{rec['任务名称']}")
    print("-" * 48)
    print(f"记录ID：{rec['record_id']}")
    for label, key in SHOW_FIELD_ORDER:
        print(f"{label}：{rec[key] or '（空）'}")
    print("任务详情：")
    detail = rec["任务详情"] or ""
    if detail:
        for line in detail.splitlines():
            print(f"  {line}")
    else:
        print("  （空）")


def print_stats_human(stats: dict) -> None:
    """stats 人类可读输出：三组分组计数。"""
    print(f"任务统计：共 {stats['total']} 条")
    for label, key in (("按状态", "by_status"), ("按项目", "by_project"),
                       ("按优先级", "by_priority")):
        print(f"\n{label}：")
        group = stats[key]
        if not group:
            print("  （无记录）")
            continue
        for name, count in group.items():
            print(f"  {name}: {count}")


def print_validate_human(payload: dict) -> None:
    """validate 人类可读输出。"""
    if payload["passed"]:
        print(f"自检通过：数据库 {payload['db_path']}，记录数 {payload['record_count']}")
    else:
        print("自检未通过：")
        for problem in payload["problems"]:
            print(f"  - {problem}")


# ---------------------------------------------------------------------------
# CLI：参数定义与分发
# ---------------------------------------------------------------------------

class TaskhubParser(argparse.ArgumentParser):
    """argparse 子类：带 --json 调用时，参数错误也输出契约 JSON（而非裸文本）。"""

    def error(self, message: str):
        if "--json" in sys.argv:
            out_json({"ok": False, "error": f"参数错误：{message}"})
            sys.exit(2)
        super().error(message)


def build_parser() -> TaskhubParser:
    """构造 CLI 参数解析器（中文帮助文本）。"""
    parser = TaskhubParser(
        prog="taskhub.py",
        description="工作任务跟踪台（本地 SQLite 版）——任务增查改关、统计与自检。",
        epilog="示例：python taskhub.py list --status 待办 --json\n"
               "      python taskhub.py add --title \"M006 首件检验跟进\" --project \"M006(YL055)\"",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<子命令>")

    p = sub.add_parser("init", help="初始化数据库（建表 + 索引，幂等）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("import", help="导入云端导出的 JSON（按 record_id 幂等：存在则更新）")
    p.add_argument("--file", required=True, help="云端导出 JSON 文件路径（{\"results\": [...]}）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("list", help="查询任务列表（默认未完结，按截止日期升序，空截止最后）")
    p.add_argument("--status", default="未完结", choices=STATUS_FILTER_CHOICES,
                   help="状态过滤：待办/进行中/已搁置/已完成/未完结(默认)/全部")
    p.add_argument("--project", default="",
                   help="按所属项目精确过滤（库内项目见 projects 命令）")
    p.add_argument("--keyword", default="",
                   help="任务名称关键字（归一化模糊匹配：忽略空格/全半角/大小写）")
    p.add_argument("--limit", type=int, default=100, help="最多返回条数（默认 100）")
    p.add_argument("--json", action="store_true",
                   help="输出机器可读单行 JSON（兼容原 taskhub_ops.py 契约）")

    p = sub.add_parser("show", help="查看单条任务详情（含完整任务详情）")
    p.add_argument("ref", nargs="?", default="",
                   help="record_id（或任务名称：优先按 record_id 匹配，未命中按名称）")
    p.add_argument("--title", default="", help="按任务名称定位（与 ref 二选一）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("add", help="新增任务（同名未完结任务自动查重跳过）")
    p.add_argument("--title", required=True, help="任务名称（必填，业务主键）")
    p.add_argument("--project", default="其他",
                   help="所属项目（默认 其他；自由文本，首次使用自动写入项目表）")
    p.add_argument("--type", default="日常事务",
                   help="任务类型（默认 日常事务；自由文本，首次使用自动写入任务类型表）")
    p.add_argument("--priority", default="中",
                   help="优先级：高/中/低（默认 中，非法值回落 中）")
    p.add_argument("--start", default="", help="开始日期 YYYY-MM-DD（默认今天）")
    p.add_argument("--deadline", default="", help="截止日期 YYYY-MM-DD（可空）")
    p.add_argument("--detail", default="", help="任务详情（可空）")
    p.add_argument("--source", default="",
                   help="来源标记（可空；写入任务详情首行 [来源:xxx]）")
    p.add_argument("--json", action="store_true", help="输出兼容原契约的单行 JSON")

    p = sub.add_parser("update", help="增量更新任务（--note 进度备注追加，不覆盖历史）")
    p.add_argument("ref", nargs="?", default="",
                   help="record_id（或任务名称：优先按 record_id 匹配，未命中按名称）")
    p.add_argument("--title", default="",
                   help="按任务名称定位（与 ref 二选一；多条同名时未完结优先、开始日期降序）")
    p.add_argument("--status", choices=VALID_STATUSES, help="新状态（4 值之一）")
    p.add_argument("--priority", choices=VALID_PRIORITIES, help="新优先级（高/中/低）")
    p.add_argument("--deadline", default=None, help="新截止日期 YYYY-MM-DD")
    p.add_argument("--project", default=None,
                   help="新所属项目（自由文本；首次使用自动写入项目表）")
    p.add_argument("--task-type", default=None,
                   help="新任务类型（自由文本；首次使用自动写入任务类型表）")
    p.add_argument("--result", default=None, help="结果结论（非空时改写）")
    p.add_argument("--note", default=None,
                   help="进度备注（追加到任务详情末尾，格式 [YYYY-MM-DD HH:MM] 备注）")
    p.add_argument("--json", action="store_true", help="输出兼容原契约的单行 JSON")

    p = sub.add_parser("close", help="关闭任务（状态→已完成 + 完成日期 + 结果结论）")
    p.add_argument("ref", nargs="?", default="",
                   help="record_id（或任务名称：优先按 record_id 匹配，未命中按名称）")
    p.add_argument("--title", default="", help="按任务名称定位（与 ref 二选一）")
    p.add_argument("--result", required=True, help="结果结论（必填）")
    p.add_argument("--finish-date", default="",
                   help="完成日期 YYYY-MM-DD（默认今天）")
    p.add_argument("--json", action="store_true", help="输出兼容原契约的单行 JSON")

    p = sub.add_parser("stats", help="统计（按状态 / 项目 / 优先级分组计数）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("projects",
                       help="管理所属项目（数据库托管：列出 / 新增 / 删除）")
    p.add_argument("--add", default="", metavar="名称",
                   help="新增所属项目（自由文本，如 --add M012）")
    p.add_argument("--delete", default="", metavar="名称",
                   help="删除所属项目（仅删字典项，历史任务文本保留）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("types",
                       help="管理任务类型（数据库托管：列出 / 新增 / 删除）")
    p.add_argument("--add", default="", metavar="名称",
                   help="新增任务类型（自由文本，如 --add 试模跟踪）")
    p.add_argument("--delete", default="", metavar="名称",
                   help="删除任务类型（仅删字典项，历史任务文本保留）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("validate", help="自检：数据库存在、表结构、记录数")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    p = sub.add_parser("apps",
                       help="管理桌面应用启动器（list/add/update/delete/launch/move）")
    p.add_argument("--add", action="store_true", help="新增应用（需配合 --name/--path）")
    p.add_argument("--update", type=int, default=0, metavar="id",
                   help="按 id 增量更新（同时被 --move 复用为目标 id）")
    p.add_argument("--delete", type=int, default=0, metavar="id",
                   help="按 id 删除应用")
    p.add_argument("--launch", type=int, default=0, metavar="id",
                   help="按 id 启动应用")
    p.add_argument("--move", choices=["up", "down"], default="",
                   help="移动顺序（up/down，配合 --update <id>）")
    p.add_argument("--name", default="", help="应用名称")
    p.add_argument("--path", default="", help="可执行路径（exe / lnk / url / 目录）")
    p.add_argument("--args", default="", help="启动参数（空格分隔）")
    p.add_argument("--icon", dest="icon_path", default="", help="图标图片路径（可选）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")

    return parser




def _run_apps_command(args: argparse.Namespace) -> int:
    """apps 子命令：list / --add / --update / --delete / --launch / --move。"""
    as_json = args.json
    is_write = bool(args.add or args.update or args.delete or args.move or args.launch)
    if not is_write:
        apps = []
        if os.path.isfile(db_path()):
            conn = open_db()
            try:
                apps = list_apps(conn)
            finally:
                conn.close()
        if as_json:
            out_json({"ok": True, "mode": "apps", "count": len(apps), "apps": apps})
        else:
            print(f"桌面应用启动器（{len(apps)} 个）：")
            for a in apps:
                extra = f"  args={a['args']}" if a['args'] else ""
                print(f"  [{a['id']}] {a['name']}  →  {a['path']}{extra}")
        return 0
    conn = open_db(create=True)
    try:
        if args.add:
            if not args.name or not args.path:
                raise UsageError("--add 需配合 --name 与 --path")
            app = add_app(conn, args.name, args.path, args.args, args.icon_path)
            if as_json:
                out_json({"ok": True, "mode": "apps", "action": "added", "app": app})
            else:
                print(f"已新增应用：[{app['id']}] {app['name']} → {app['path']}")
        elif args.update and not args.move:
            kwargs = {}
            if args.name: kwargs["name"] = args.name
            if args.path: kwargs["path"] = args.path
            if args.args: kwargs["args"] = args.args
            if args.icon_path: kwargs["icon_path"] = args.icon_path
            if not kwargs:
                raise UsageError("--update 需至少指定一个字段（--name/--path/--args/--icon）")
            app = update_app(conn, args.update, **kwargs)
            if as_json:
                out_json({"ok": True, "mode": "apps", "action": "updated", "app": app})
            else:
                print(f"已更新应用：[{app['id']}] {app['name']}")
        elif args.move:
            if not args.update:
                raise UsageError("--move 需配合 --update <id>")
            app = move_app(conn, args.update, args.move)
            if as_json:
                out_json({"ok": True, "mode": "apps", "action": "moved_" + args.move, "app": app})
            else:
                print(f"已{('上' if args.move == 'up' else '下')}移应用：[{app['id']}] {app['name']}")
        elif args.delete:
            delete_app(conn, args.delete)
            if as_json:
                out_json({"ok": True, "mode": "apps", "action": "deleted", "id": args.delete})
            else:
                print(f"已删除应用：id={args.delete}")
        elif args.launch:
            app = get_app(conn, args.launch)
            if app is None:
                raise UsageError(f"应用 id={args.launch} 不存在")
            launch_app(app)
            if as_json:
                out_json({"ok": True, "mode": "apps", "action": "launched", "app": app})
            else:
                print(f"已启动：{app['name']} ({app['path']})")
    finally:
        conn.close()
    return 0

def _run_dict_command(args: argparse.Namespace, cmd: str,
                      list_fn, add_fn, del_fn, label: str) -> int:
    """projects / types 共用管理逻辑（数据库托管字典，用户自建）。

    - 纯列表：读取库内用户自建列表；未初始化数据库时显示空列表；
    - --add / --delete：无库时自动建库建表。
    """
    if args.add or args.delete:
        conn = open_db(create=True)
        try:
            if args.add:
                add_fn(conn, args.add)
            if args.delete:
                del_fn(conn, args.delete)
        finally:
            conn.close()
        if args.json:
            out_json({"ok": True, "mode": cmd,
                      "action": ("added" if args.add else "deleted"),
                      "name": (args.add or args.delete).strip()})
        else:
            if args.add:
                print(f"已新增{label}：{args.add.strip()}")
            if args.delete:
                print(f"已删除{label}：{args.delete.strip()}")
        return 0
    items = None
    has_db = os.path.isfile(db_path())
    if has_db:
        conn = open_db()
        try:
            items = list_fn(conn)
        finally:
            conn.close()
    if items is None:
        items = []
    if args.json:
        key = "projects" if cmd == "projects" else "types"
        out_json({"ok": True, "mode": cmd, key: items})
    else:
        suffix = "" if has_db else "（数据库未初始化）"
        print(f"{label}（{len(items)} 个）{suffix}：")
        for i, name in enumerate(items, 1):
            print(f"  {i}. {name}")
    return 0


def dispatch(args: argparse.Namespace) -> int:
    """子命令分发；返回退出码。"""
    cmd = args.command

    if cmd == "init":
        conn = open_db(create=True)
        try:
            ensure_schema(conn)
        finally:
            conn.close()
        path = os.path.abspath(db_path())
        if args.json:
            out_json({"ok": True, "mode": "init", "db_path": path})
        else:
            print(f"数据库已就绪：{path}")
        return 0

    if cmd == "import":
        conn = open_db(create=True)
        try:
            ensure_schema(conn)
            result = import_records(conn, args.file)
        finally:
            conn.close()
        if args.json:
            out_json(result)
        else:
            print(f"导入完成：文件共 {result['total']} 条，新增 {result['inserted']}，"
                  f"更新 {result['updated']}，跳过 {result['skipped']}")
            for problem in result["problems"]:
                print(f"  跳过原因：{problem}")
        return 0

    if cmd == "list":
        if args.limit < 1:
            raise UsageError("--limit 须为正整数")
        # project 为纯精确过滤（与原脚本一致：无匹配返回空列表，不校验合法性）
        project = (args.project or "").strip()
        conn = open_db()
        try:
            total, shown, matched = query_tasks(
                conn, args.status, project, args.keyword, args.limit)
        finally:
            conn.close()
        if args.json:
            out_json({"ok": True, "mode": "list", "count": matched,
                      "total_in_db": total,
                      "tasks": [row_to_list_item(r) for r in shown]})
        else:
            desc = f"状态={args.status}"
            if project:
                desc += f"，项目={project}"
            if args.keyword:
                desc += f"，关键字={args.keyword}"
            print_tasks_human(shown, matched, total, desc, args.limit)
        return 0

    if cmd == "show":
        conn = open_db()
        try:
            rec = row_to_record(find_record(conn, args.ref, args.title))
        finally:
            conn.close()
        if args.json:
            out_json({"ok": True, "mode": "show", "task": rec})
        else:
            print_show_human(rec)
        return 0

    if cmd == "add":
        conn = open_db()
        try:
            result = add_task(conn, args.title, args.project, args.type,
                              args.priority, args.start, args.deadline,
                              args.detail, args.source)
        finally:
            conn.close()
        if args.json:
            out_json(result)
        elif result["action"] == "created":
            print(f"新增成功：{result['record_id']} 任务「{result['title']}」")
        else:
            print(f"跳过新增：{result['reason']}")
        return 0

    if cmd == "update":
        conn = open_db()
        try:
            result = update_task(conn, args.ref, args.title, args.status,
                                 args.priority, args.deadline, args.project,
                                 args.result, args.note,
                                 getattr(args, "task_type", None))
        finally:
            conn.close()
        if args.json:
            out_json(result)
        else:
            fields = "、".join(result["changed_fields"])
            print(f"更新成功：{result['record_id']} 任务「{result['title']}」"
                  f"（字段：{fields}）")
        return 0

    if cmd == "close":
        conn = open_db()
        try:
            result = close_task(conn, args.ref, args.title, args.result,
                                args.finish_date)
        finally:
            conn.close()
        if args.json:
            out_json(result)
        elif result["action"] == "closed":
            print(f"关闭成功：{result['record_id']} 任务「{result['title']}」"
                  f"（完成日期 {result['finish_date']}）")
        else:
            print(f"跳过关闭：任务已完成 {result['record_id']} 任务「{result['title']}」")
        return 0

    if cmd == "stats":
        conn = open_db()
        try:
            stats = gather_stats(conn)
        finally:
            conn.close()
        if args.json:
            out_json({"ok": True, "mode": "stats", **stats})
        else:
            print_stats_human(stats)
        return 0

    if cmd == "projects":
        return _run_dict_command(
            args, "projects",
            list_projects, add_project, delete_project, "所属项目")

    if cmd == "types":
        return _run_dict_command(
            args, "types",
            list_task_types, add_task_type, delete_task_type, "任务类型")

    if cmd == "validate":
        problems, count = run_validate()
        payload = {"ok": not problems, "mode": "validate", "passed": not problems,
                   "db_path": os.path.abspath(db_path()), "record_count": count}
        if problems:
            payload["error"] = "自检未通过：" + "；".join(problems)
            payload["problems"] = list(problems)
        if args.json:
            out_json(payload)
        else:
            print_validate_human(payload)
        return 0 if not problems else 3

    if cmd == "apps":
        return _run_apps_command(args)

    raise UsageError(f"未知子命令：{cmd}")  # 理论上 argparse 已拦截


def _emit_error(message: str, as_json: bool) -> None:
    """统一错误输出：--json 走 stdout 契约 JSON；否则 stderr 人类可读。"""
    if as_json:
        out_json({"ok": False, "error": message[:500]})
    else:
        print(f"错误：{message}", file=sys.stderr)


def _configure_stdio() -> None:
    """Windows 控制台编码兼容：stdout/stderr 统一 UTF-8，避免中文 GBK 乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    """CLI 入口：返回进程退出码（0 成功 / 2 校验错误 / 3 运行时错误）。"""
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except UsageError as exc:
        _emit_error(str(exc), getattr(args, "json", False))
        return 2
    except RunError as exc:
        _emit_error(str(exc), getattr(args, "json", False))
        return 3
    except sqlite3.Error as exc:
        _emit_error(f"数据库错误：{exc}", getattr(args, "json", False))
        return 3
    except OSError as exc:
        _emit_error(f"运行时错误：{exc}", getattr(args, "json", False))
        return 3


if __name__ == "__main__":
    sys.exit(main())
