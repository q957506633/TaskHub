# TaskHub — Desktop Task Tracker (GUI + CLI)

> **[English](README.md)** | [中文](README_ZH.md)

TaskHub is a local-first task tracking tool: **single-file SQLite database + Flet native desktop UI + full CLI**. Three entry points share one database — change it anywhere, see it everywhere. Zero cloud dependency, zero third-party dependencies for the CLI, ready to use out of the box.

## Features

### Desktop App (TaskHub.exe, double-click to run)

- **Native desktop window**: rendered by the Flet/Flutter engine, not a browser page; the client is bundled in the package and fully offline. Use `--web` to fall back to browser mode
- **Four views**:
  - **Dashboard**: drill-down KPIs, status donut chart, recent attention, distribution bars
  - **Task Board**: four status columns (To-do / In Progress / On Hold / Done) with right-click transitions; the Done column shows the latest 5 only, with a shortcut to the ledger for all
  - **Task Ledger**: multi-dimension filters, column sorting, pagination, CSV export
  - **Calendar**: aggregated due / start / finish dates
- **Task detail dialog**: status transitions / progress notes / field editing / close / delete, auto-scroll for long content
- **User-managed task types & projects**: add/manage directly in the UI; stored in the database and migrated with it; in-use delete protection
- **One-click UI language switch (Chinese/English)** (translates UI text only, data values unchanged); light/dark themes; shortcuts `F5` refresh, `Esc` close dialog
- **Desktop app launcher sidebar** (left rail): pin frequently used apps, right-click to add/edit/reorder/launch — shared between the GUI sidebar and the CLI `apps` command

### CLI (shares the same database with the GUI)

- Every command supports `--json` machine-readable output
- Runs on Python 3.10+ standard library only (sqlite3 / argparse / json) — **zero third-party dependencies**
- The packaged `TaskHub.exe` run with arguments is the same CLI

## Advantages

1. **Directly operable by AI agents / automation**: CLI output is single-line JSON (`--json`) with stable fields and explicit exit codes (0 success / 2 validation error / 3 runtime error) — no need to parse human-readable tables; `add` has built-in **duplicate checking** (normalized comparison) and `close` is idempotent, ideal for unattended automation calling repeatedly.
2. **Local-first, data ownership**: all data lives in a single SQLite file (`data/taskhub.db`) — no account, no cloud, no network; the `TASKHUB_DB` environment variable switches/isolates databases at any time.
3. **Two modes, one dataset**: humans drag cards on the board while agents batch add/update/close via the CLI — no conflicts, real-time sync.
4. **User-hosted categories**: task types and projects live in database dictionary tables, add/remove via GUI or CLI, with in-use delete protection (types/projects still referenced by tasks cannot be deleted).
5. **Verifiable and packageable**: ships with a unittest suite (runs against a temp database); one-command PyInstaller packaging into a standalone Windows directory.

## Quick Start

### Option 1: Download the packaged build (Windows)

Download `TaskHub_vX.Y.Z_win64.zip` from [Releases](../../releases), extract, then:

- Double-click `TaskHub.exe` → GUI (database auto-initialized; first run starts empty)
- Run `TaskHub.exe <subcommand>` in a terminal → CLI

### Option 2: Run from source

```bash
pip install flet flet-charts flet-web   # GUI only; CLI has no dependencies

python run.py                            # desktop window
python run.py --web                      # browser mode
python taskhub.py init                   # CLI (auto-creates the database)
python -m unittest discover -s tests -v  # run tests
```

### Build the desktop app

```bash
pip install pyinstaller
python build_exe.py
# Output: dist/TaskHub/ (TaskHub.exe + _internal + data/)
```

## Database Location

- Default: `<TaskHub>/data/taskhub.db` (auto-created on first `init` or GUI launch; task types and projects start empty for users to create their own)
- Override via environment variable (testing / multi-instance isolation):

```
set TASKHUB_DB=D:\somewhere\other.db       (CMD)
$env:TASKHUB_DB = "D:\somewhere\other.db"  (PowerShell)
export TASKHUB_DB=/somewhere/other.db      (bash)
```

## CLI Command Reference

> All commands support `--json`; dates use `YYYY-MM-DD`.
> For the packaged build, replace `python taskhub.py` with `TaskHub.exe`.

### init — Initialize database (idempotent)

```
python taskhub.py init [--json]
```

Creates `data/`, tables and indexes; safe to run repeatedly.

### add — Create a task

```
python taskhub.py add --title X [--project 其他] [--type 日常事务] [--priority 中]
                     [--start 今天] [--deadline] [--detail] [--source] [--json]
```

- `--title` required (business key); new tasks start as "To-do"
- Defaults: project=其他, type=日常事务, priority=中 (invalid priority falls back to 中), start date=today
- `--source` writes `[来源:xxx]` as the first detail line, `--detail` follows
- **Duplicate check**: same title (NFKC-normalized) with status To-do/In Progress/On Hold → skipped (`action=skipped_duplicate`, exit code 0); same title already Done → created normally
- `--project` / `--type` accept free text; first occurrence auto-registers a dictionary entry
- record_id is a generated 22-character random string

### list — Query tasks

```
python taskhub.py list [--status 未完结] [--project X] [--keyword X] [--limit 100] [--json]
```

- `--status`: 待办 / 进行中 / 已搁置 / 已完成 / **未完结 (open, default)** / 全部
- `--project`: exact match on project (valid values via `projects`)
- `--keyword`: fuzzy title match with **normalization** (fullwidth→halfwidth, whitespace stripped, lowercased)
- Sort: deadline ascending, empty deadline last; `--json` truncates details to 200 chars

### show — Task details

```
python taskhub.py show <record_id或任务名> [--title X] [--json]
```

- Matches record_id first, then title (normalized); `--title` forces title matching
- Multiple same titles: open tasks first, then start date descending; full details (not truncated)

### update — Incremental update

```
python taskhub.py update <record_id或任务名> [--title X] [--status] [--priority]
                         [--deadline] [--project] [--result] [--note] [--json]
```

- Same lookup rules as show
- `--status` (待办/进行中/已搁置/已完成), `--priority` (高/中/低), `--deadline` validated with errors on invalid values; `--project`/`--type` accept free text with auto-registration
- **`--note` appends a progress note**: format `[YYYY-MM-DD HH:MM] note`, appended to the end of details, history preserved
- `--result` overwrites the result when non-empty; no updatable field → error (exit code 2)

### close — Close a task

```
python taskhub.py close <record_id或任务名> --result X [--finish-date 今天] [--json]
```

- `--result` required; status → Done, writes finish date (default today) and result
- **Idempotent**: closing an already-done task → `action=skipped_already_done` (exit code 0, existing result not overwritten)

### stats — Statistics

```
python taskhub.py stats [--json]
```

Grouped counts by status / project / priority (descending within groups).

### projects — Project dictionary (database-backed)

```
python taskhub.py projects                      # list all projects
python taskhub.py projects --add "NewProject"   # add a project
python taskhub.py projects --delete "NewProject" # delete a project
python taskhub.py projects [--json]
```

- Projects are user-created (no built-in seeds); free text in `add`/`update` auto-registers
- **Delete protection**: projects still referenced by tasks cannot be deleted (reports usage count)

### types — Task type dictionary (database-backed)

```
python taskhub.py types                      # list all types
python taskhub.py types --add "NewType"      # add a type
python taskhub.py types --delete "NewType"   # delete a type
python taskhub.py types [--json]
```

- Task types are user-created (no built-in seeds); free-text auto-registration; same delete protection

### apps — Desktop app launcher management (shared by the GUI sidebar and CLI)

```
python taskhub.py apps                                              # list all apps
python taskhub.py apps --add --name X --path "C:/path/app.exe"      # add (--path required)
python taskhub.py apps --add --name X --path "..." --args "..." --icon image_path
python taskhub.py apps --update <id> --name X --path X [--args X] [--icon X]
python taskhub.py apps --update <id> --move up|down                 # reorder
python taskhub.py apps --delete <id>
python taskhub.py apps --launch <id>                                # launch the app
```

- `--path` accepts exe / lnk / url / directory; with `--args` the app is launched with an argument list, otherwise via `os.startfile`
- `--add` / `--delete` / `--launch` are action switches (no value); `--update` / `--delete` / `--launch` take an id
- The GUI sidebar and CLI share the `app_launchers` table; existing databases are migrated automatically on first open

### import — Bulk JSON import (idempotent)

```
python taskhub.py import --file <json路径> [--json]
```

- Input format: `{"results": [...]}` with Chinese field names (任务名称/所属项目/…/结果结论 + record_id)
- Idempotent by record_id: existing rows updated, new rows inserted; rows missing record_id / 任务名称 are skipped and reported in `problems`

### validate — Self check

```
python taskhub.py validate [--json]
```

Checks database file, table schema integrity and record count. Exit 0 on pass, 3 on problems.

## JSON Output Contract (--json)

Success (single-line JSON on stdout, Chinese preserved):

```jsonc
{"ok": true, "mode": "add", "action": "created", "record_id": "...", "title": "..."}
{"ok": true, "mode": "add", "action": "skipped_duplicate", "reason": "...", "record_id": "...", "title": "..."}
{"ok": true, "mode": "update", "action": "updated", "record_id": "...", "title": "...", "changed_fields": ["状态", "任务详情"]}
{"ok": true, "mode": "close", "action": "closed", "record_id": "...", "title": "...", "finish_date": "2026-09-15"}
{"ok": true, "mode": "close", "action": "skipped_already_done", "record_id": "...", "title": "..."}
{"ok": true, "mode": "list", "count": 24, "total_in_db": 64, "tasks": [{"record_id": "...", "任务名称": "...", "所属项目": "...", "任务类型": "...", "优先级": "...", "状态": "...", "截止日期": "2026-09-08", "任务详情": "first 200 chars..."}]}
```

Failure:

```json
{"ok": false, "error": "error description"}
```

## Exit Codes

| Code | Meaning | Examples |
|---|---|---|
| 0 | Success (including skipped_duplicate / skipped_already_done business skips) | add duplicate skip, close already done |
| 2 | Argument / validation error | invalid status/priority, bad date, unknown record, close without result, update without fields |
| 3 | Database / runtime error | database not initialized, schema damaged, validate failed |

## Fields & Schema

Valid values: priority (高/中/低), status (待办/进行中/已搁置/已完成); task types and projects are user-managed database dictionaries (user-created + free-text auto-registration).

tasks table (SQLite):

| Column | Meaning | Constraints |
|---|---|---|
| record_id | Record ID | PRIMARY KEY, 22-char random string |
| title | Task name | NOT NULL, business key |
| project | Project | default 其他 |
| task_type | Task type | default 日常事务 |
| priority | Priority | default 中 |
| status | Status | default 待办 |
| start_date / deadline / finish_date | Start / due / finish dates | YYYY-MM-DD, empty = empty string |
| detail | Details | progress notes appended line by line |
| result | Result summary | required by close |
| created_at / updated_at | Audit timestamps | maintained automatically |

## Project Structure

```
TaskHub/
├── taskhub.py            # Core business + CLI (all business logic; GUI reuses its functions)
├── taskhub_gui_flet.py   # Desktop GUI (Flet native window · dual themes · bilingual)
├── i18n.py               # GUI bilingual strings (display layer only; CLI contract unaffected)
├── run.py                # Unified launcher: no args → desktop (--web → browser); args → CLI
├── build_exe.py          # PyInstaller packaging (onedir)
├── TaskHub.spec          # PyInstaller spec
├── tests/                # unittest suite (TASKHUB_DB points to a temp database)
└── data/                 # Generated at runtime: taskhub.db (SQLite), lang.json (UI language)
```

## FAQ

- **Garbled Chinese on GBK consoles**: the CLI already reconfigures stdout to UTF-8; subprocess callers can set `PYTHONIOENCODING=utf-8` for safety
- **Database not found error**: run `python taskhub.py init` first, or point `TASKHUB_DB` to an existing path
- **add returns skipped_duplicate**: an open task with the same (normalized) title exists — a normal business skip, exit code is still 0