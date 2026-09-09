#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run.py —— TaskHub 统一启动器（桌面应用 + CLI 双模式）。

打包成 TaskHub.exe 后：
  - 双击 / 无参数运行 → 启动桌面 GUI 窗口
  - 带参数运行       → 完整 CLI（taskhub.py 的全部子命令与 --json 契约）

  TaskHub.exe                       # 打开桌面应用（Flet 原生窗口）
  TaskHub.exe --web                 # 浏览器模式回退
  TaskHub.exe list --json           # CLI 查询
  TaskHub.exe add --title "X" --json
"""

from __future__ import annotations

import os
import sys

# PyInstaller --windowed 模式下 stdout/stderr 为 None，而 flet(uvicorn) 的
# 日志初始化需要调用 isatty()。这里兜底为内存流；控制台/管道场景 stdout
# 存在，不受影响（CLI --json 输出仍走真实管道）。
if sys.stdout is None or sys.stderr is None:
    import io
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(
            io.BytesIO(), encoding="utf-8", line_buffering=True)
    if sys.stderr is None:
        sys.stderr = io.TextIOWrapper(
            io.BytesIO(), encoding="utf-8", line_buffering=True)

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 打包态：优先使用随包分发的 Flet 桌面客户端（_internal/flet_client/flet），
# 实现完全离线自包含；不存在时回退 ~/.flet/client 缓存或首次联网下载。
if getattr(sys, "frozen", False):
    _bundled = os.path.join(getattr(sys, "_MEIPASS", _HERE),
                            "flet_client", "flet")
    if os.path.isfile(os.path.join(_bundled, "flet.exe")):
        os.environ.setdefault("FLET_VIEW_PATH", _bundled)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv == ["--web"]:
        # 无参数 → Flet 原生桌面窗口（默认）；--web → 浏览器模式回退。
        import taskhub_gui_flet
        return taskhub_gui_flet.main(["--web"] if argv else [])
    # 有参数 → CLI（透传给 taskhub.main）
    import taskhub
    return taskhub.main(argv)


if __name__ == "__main__":
    sys.exit(main())
