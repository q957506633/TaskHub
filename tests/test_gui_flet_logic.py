# -*- coding: utf-8 -*-
"""Flet GUI 逻辑回归：无显示环境用 Stub Page 构建全部视图与弹窗。

真实渲染由桌面客户端负责；这里只保证视图/弹窗构建期不抛异常
（曾漏过 _kpi_card 改参后的 NameError，此类错误编译期发现不了）。
使用临时空库（TASKHUB_DB），不触碰 data/taskhub.db。
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _flet_available() -> bool:
    try:
        import flet  # noqa: F401
        return True
    except ImportError:
        return False


class _Win:
    width = 1380
    height = 900
    min_width = 900
    min_height = 620


class _StubPage:
    """duck-type flet.Page：仅覆盖 TaskHubFlet 用到的成员。"""

    def __init__(self):
        self.controls = []
        self.overlay = []
        self.window = _Win()
        self.title = ""
        self.padding = 0
        self.bgcolor = None
        self.theme = None
        self.theme_dark = None
        self.theme_mode = None
        self.on_keyboard_event = None
        self._dialogs = []

    def update(self):
        pass

    def add(self, *controls):
        self.controls.extend(controls)

    def show_dialog(self, dlg):
        self._dialogs.append(dlg)

    def pop_dialog(self):
        if self._dialogs:
            self._dialogs.pop()


@unittest.skipUnless(_flet_available(), "未安装 flet，跳过")
class TestFletGuiLogic(unittest.TestCase):

    def setUp(self):
        import taskhub
        fd, self.db_path = tempfile.mkstemp(suffix=".db",
                                            prefix="taskhub_flet_logic_")
        os.close(fd)
        os.remove(self.db_path)
        os.environ["TASKHUB_DB"] = self.db_path
        conn = taskhub.open_db(create=True)
        try:
            taskhub.ensure_schema(conn)
            ts = "2026-09-01 08:00:00"
            rows = [
                ("todo" + "0" * 19, "写季度质量报告", "通用质量", "报告文档",
                 "高", "待办", "2026-09-01", "2026-09-10", "", "初稿要点",
                 "", ts),
                ("do" + "0" * 21, "处理耳面流痕客诉", "M007(YL057)", "客诉处理",
                 "高", "进行中", "2026-08-20", "2026-09-04", "",
                 "8天库存待处理\nSEM 分析已完成", "", ts),
                ("done" + "0" * 19, "完成8D报告初审", "M006(YL055)", "报告文档",
                 "中", "已完成", "2026-08-01", "2026-08-31", "2026-09-02",
                 "", "结论：通过", ts),
            ]
            for rid, title, proj, typ, pri, st, sd, dl, fd_, det, res, ts_ in rows:
                conn.execute(
                    "INSERT INTO tasks (record_id, title, project, task_type,"
                    " priority, status, start_date, deadline, finish_date,"
                    " detail, result, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, title, proj, typ, pri, st, sd, dl, fd_, det, res,
                     ts_, ts_))
            conn.commit()
        finally:
            conn.close()
        import taskhub_gui_flet as g
        self.g = g
        self.page = _StubPage()
        self.app = g.TaskHubFlet(self.page)

    def tearDown(self):
        os.environ.pop("TASKHUB_DB", None)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_all_views_build(self):
        app = self.app
        app.load_rows(render=False)
        for v in ("dash", "board", "ledger", "cal"):
            app.set_view(v)

    def test_dialogs_build(self):
        app = self.app
        app.load_rows(render=False)
        app.set_view("dash")
        app._dlg_add()                      # 新建任务弹窗（含来源字段行）
        self.page.pop_dialog()
        rid = next(r["record_id"] for r in app.rows
                   if r["status"] == "进行中")
        app._open_detail(rid)               # 详情弹窗
        self.page.pop_dialog()
        app._dlg_edit(rid)                  # 编辑弹窗
        self.page.pop_dialog()
        app._dlg_close_task(rid)            # 完成关闭弹窗
        self.page.pop_dialog()
        app._dlg_app_edit()                 # 添加快捷启动弹窗
        self.page.pop_dialog()
        app._dlg_app_edit({"id": 1, "name": "notepad", "path": "notepad.exe", "icon_path": ""})  # 编辑弹窗
        self.page.pop_dialog()

    def test_theme_toggle_rebuilds(self):
        app = self.app
        app.load_rows(render=False)
        app.set_view("dash")
        app.toggle_theme()
        self.assertTrue(app.dark)
        app.toggle_theme()
        self.assertFalse(app.dark)
        # 字体与双主题设置生效
        self.assertEqual(self.page.theme.font_family, self.g.FONT_FAMILY)
        self.assertIsNotNone(self.page.theme_dark)

    def test_palette_tokens(self):
        g = self.g
        # Apple 设计语言规范原值
        self.assertEqual(g.A["primary"], "#0066cc")
        self.assertEqual(g.A["primary_on_dark"], "#2997ff")
        self.assertEqual(g.A["ink"], "#1d1d1f")
        self.assertEqual(g.A["canvas"], "#ffffff")
        # 圆角规范
        self.assertEqual(g.R["pill"], 9999)
        self.assertEqual(g.R["lg"], 18)

    def test_app_rail_with_launchers(self):
        """验证侧栏添加快捷启动项后能正常构建，且使用 GestureDetector 处理右键。"""
        import flet as ft
        import taskhub
        conn = taskhub.open_db()
        try:
            conn.execute(
                "INSERT INTO app_launchers (name, path, sort_order, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("测试工具", "notepad.exe", 1, "2026-09-10 10:00:00", "2026-09-10 10:00:00")
            )
            conn.commit()
        finally:
            conn.close()

        app = self.app
        app._load_apps()
        self.assertEqual(len(app._apps), 1)
        rail = app._build_app_rail()
        # 验证侧栏构建成功且最后一个项为 GestureDetector
        last_item = rail.content.controls[-1]
        self.assertIsInstance(last_item, ft.GestureDetector)
        self.assertEqual(last_item.tooltip, "测试工具")

    def test_app_avatar_with_real_icon(self):
        """验证拥有实际存在图标文件时，_app_avatar 能正常生成 ft.Image 且无 ImageFit 属性错误。"""
        import flet as ft
        import tempfile
        fd, tmp_png = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            ctl = self.app._app_avatar({"name": "测试", "icon_path": tmp_png})
            self.assertIsInstance(ctl, ft.Container)
            self.assertIsInstance(ctl.content, ft.Image)
        finally:
            if os.path.exists(tmp_png):
                os.remove(tmp_png)

    def test_app_avatar_fallbacks(self):
        """验证无图标或图标不存在时，_app_avatar 能安全降级到文字头像。"""
        import flet as ft
        ctl1 = self.app._app_avatar({"name": "测试", "icon_path": ""})
        self.assertIsInstance(ctl1, ft.Container)
        self.assertIsInstance(ctl1.content, ft.Text)
        self.assertEqual(ctl1.content.value, "测试")

        ctl2 = self.app._app_avatar({"name": "ABC", "icon_path": "not_exists.png"})
        self.assertIsInstance(ctl2, ft.Container)
        self.assertIsInstance(ctl2.content, ft.Text)
        self.assertEqual(ctl2.content.value, "AB")


if __name__ == "__main__":
    unittest.main()
