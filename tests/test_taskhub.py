# -*- coding: utf-8 -*-
"""test_taskhub.py —— TaskHub CLI 单元测试（unittest，标准库）。

运行方式（项目根目录）：
  python -m unittest discover -s tests -v

测试使用独立临时数据库，通过环境变量 TASKHUB_DB 指定，
绝不污染 data/taskhub.db 正式库。
全部经 CLI 子进程级端到端验证（机器契约最真实），个别纯函数另测。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # TaskHub/
TASKHUB = os.path.join(SCRIPT_DIR, "taskhub.py")
# 云端全量导出：D:\BuddyClaw\04_临时文件(Temp)\taskhub_refactor\cloud_records_raw.json
CLOUD_JSON = os.path.normpath(os.path.join(
    SCRIPT_DIR, "..", "..", "04_临时文件(Temp)",
    "taskhub_refactor", "cloud_records_raw.json"))

PY = sys.executable or "python"


def _re_dirs() -> None:
    """确保 import taskhub 可用（tests 目录在 sys.path 时）。"""
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)


class CLIBase(unittest.TestCase):
    """CLI 子进程测试基类：每个用例独立临时库，互不干扰。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="taskhub_test_")
        self.db = os.path.join(self.tmpdir.name, "test.db")
        self.env = {**os.environ, "TASKHUB_DB": self.db,
                    "PYTHONIOENCODING": "utf-8"}

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # 基础调用封装
    # ------------------------------------------------------------------

    def run_cli(self, *args: str, use_json: bool = False) -> subprocess.CompletedProcess:
        """跑 CLI（默认 --json 便于断言）；返回 CompletedProcess（不抛异常）。"""
        argv = [PY, TASKHUB, *args]
        if use_json:
            argv.append("--json")
        return subprocess.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=self.env, timeout=60,
        )

    def run_json(self, *args: str) -> tuple[dict, subprocess.CompletedProcess]:
        """跑 CLI（自动追加 --json），解析 stdout 单行 JSON。"""
        proc = self.run_cli(*args, use_json=True)
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail(f"stdout 非单行 JSON：rc={proc.returncode}\n"
                      f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        return payload, proc

    def init_db(self) -> None:
        proc = self.run_cli("init", use_json=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def add_task(self, title: str, **kwargs: str) -> dict:
        """add 任务并断言成功，返回契约 JSON。"""
        args = ["add", "--title", title]
        for key, value in kwargs.items():
            args += [f"--{key.replace('_', '-')}", value]
        payload, proc = self.run_json(*args)
        self.assertEqual(proc.returncode, 0, f"{payload} {proc.stderr}")
        self.assertTrue(payload["ok"])
        return payload

    def fetch_row(self, record_id: str) -> dict:
        """直连测试库读一行（英文列名 → dict）。"""
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE record_id = ?", (record_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def parse_note_timestamp(detail: str) -> str:
        """从任务详情提取最近一条备注的时间戳，格式 YYYY-MM-DD HH:MM。"""
        match = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]", detail)
        return match.group(1) if match else ""


class TestInitAndValidate(CLIBase):
    """init 幂等 / validate 自检 / 数据库缺失报错。"""

    def test_init_idempotent_and_validate_pass(self) -> None:
        # init 两次（幂等），validate 通过，记录数 0
        for _ in range(2):
            payload, proc = self.run_json("init")
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "init")
        payload, proc = self.run_json("validate")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["record_count"], 0)

    def test_validate_fails_when_db_missing(self) -> None:
        # 数据库不存在：validate 退出码 3，ok=false
        payload, proc = self.run_json("validate")
        self.assertEqual(proc.returncode, 3)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["problems"])

    def test_list_fails_when_db_missing(self) -> None:
        # 数据库不存在：list 退出码 3（明确指引先 init）
        payload, proc = self.run_json("list")
        self.assertEqual(proc.returncode, 3)
        self.assertFalse(payload["ok"])
        self.assertIn("init", payload["error"])

    def test_projects_command(self) -> None:
        # 字典用户自建，无内置种子值：未初始化 → 空列表
        payload, proc = self.run_json("projects")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["projects"], [])
        # init 之后同样为空列表（不播种）
        self.init_db()
        payload, proc = self.run_json("projects")
        self.assertEqual(payload["projects"], [])
        payload, proc = self.run_json("types")
        self.assertEqual(payload["types"], [])


class TestImport(CLIBase):
    """import 云端导出数据 / 幂等重导 / record_id 保留。"""

    def test_import_full_records(self) -> None:
        self.init_db()
        payload, proc = self.run_json("import", "--file", CLOUD_JSON)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(payload["inserted"], 64)
        self.assertEqual(payload["skipped"], 0)

        # validate：记录数 64
        payload, _ = self.run_json("validate")
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["record_count"], 64)

        # record_id 原样保留、日期截取 T 前段
        with open(CLOUD_JSON, encoding="utf-8") as f:
            cloud = json.load(f)["results"]
        by_id = {r["record_id"]: r for r in cloud}
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tasks").fetchall()
        conn.close()
        self.assertEqual(len(rows), 64)
        for row in rows:
            self.assertIn(row["record_id"], by_id)
            src = by_id[row["record_id"]]
            self.assertEqual(row["title"], src["任务名称"].strip())
            # 日期字段：截取 YYYY-MM-DD，原空值 → 空串
            for col, cn in [("start_date", "开始日期"), ("deadline", "截止日期"),
                            ("finish_date", "完成日期")]:
                expected = (src.get(cn) or "").split("T")[0]
                self.assertEqual(row[col], expected,
                                 f"{row['record_id']}.{col}: {row[col]!r} != {expected!r}")
            # 状态为已完成的 40 条记录：状态正确
            self.assertEqual(row["status"], src["状态"].strip())

    def test_import_idempotent_rerun(self) -> None:
        # 二次导入：64 条全部 update（不再 insert），总数仍 64
        self.init_db()
        self.run_json("import", "--file", CLOUD_JSON)
        payload, proc = self.run_json("import", "--file", CLOUD_JSON)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["inserted"], 0)
        self.assertEqual(payload["updated"], 64)
        payload, _ = self.run_json("validate")
        self.assertEqual(payload["record_count"], 64)

    def test_import_missing_file(self) -> None:
        self.init_db()
        payload, proc = self.run_json("import", "--file", "Z:/不存在.json")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])

    def test_import_rejects_bad_format(self) -> None:
        # 非 results 结构 → 参数/校验错误（退出码 2）
        self.init_db()
        bad = os.path.join(self.tmpdir.name, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"foo": []}, f)
        payload, proc = self.run_json("import", "--file", bad)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])


class TestAddAndDuplicate(CLIBase):
    """add 默认值 / 查重规则（同名未完结跳过、已完结可新增）。"""

    def test_add_with_defaults_and_source(self) -> None:
        self.init_db()
        payload = self.add_task("M006 首件检验跟进", project="M006(YL055)",
                                source="自动化", detail="首件尺寸全检")
        self.assertEqual(payload["action"], "created")
        self.assertRegex(payload["record_id"], r"^[0-9A-Za-z]{22}$")
        row = self.fetch_row(payload["record_id"])
        self.assertEqual(row["title"], "M006 首件检验跟进")
        self.assertEqual(row["project"], "M006(YL055)")
        self.assertEqual(row["task_type"], "日常事务")   # 默认任务类型
        self.assertEqual(row["priority"], "中")          # 默认优先级
        self.assertEqual(row["status"], "待办")          # 新任务默认待办
        self.assertEqual(row["start_date"], datetime_date_today())
        # source 写入详情首行 + detail 第二行
        self.assertEqual(row["detail"], "[来源:自动化]\n首件尺寸全检")
        self.assertEqual(row["deadline"], "")

    def test_add_duplicate_open_task_skipped(self) -> None:
        self.init_db()
        first = self.add_task("M008 修模验证")
        # 同名（仅空格/全角差异）+ 未完结 → 跳过
        payload, proc = self.run_json("add", "--title", "Ｍ008　修模验证　")
        self.assertEqual(proc.returncode, 0)  # 业务跳过退出码仍 0
        self.assertEqual(payload["action"], "skipped_duplicate")
        self.assertEqual(payload["record_id"], first["record_id"])
        self.assertIn("未完结同名任务", payload["reason"])

    def test_add_duplicate_closed_task_allowed(self) -> None:
        self.init_db()
        first = self.add_task("季度评审准备")
        payload, _ = self.run_json("close", first["record_id"], "--result", "评审完成")
        self.assertEqual(payload["action"], "closed")
        # 同名但已完结 → 正常新增
        payload = self.add_task("季度评审准备")
        self.assertEqual(payload["action"], "created")
        self.assertNotEqual(payload["record_id"], first["record_id"])
        # 库内两条同名：一已完成一待办
        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)

    def test_add_duplicate_case_insensitive(self) -> None:
        # 小写/大写差异（NFKC + lower 归一化）也算同名
        self.init_db()
        self.add_task("报告review-2026Q4")
        payload, proc = self.run_json("add", "--title", "报告REVIEW-2026q4")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["action"], "skipped_duplicate")

    def test_add_validation_errors(self) -> None:
        self.init_db()
        # 缺 title：argparse 必填校验
        payload, proc = self.run_json("add")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])
        # 非法日期
        for args in (["add", "--title", "X", "--deadline", "2026/09/08"],
                     ["add", "--title", "X", "--deadline", "2026-13-40"]):
            payload, proc = self.run_json(*args)
            self.assertEqual(proc.returncode, 2, f"{args}: {payload}")
            self.assertFalse(payload["ok"])
        # 自定义任务类型：允许（数据库托管），首次出现自动注册
        payload, proc = self.run_json("add", "--title", "X",
                                      "--type", "自定义类型A")
        self.assertEqual(proc.returncode, 0, f"{payload}")
        payload2, proc = self.run_json("types", "--json")
        self.assertIn("自定义类型A", payload2["types"])
        # 自定义所属项目：允许（数据库托管），首次出现自动注册
        payload, proc = self.run_json("add", "--title", "Y",
                                      "--project", "M012(自定义)")
        self.assertEqual(proc.returncode, 0, f"{payload}")
        payload2, proc = self.run_json("projects", "--json")
        self.assertIn("M012(自定义)", payload2["projects"])

    def test_delete_in_use_guarded(self) -> None:
        # 字典项仍被任务使用时不允许删除（CLI 退出码 2 + 明确提示）
        self.init_db()
        self.add_task("在用类型任务", type="在用类型")
        self.add_task("在用项目任务", project="在用项目")
        # 空闲字典项可正常删除
        payload, proc = self.run_json("types", "--add", "空闲类型")
        self.assertEqual(proc.returncode, 0, f"{payload}")
        payload, proc = self.run_json("types", "--delete", "空闲类型")
        self.assertEqual(proc.returncode, 0, f"{payload}")
        # 在用类型/项目：删除被拦截
        for args in (["types", "--delete", "在用类型"],
                     ["projects", "--delete", "在用项目"]):
            payload, proc = self.run_json(*args)
            self.assertEqual(proc.returncode, 2, f"{args}: {payload}")
            self.assertFalse(payload["ok"])
            self.assertIn("不允许删除", payload["error"])
        # 字典项仍在
        payload2, proc = self.run_json("types", "--json")
        self.assertIn("在用类型", payload2["types"])
        payload2, proc = self.run_json("projects", "--json")
        self.assertIn("在用项目", payload2["projects"])
        # 非法优先级：回落中（不报错）
        payload, proc = self.run_json("add", "--title", "X",
                                      "--priority", "紧急")
        self.assertEqual(proc.returncode, 0)
        row = self.fetch_row(payload["record_id"])
        self.assertEqual(row["priority"], "中")


class TestUpdate(CLIBase):
    """update 增量更新 / note 追加历史保留 / 多条同名定位。"""

    def test_update_fields_and_note_append(self) -> None:
        self.init_db()
        created = self.add_task("客诉8D报告跟进", detail="初稿已发内部评审")
        rid = created["record_id"]

        payload, proc = self.run_json("update", rid, "--status", "进行中",
                                     "--priority", "高", "--deadline", "2026-09-30",
                                     "--project", "M007(YL057)",
                                     "--note", "技术原因已定位")
        self.assertEqual(proc.returncode, 0, payload)
        self.assertEqual(payload["action"], "updated")
        self.assertEqual(payload["mode"], "update")
        self.assertEqual(payload["record_id"], rid)
        self.assertIn("状态", payload["changed_fields"])

        row = self.fetch_row(rid)
        self.assertEqual(row["status"], "进行中")
        self.assertEqual(row["priority"], "高")
        self.assertEqual(row["deadline"], "2026-09-30")
        self.assertEqual(row["project"], "M007(YL057)")
        # 历史详情保留 + 追加时间戳备注
        self.assertIn("初稿已发内部评审", row["detail"])
        stamp = self.parse_note_timestamp(row["detail"])
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertIn("技术原因已定位", row["detail"])
        # 备注行在原详情之后（追加不覆盖）
        self.assertLess(row["detail"].index("初稿已发内部评审"),
                        row["detail"].index("技术原因已定位"))

        # 二次追加：两条备注按顺序保留
        self.run_json("update", rid, "--note", "整改措施已验证")
        row = self.fetch_row(rid)
        self.assertIn("技术原因已定位", row["detail"])
        self.assertIn("整改措施已验证", row["detail"])
        self.assertLess(row["detail"].index("技术原因已定位"),
                        row["detail"].index("整改措施已验证"))

    def test_update_by_title(self) -> None:
        self.init_db()
        created = self.add_task("M010 审厂资料准备")
        payload, proc = self.run_json("update", "--title", "Ｍ010　审厂资料准备",
                                      "--status", "进行中")
        self.assertEqual(proc.returncode, 0, payload)
        self.assertEqual(payload["record_id"], created["record_id"])
        row = self.fetch_row(created["record_id"])
        self.assertEqual(row["status"], "进行中")

    def test_update_picks_open_when_same_title(self) -> None:
        # 同名两条：一已完成一进行中 → 按名称更新命中未完结那条
        self.init_db()
        closed = self.add_task("通用任务A")
        self.run_json("close", closed["record_id"], "--result", "完成")
        reopened = self.add_task("通用任务A")  # 已完结同名可新增
        self.assertEqual(reopened["action"], "created")
        payload, _ = self.run_json("update", "--title", "通用任务A",
                                   "--status", "进行中")
        self.assertEqual(payload["record_id"], reopened["record_id"])
        row = self.fetch_row(closed["record_id"])
        self.assertEqual(row["status"], "已完成")  # 已完成那条未被误改

    def test_update_no_fields_error(self) -> None:
        self.init_db()
        created = self.add_task("M011 试验跟进")
        payload, proc = self.run_json("update", created["record_id"])
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])

    def test_update_not_found(self) -> None:
        self.init_db()
        payload, proc = self.run_json("update", "noSuchId1234567890abcdefgh", "--status", "进行中")
        # ref 先按 record_id 未命中、再按任务名未命中 → 报错
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])

    def test_update_invalid_values(self) -> None:
        self.init_db()
        rid = self.add_task("校验用任务")["record_id"]
        # 非法状态/优先级被 argparse choices 拦截
        for args in (["update", rid, "--status", "全部"],
                     ["update", rid, "--priority", "紧急"],
                     ["update", rid, "--deadline", "09/30/2026"]):
            payload, proc = self.run_json(*args)
            self.assertEqual(proc.returncode, 2, f"{args}: {payload}")
            self.assertFalse(payload["ok"])
        # 自定义所属项目：允许（数据库托管），首次出现自动注册
        payload, proc = self.run_json("update", rid, "--project", "M999")
        self.assertEqual(proc.returncode, 0, f"{payload}")
        payload2, proc = self.run_json("projects", "--json")
        self.assertIn("M999", payload2["projects"])
        # 无字段报错与非法值不混写
        payload, proc = self.run_json("update", rid, "--deadline", "")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])


class TestClose(CLIBase):
    """close 必填校验 / 已完成跳过 / finish_date 写入。"""

    def test_close_success(self) -> None:
        self.init_db()
        rid = self.add_task("M009 批次检验安排")["record_id"]
        payload, proc = self.run_json("close", rid, "--result", "检验合格放行",
                                      "--finish-date", "2026-09-15")
        self.assertEqual(proc.returncode, 0, payload)
        self.assertEqual(payload["action"], "closed")
        self.assertEqual(payload["mode"], "close")
        self.assertEqual(payload["finish_date"], "2026-09-15")
        row = self.fetch_row(rid)
        self.assertEqual(row["status"], "已完成")
        self.assertEqual(row["finish_date"], "2026-09-15")
        self.assertEqual(row["result"], "检验合格放行")

    def test_close_finish_date_default_today(self) -> None:
        self.init_db()
        rid = self.add_task("默认完成日期任务")["record_id"]
        payload, proc = self.run_json("close", rid, "--result", "按期完成")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["finish_date"], datetime_date_today())
        self.assertEqual(self.fetch_row(rid)["finish_date"], datetime_date_today())

    def test_close_requires_result(self) -> None:
        self.init_db()
        rid = self.add_task("缺结果任务")["record_id"]
        payload, proc = self.run_json("close", rid)  # argparse required=True
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])
        payload, proc = self.run_json("close", rid, "--result", "   ")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])

    def test_close_already_done_skipped(self) -> None:
        self.init_db()
        rid = self.add_task("二次关闭任务")["record_id"]
        first, _ = self.run_json("close", rid, "--result", "第一次结论")
        self.assertEqual(first["action"], "closed")
        second, proc = self.run_json("close", rid, "--result", "第二次结论")
        self.assertEqual(proc.returncode, 0)  # 业务跳过退出码 0
        self.assertEqual(second["action"], "skipped_already_done")
        row = self.fetch_row(rid)
        self.assertEqual(row["result"], "第一次结论")  # 结论未被覆盖

    def test_close_invalid_finish_date(self) -> None:
        self.init_db()
        rid = self.add_task("非法日期任务")["record_id"]
        payload, proc = self.run_json("close", rid, "--result", "结论",
                                      "--finish-date", "2026-02-30")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])


class TestListAndShow(CLIBase):
    """list 过滤与排序 / 归一化匹配 / limit / show 详情。"""

    def seed_tasks(self) -> None:
        """注入固定测试数据（跨状态/项目/截止）。"""
        self.init_db()
        self.t1 = self.add_task("M006 来料检验跟进", project="M006(YL055)",
                                priority="高", deadline="2026-09-10",
                                detail="来料抽检中")["record_id"]
        self.t2 = self.add_task("M007 密度分析报告", project="M007(YL057)",
                                priority="中", deadline="2026-09-05",
                                detail="数据分析过半")["record_id"]
        self.t3 = self.add_task("实验室 1#炉对比", project="实验室",
                                priority="低", deadline="",
                                detail="新炉投用对比")["record_id"]
        closed = self.add_task("M006 客诉回复", project="M006(YL055)")
        self.t4 = closed["record_id"]
        self.run_json("close", self.t4, "--result", "已回复客户")
        self.t5 = self.add_task("通用质量审厂准备", project="通用质量",
                                priority="高", deadline="2026-09-01")["record_id"]
        self.run_json("update", self.t5, "--status", "已搁置")

    def test_list_default_open_sorted_by_deadline(self) -> None:
        self.seed_tasks()
        payload, proc = self.run_json("list")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["mode"], "list")
        # 未完结 = 待办(t1,t2,t3) + 已搁置(t5) = 4 条；已完成 t4 不算
        self.assertEqual(payload["count"], 4)
        self.assertEqual(payload["total_in_db"], 5)
        # 截止升序（09-01 → 09-05 → 09-10），空截止(t3)最后
        ids = [t["record_id"] for t in payload["tasks"]]
        self.assertEqual(ids, [self.t5, self.t2, self.t1, self.t3])
        # list 条目字段与原契约一致
        task0 = payload["tasks"][0]
        for key in ("record_id", "任务名称", "所属项目", "任务类型",
                    "优先级", "状态", "截止日期", "任务详情"):
            self.assertIn(key, task0)

    def test_list_all_and_limit(self) -> None:
        self.seed_tasks()
        payload, _ = self.run_json("list", "--status", "全部")
        self.assertEqual(payload["count"], 5)
        # limit 截断：count 为过滤后总数，tasks 截取前 N 条
        payload, _ = self.run_json("list", "--status", "全部", "--limit", "2")
        self.assertEqual(payload["count"], 5)
        self.assertEqual(len(payload["tasks"]), 2)
        # 全部 5 条：有截止的 3 条按日期升序在前，
        # 空截止的 t3/t4 并列最后（次序按 record_id，仅断言集合）
        payload, _ = self.run_json("list", "--status", "全部")
        ids = [t["record_id"] for t in payload["tasks"]]
        self.assertEqual(ids[:3], [self.t5, self.t2, self.t1])
        self.assertEqual(set(ids[3:]), {self.t3, self.t4})

    def test_list_status_and_project_filter(self) -> None:
        self.seed_tasks()
        payload, _ = self.run_json("list", "--status", "已搁置")
        self.assertEqual([t["record_id"] for t in payload["tasks"]], [self.t5])
        payload, _ = self.run_json("list", "--status", "已完成")
        self.assertEqual([t["record_id"] for t in payload["tasks"]], [self.t4])
        payload, _ = self.run_json("list", "--project", "M006(YL055)")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tasks"][0]["record_id"], self.t1)
        # 组合过滤：未完结 + 项目 M007(YL057)
        payload, _ = self.run_json("list", "--project", "M007(YL057)")
        self.assertEqual([t["record_id"] for t in payload["tasks"]], [self.t2])

    def test_list_keyword_normalized(self) -> None:
        self.seed_tasks()
        # 全角/半角/空格/大小写归一化匹配（t1「M006 来料检验跟进」）
        for kw in ("M006", "ｍ006", "M006　来料", "来料检验"):
            payload, _ = self.run_json("list", "--keyword", kw)
            self.assertEqual(payload["count"], 1, f"keyword={kw}")
            self.assertEqual(payload["tasks"][0]["record_id"], self.t1)
        # 关键字只匹配任务名称（t5「通用质量审厂准备」命中「准备」）
        payload, _ = self.run_json("list", "--keyword", "准备")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["tasks"][0]["record_id"], self.t5)

    def test_list_human_output(self) -> None:
        self.seed_tasks()
        proc = self.run_cli("list")  # 无 --json：人类可读表格
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("任务列表", proc.stdout)
        self.assertIn("任务名称", proc.stdout)
        self.assertIn("截止日期", proc.stdout)
        self.assertIn("来料检验跟进", proc.stdout)
        # 已完成任务默认不出现
        self.assertNotIn("客诉回复", proc.stdout)

    def test_show_by_id_and_title(self) -> None:
        self.seed_tasks()
        payload, proc = self.run_json("show", self.t1)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["mode"], "show")
        self.assertEqual(payload["task"]["record_id"], self.t1)
        self.assertEqual(payload["task"]["任务详情"], "来料抽检中")
        # 按名称（归一化）
        payload, proc = self.run_json("show", "--title", "Ｍ006　来料检验跟进")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["task"]["record_id"], self.t1)
        # 人类可读
        proc = self.run_cli("show", self.t1)
        self.assertIn("来料抽检中", proc.stdout)

    def test_show_not_found(self) -> None:
        self.init_db()
        payload, proc = self.run_json("show", "NoSuchRecordId0000000")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(payload["ok"])


class TestStats(CLIBase):
    """stats 分组计数。"""

    def test_stats_grouping(self) -> None:
        self.init_db()
        r1 = self.add_task("任务一", project="M006(YL055)", priority="高")["record_id"]
        self.add_task("任务二", project="M006(YL055)", priority="中")
        self.add_task("任务三", project="实验室", priority="低")
        self.run_json("close", r1, "--result", "完成")
        payload, proc = self.run_json("stats")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["by_status"]["待办"], 2)
        self.assertEqual(payload["by_status"]["已完成"], 1)
        self.assertEqual(payload["by_project"]["M006(YL055)"], 2)
        self.assertEqual(payload["by_project"]["实验室"], 1)
        self.assertEqual(payload["by_priority"]["高"], 1)
        self.assertEqual(payload["by_priority"]["中"], 1)
        self.assertEqual(payload["by_priority"]["低"], 1)
        # 人类可读
        proc = self.run_cli("stats")
        self.assertIn("按状态", proc.stdout)
        self.assertIn("按项目", proc.stdout)


class TestJsonContract(CLIBase):
    """--json 输出契约（与原 taskhub_ops.py 兼容）。"""

    def test_contract_add_update_close_list(self) -> None:
        self.init_db()
        # add
        payload, proc = self.run_json("add", "--title", "契约测试任务",
                                     "--source", "自动化")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["mode"], "add")
        self.assertEqual(payload["action"], "created")
        rid = payload["record_id"]
        # add 查重跳过也走契约
        payload, proc = self.run_json("add", "--title", "契约测试任务")
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["action"], "skipped_duplicate")
        self.assertIn("reason", payload)
        # update
        payload, _ = self.run_json("update", rid, "--note", "进度推进",
                                   "--status", "进行中")
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["mode"], "update")
        self.assertEqual(payload["action"], "updated")
        self.assertIn("changed_fields", payload)
        # close
        payload, _ = self.run_json("close", rid, "--result", "顺利完结")
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["mode"], "close")
        self.assertEqual(payload["action"], "closed")
        self.assertIn("finish_date", payload)
        # close 已完成
        payload, proc = self.run_json("close", rid, "--result", "再关闭")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(payload["action"], "skipped_already_done")
        # list
        payload, _ = self.run_json("list", "--status", "已完成")
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["mode"], "list")
        self.assertIn("count", payload)
        self.assertIn("total_in_db", payload)
        self.assertIn("tasks", payload)
        # 失败契约
        payload, proc = self.run_json("close", "NoSuchId000000000000000000",
                                      "--result", "X")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(payload["ok"], False)
        self.assertIn("error", payload)

    def test_json_single_line(self) -> None:
        # stdout 必须单行 JSON（自动化逐行解析依赖）
        self.init_db()
        proc = self.run_cli("list", use_json=True)
        self.assertEqual(proc.returncode, 0)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        json.loads(lines[0])
        # add 带中文不转义
        proc = self.run_cli("add", "--title", "中文任务Ａ", use_json=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("中文任务Ａ", proc.stdout)


class TestPureHelpers(unittest.TestCase):
    """纯函数单测（不经子进程）。"""

    @classmethod
    def setUpClass(cls) -> None:
        _re_dirs()
        import taskhub
        cls.taskhub = taskhub

    def test_norm_text(self) -> None:
        f = self.taskhub.norm_text
        self.assertEqual(f("Ｍ006　客 诉"), f("m006客诉"))
        self.assertEqual(f("  A B  "), "ab")
        self.assertEqual(f(None), "")
        self.assertEqual(f(""), "")

    def test_fmt_date(self) -> None:
        f = self.taskhub.fmt_date
        self.assertEqual(f("2026-09-05T00:00:00Z"), "2026-09-05")
        self.assertEqual(f("2026-09-05"), "2026-09-05")
        self.assertEqual(f(""), "")
        self.assertEqual(f(None), "")
        self.assertEqual(f("  2026-09-05T00:00:00Z  "), "2026-09-05")

    def test_cut_and_pad_display_width(self) -> None:
        f_cut = self.taskhub.cut_text
        f_pad = self.taskhub.pad
        f_w = self.taskhub.disp_width
        self.assertEqual(f_w("中文ab"), 6)
        # 省略号占 2 宽：8 宽限制下最多放 6 宽内容 + …
        self.assertEqual(f_cut("中文abcdefgh", 8), "中文ab…")
        self.assertEqual(f_cut("短", 8), "短")
        self.assertEqual(f_pad("中", 4), "中  ")
        # 截断宽度 ≥ 4 才能容纳省略号
        self.assertTrue(f_cut("很长的中文字符串内容", 6).endswith("…"))

    def test_check_date(self) -> None:
        f = self.taskhub.check_date
        self.assertEqual(f("2026-09-05", "日期"), "2026-09-05")
        self.assertEqual(f(" 2026-09-05 ", "日期"), "2026-09-05")
        for bad in ("", "2026/09/05", "2026-9-5", "2026-02-30", "abc"):
            with self.assertRaises(self.taskhub.UsageError):
                f(bad, "日期")

    def test_validate_constants(self) -> None:
        t = self.taskhub
        # 字典用户自建：不应再有内置项目/类型种子常量
        self.assertFalse(hasattr(t, "VALID_PROJECTS"))
        self.assertFalse(hasattr(t, "VALID_TYPES"))
        self.assertEqual(t.VALID_PRIORITIES, ["高", "中", "低"])
        self.assertEqual(len(t.VALID_STATUSES), 4)
        self.assertEqual(t.OPEN_STATUSES, {"待办", "进行中", "已搁置"})
        # 生成 ID 唯一性与长度
        import sqlite3 as s3
        conn = s3.connect(":memory:")
        conn.row_factory = s3.Row
        conn.executescript(t.SCHEMA_SQL)
        ids = {t.new_record_id(conn) for _ in range(50)}
        self.assertEqual(len(ids), 50)
        for rid in ids:
            self.assertRegex(rid, r"^[0-9A-Za-z]{22}$")


class TestAppLaunchers(unittest.TestCase):
    """测试快捷应用管理及图标/名称自动提取。"""

    def setUp(self) -> None:
        import taskhub
        self.taskhub = taskhub
        fd, self.db_path = tempfile.mkstemp(suffix=".db", prefix="taskhub_test_apps_")
        os.close(fd)
        os.remove(self.db_path)
        os.environ["TASKHUB_DB"] = self.db_path
        self.conn = taskhub.open_db(create=True)
        taskhub.ensure_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        os.environ.pop("TASKHUB_DB", None)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_extract_app_info_notepad(self) -> None:
        t = self.taskhub
        np = r"C:\Windows\notepad.exe"
        if os.path.exists(np):
            name, icon = t.extract_app_info(np)
            self.assertTrue(bool(name))
            if sys.platform == "win32":
                self.assertTrue(bool(icon))
                self.assertTrue(os.path.exists(icon))

    def test_extract_app_info_fallback(self) -> None:
        t = self.taskhub
        name, icon = t.extract_app_info("non_existent_app.exe")
        self.assertEqual(name, "non_existent_app")
        self.assertEqual(icon, "")

    def test_add_app_auto_info(self) -> None:
        t = self.taskhub
        np = r"C:\Windows\notepad.exe"
        if os.path.exists(np):
            app = t.add_app(self.conn, "", np)
            self.assertTrue(bool(app["name"]))
            self.assertEqual(app["path"], np)
            if sys.platform == "win32":
                self.assertTrue(bool(app["icon_path"]))


def datetime_date_today() -> str:
    """测试辅助：今天的 ISO 日期（与 CLI 同源逻辑）。"""
    import datetime
    return datetime.date.today().isoformat()


if __name__ == "__main__":
    unittest.main(verbosity=2)
