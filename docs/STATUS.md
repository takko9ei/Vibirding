# Vibirding · 当前开发状态

> 本文件只做冷启动进度摘要。完整目录、数据结构、契约和实施边界以
> [architecture.md](architecture.md) 为唯一事实来源。

最后更新：2026-09-05。

## 当前状态

- 当前分支：`v2`。
- v1 的单条笔记、可选单图、CLI、四工具、权限闸、trace 和 eval 能力保留。
- v2 第 1 步 PostgreSQL 存储替换已实现、验证并提交。
- v2 **2.1 文本拆分已实现并通过本地验证，正在等待 review/commit**；2.2 尚未开始。

## v2 第 1 步已交付

- `docker-compose.yml`：本地 PostgreSQL 16 服务和持久化 volume。
- `alembic.ini`、`migrations/`：Alembic `0001` migration 创建 `observations`。
- `vibirding/db/`：SQLAlchemy engine/session、ORM 和 repository。
- `memory/log.py`：保留 `append()` / `query()` 兼容外观，底层改为 PostgreSQL。
- `append_log`：继续由工具生成机器字段，ID 改为完整 UUID。
- eval：每条用例使用独立 PostgreSQL 临时 schema，结束后删除。

`observations` 当前包含 UUID 主键、identity `sequence_no`、TIMESTAMPTZ、v1 字段、
JSONB `flags` 和可空 `user_id`。本切片未引入批量、照片、物种名录、FastAPI 或 React。

## 当前验证结果

| 验证 | 结果 |
| --- | --- |
| Alembic upgrade/downgrade 与 ORM 一致性 | 10/10 |
| 2.1 文本拆分独立离线测试 | 29/29 |
| PostgreSQL 存储与 v1 Log 兼容语义 | 38/38 |
| S1/S3/S4/S6 离线自检 | 101/101 |
| v1 离线 eval | 13/13 |
| 开发库 observations | 0 条 |
| 测试遗留临时 schema | 0 个 |

## v2 2.1 本次交付

- 新增 `DraftObservation`，暂不填写 `species_id`，暂不关联照片。
- 新增 `TextSplitService`：一次模型调用取得共享上下文和观测列表，再由程序确定性地下发
  地点、日期、时段并生成草稿编号。
- 空输入、不合规工具调用、空列表、字段类型或日期格式错误均整批失败；未知物种强制标记
  `needs_confirmation`。
- 本切片不访问照片、物种名录或数据库，也没有接入 Web；独立离线测试不需要外部服务。

保留的查询语义包括：大小写敏感子串、`%`/`_` 按普通字符处理、`start..end`
日期范围、空日期排除、插入顺序和空库返回 `[]`。

## 运行要求

1. `.env` 设置 `DATABASE_URL`；本地默认值见根目录 `.env.example`。
2. `docker compose up -d postgres` 启动数据库。
3. `python -m alembic upgrade head` 升级 schema。
4. `python -m vibirding "<笔记或查询>"` 运行正式 CLI。

PostgreSQL volume 持久保存数据；`docker compose down -v` 会删除该 volume，不应作为普通
停止命令使用。

## 保留的开发入口

- `scripts/check_s1.py`、`check_s3.py`、`check_s4.py`、`check_s5.py`、`check_s6.py`：分切片回归。
- `scripts/check_v2_db.py`：真实 migration 验证。
- `scripts/db_test_support.py`：测试 schema 隔离。
- `scripts/run_s2.py`：Gemini 备用 provider 手动冒烟。
- `scripts/run_s6.py`：预算耗尽和工具失败手动演示。
- `evals/run_evals.py`：离线/在线两档 eval。

正式交付入口始终是 `python -m vibirding`。

## 下一切片：2.1 文本拆分

只实现“一篇自然语言笔记拆成多个 `DraftObservation`，共享上下文下发”，并增加独立
离线测试。该切片不处理照片、不引入物种名录、不匹配、不写 observations，也不做 Web。
