# TaskHub —— 工作任务跟踪台（桌面应用 + CLI 双模式）

> [English](README.md) | **[中文](README_ZH.md)**

TaskHub 是一个本地优先的任务跟踪工具：**SQLite 单文件数据库 + Flet 原生桌面界面 + 完整 CLI**，同一数据库三种入口共用，改一处处处可见。零云端依赖、零第三方运行时依赖（CLI 部分），开箱即用。

## 功能特性

### 桌面应用（TaskHub.exe，双击即用）

- **原生桌面窗口**：Flet/Flutter 引擎渲染，非浏览器页面，客户端随包内置、完全离线可用；`--web` 可回退浏览器模式
- **四个视图**：
  - **仪表盘**：KPI 可下钻、状态环图、近期关注、分布条图
  - **任务看板**：四状态列（待办/进行中/已搁置/已完成）+ 右键流转；已完成列仅展示最近 5 条，列底可跳台账查看全部
  - **任务台账**：多维筛选、表头排序、分页、导出 CSV
  - **日程月历**：截止·开始·完成日期聚合展示
- **任务详情弹窗**：状态流转 / 进度备注追加 / 字段编辑 / 完成关闭 / 删除，内容超长自动滚动
- **任务类型与所属项目可自定义**：界面上直接新增/管理，存数据库、随库迁移；删除有在用保护
- **界面中英文一键切换**（仅翻译界面文字，数据值保持原样）；亮色/暗色双主题；快捷键 `F5` 刷新、`Esc` 关闭弹窗
- **桌面应用启动器侧栏**（左侧竖栏）：把常用软件钉到侧栏，右键增/改/排序/启动；GUI 侧栏与 CLI `apps` 命令共用同一张数据表

### CLI（与 GUI 共用同一数据库）

- 所有命令支持 `--json` 输出机器可读契约
- Python 3.10+ 标准库即可运行（sqlite3 / argparse / json），**零第三方依赖**
- 打包版 `TaskHub.exe` 带参数运行即为同一套 CLI

## 优势

1. **AI Agent / 自动化可直接操作**：CLI 输出为单行 JSON（`--json`），字段稳定、退出码语义明确（0 成功 / 2 参数校验错 / 3 运行时错），无需解析人读表格即可编程调用；任务新增自带**同名查重**（归一化比较），close 幂等，适合无人值守的自动化流程反复调用。
2. **本地优先，数据自主**：数据落地单个 SQLite 文件（`data/taskhub.db`），无账号、无云端、无网络依赖；`TASKHUB_DB` 环境变量可随时切换/隔离数据库。
3. **双模式同一数据**：人工在 GUI 里看板拖拽，Agent 在 CLI 里批量增改关，互不冲突、实时互通。
4. **分类字段用户自托管**：任务类型、所属项目存数据库字典表，GUI/CLI 均可增删，删除有在用保护（仍被任务引用的类型/项目不允许删除）。
5. **可验证、可打包**：自带 unittest 测试套件（临时库运行，不污染正式数据）；PyInstaller 一键打包为 Windows 独立目录。

## 快速开始

### 方式一：下载打包版（Windows）

从 [Releases](../../releases) 下载 `TaskHub_vX.Y.Z_win64.zip`，解压后：

- 双击 `TaskHub.exe` → 图形界面（数据库自动初始化，首次运行为空库）
- 命令行 `TaskHub.exe <子命令>` → CLI

### 方式二：源码运行

```bash
pip install flet flet-charts flet-web   # 仅 GUI 需要；CLI 无依赖

python run.py                            # 桌面窗口
python run.py --web                      # 浏览器模式
python taskhub.py init                   # CLI（自动建库）
python -m unittest discover -s tests -v  # 运行测试
```

### 打包桌面版

```bash
pip install pyinstaller
python build_exe.py
# 产物：dist/TaskHub/（TaskHub.exe + _internal + data/）
```

## 数据库位置

- 默认：`<TaskHub>/data/taskhub.db`（首次 `init` 或 GUI 启动时自动创建；任务类型与所属项目为空，由用户自建）
- 环境变量覆盖（测试/多实例隔离）：

```
set TASKHUB_DB=D:\somewhere\other.db       （CMD）
$env:TASKHUB_DB = "D:\somewhere\other.db"  （PowerShell）
export TASKHUB_DB=/somewhere/other.db      （bash）
```

## CLI 命令速查

> 所有命令均支持 `--json`；日期格式统一 `YYYY-MM-DD`。
> 打包版将 `python taskhub.py` 替换为 `TaskHub.exe` 即可。

### init —— 初始化数据库（幂等）

```
python taskhub.py init [--json]
```

自动创建 `data/` 目录、数据表与索引，重复执行无副作用。

### add —— 新增任务

```
python taskhub.py add --title X [--project 其他] [--type 日常事务] [--priority 中]
                     [--start 今天] [--deadline] [--detail] [--source] [--json]
```

- `--title` 必填（业务主键）；新任务状态固定「待办」
- 默认值：项目=其他、类型=日常事务、优先级=中（非法优先级回落中）、开始日期=今天
- `--source` 写入详情首行 `[来源:xxx]`，`--detail` 随后
- **同名查重**：同名（NFKC 归一化）且状态为待办/进行中/已搁置 → 跳过（`action=skipped_duplicate`，退出码 0）；同名已完结 → 正常新增
- `--project` / `--type` 支持自由文本，首次出现自动注册为字典项
- record_id 自动生成 22 位随机串

### list —— 查询任务列表

```
python taskhub.py list [--status 未完结] [--project X] [--keyword X] [--limit 100] [--json]
```

- `--status`：待办 / 进行中 / 已搁置 / 已完成 / **未完结（默认）** / 全部
- `--project`：按所属项目精确匹配（合法值见 `projects`）
- `--keyword`：任务名称模糊匹配，**归一化比较**（全角→半角、去空白、转小写）
- 排序：截止日期升序，空截止排最后；`--json` 时详情截前 200 字

### show —— 查看单条任务详情

```
python taskhub.py show <record_id或任务名> [--title X] [--json]
```

- record_id 优先匹配，未命中按任务名称（归一化）；`--title` 显式按名称
- 多条同名：未完结优先，再按开始日期降序；输出完整详情（不截断）

### update —— 增量更新任务

```
python taskhub.py update <record_id或任务名> [--title X] [--status] [--priority]
                         [--deadline] [--project] [--result] [--note] [--json]
```

- 定位规则同 show
- `--status`（待办/进行中/已搁置/已完成）、`--priority`（高/中/低）、`--deadline` 校验非法即报错；`--project`/`--type` 自由文本自动注册
- **`--note` 追加进度备注**：格式 `[YYYY-MM-DD HH:MM] 备注`，追加到详情末尾，不覆盖历史
- `--result` 非空时改写结果结论；无可更新字段 → 报错（退出码 2）

### close —— 关闭任务

```
python taskhub.py close <record_id或任务名> --result X [--finish-date 今天] [--json]
```

- `--result` 必填；状态→已完成、写入完成日期（默认今天）与结果结论
- **幂等**：已完成任务再 close → `action=skipped_already_done`（退出码 0，不覆盖已有结论）

### stats —— 统计

```
python taskhub.py stats [--json]
```

按状态 / 所属项目 / 优先级分组计数（组内按数量降序）。

### projects —— 所属项目管理（数据库托管）

```
python taskhub.py projects                      # 列出全部所属项目
python taskhub.py projects --add "新项目"       # 新增所属项目
python taskhub.py projects --delete "新项目"    # 删除所属项目
python taskhub.py projects [--json]
```

- 所属项目由用户自建（无内置种子值）；`add`/`update` 时自由文本首次出现自动注册
- **删除保护**：仍被任务使用的项目不允许删除（提示在用条数）

### types —— 任务类型管理（数据库托管）

```
python taskhub.py types                      # 列出全部任务类型
python taskhub.py types --add "新类型"       # 新增任务类型
python taskhub.py types --delete "新类型"    # 删除任务类型
python taskhub.py types [--json]
```

- 任务类型由用户自建（无内置种子值）；自由文本自动注册；删除保护同上

### apps —— 桌面应用启动器管理（GUI 侧栏与 CLI 共用）

```
python taskhub.py apps                                              # 列出全部启动项
python taskhub.py apps --add --name X --path "C:/path/app.exe"      # 新增（--path 必填）
python taskhub.py apps --add --name X --path "..." --args "..." --icon image_path
python taskhub.py apps --update <id> --name X --path X [--args X] [--icon X]
python taskhub.py apps --update <id> --move up|down                 # 上下移动排序
python taskhub.py apps --delete <id>
python taskhub.py apps --launch <id>                                # 启动应用
```

- `--path` 支持 exe / lnk / url / 目录；带 `--args` 时按参数列表启动，否则走 `os.startfile`
- `--add` / `--delete` / `--launch` 为动作开关（无值）；`--update` / `--delete` / `--launch` 需指定 id
- GUI 侧栏与 CLI 共用 `app_launchers` 数据表；老库打开时自动迁移

### import —— 批量导入 JSON（幂等）

```
python taskhub.py import --file <json路径> [--json]
```

- 输入格式：`{"results": [...]}`，中文字段名（任务名称/所属项目/…/结果结论 + record_id）
- 按 record_id 幂等：已存在则更新，不存在则插入；缺 record_id / 任务名称的坏行跳过并记入 `problems`

### validate —— 自检

```
python taskhub.py validate [--json]
```

检查数据库文件、表结构完整性与记录数。通过退出码 0，问题退出码 3。

## JSON 输出契约（--json）

成功（stdout 单行 JSON，保留中文原文）：

```jsonc
{"ok": true, "mode": "add", "action": "created", "record_id": "...", "title": "..."}
{"ok": true, "mode": "add", "action": "skipped_duplicate", "reason": "...", "record_id": "...", "title": "..."}
{"ok": true, "mode": "update", "action": "updated", "record_id": "...", "title": "...", "changed_fields": ["状态", "任务详情"]}
{"ok": true, "mode": "close", "action": "closed", "record_id": "...", "title": "...", "finish_date": "2026-09-15"}
{"ok": true, "mode": "close", "action": "skipped_already_done", "record_id": "...", "title": "..."}
{"ok": true, "mode": "list", "count": 24, "total_in_db": 64, "tasks": [{"record_id": "...", "任务名称": "...", "所属项目": "...", "任务类型": "...", "优先级": "...", "状态": "...", "截止日期": "2026-09-08", "任务详情": "前200字..."}]}
```

失败：

```json
{"ok": false, "error": "错误描述"}
```

## 退出码

| 码 | 含义 | 示例 |
|---|---|---|
| 0 | 成功（含 skipped_duplicate / skipped_already_done 业务跳过） | add 查重跳过、close 已完成 |
| 2 | 参数 / 校验错误 | 非法状态/优先级、日期格式错、记录不存在、close 缺 result、update 无字段 |
| 3 | 数据库 / 运行时错误 | 数据库未初始化、表结构损坏、validate 未通过 |

## 字段与数据表

字段合法值：优先级（高/中/低）、状态（待办/进行中/已搁置/已完成）；任务类型与所属项目为数据库托管的自定义字典（用户自建 + 自由文本自动注册）。

tasks 表（SQLite）：

| 列 | 语义 | 约束 |
|---|---|---|
| record_id | 记录ID | PRIMARY KEY，22 位随机串 |
| title | 任务名称 | NOT NULL，业务主键 |
| project | 所属项目 | 默认 其他 |
| task_type | 任务类型 | 默认 日常事务 |
| priority | 优先级 | 默认 中 |
| status | 状态 | 默认 待办 |
| start_date / deadline / finish_date | 开始/截止/完成日期 | YYYY-MM-DD，空=空串 |
| detail | 任务详情 | 进度备注按行追加 |
| result | 结果结论 | close 必填 |
| created_at / updated_at | 审计时间戳 | 自动维护 |

## 项目结构

```
TaskHub/
├── taskhub.py            # 核心业务 + CLI（全部业务逻辑，GUI 复用其函数）
├── taskhub_gui_flet.py   # 桌面 GUI（Flet 原生窗口 · 双主题 · 中英双语）
├── i18n.py               # GUI 双语文案层（仅显示层，CLI 契约不受影响）
├── run.py                # 统一启动器：无参→桌面窗口（--web→浏览器）；有参→CLI
├── build_exe.py          # PyInstaller 打包（onedir）
├── TaskHub.spec          # PyInstaller 规格文件
├── tests/                # unittest 测试（TASKHUB_DB 指向临时库，不污染正式数据）
└── data/                 # 运行时生成：taskhub.db（SQLite）、lang.json（界面语言偏好）
```

## 常见问题

- **GBK 控制台中文乱码**：CLI 已自动切换 stdout 为 UTF-8；子进程调用方可加 `PYTHONIOENCODING=utf-8` 保险
- **数据库不存在报错**：先 `python taskhub.py init`，或用 `TASKHUB_DB` 指定既有路径
- **add 返回 skipped_duplicate**：库中已有同名未完结任务（归一化比较），属正常业务跳过，退出码仍为 0