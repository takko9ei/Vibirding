# Vibirding · 当前开发状态

> 本文件只做冷启动进度摘要。完整目录、数据结构、契约和实施边界以
> [architecture.md](architecture.md) 为唯一事实来源。

最后更新：2026-09-06。

## 当前状态

- 当前分支：`v2`。
- v1 的单条笔记、可选单图、CLI、四工具、权限闸、trace 和 eval 能力保留。
- v2 第 1 步 PostgreSQL 存储替换已实现、验证并提交。
- v2 **2.1 文本拆分已实现、验证并提交**。
- v2 **2.2 照片预处理已实现、验证并提交**。
- v2 **2.3 物种名录与 dry-run 匹配已实现、验证并提交**。
- v2 **2.4 批量确认写入已实现、验证并提交**。
- v2 **2.5 未匹配照片草稿已实现并通过验证，正在等待 review/commit**。

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
| Alembic upgrade/downgrade 与 ORM 一致性 | 24/24 |
| 2.1 文本拆分独立离线测试 | 29/29 |
| 2.2 照片预处理独立离线测试 | 26/26 |
| 2.3 名录与 dry-run 匹配测试 | 36/36 |
| 2.4 批量确认写入测试 | 35/35 |
| 2.5 未匹配照片草稿测试 | 30/30 |
| PostgreSQL 存储与 v1 Log 兼容语义 | 38/38 |
| S1/S3/S4/S6 离线自检 | 101/101 |
| v1 离线 eval | 13/13 |
| 开发库 species | 11,167 条（eBird 当前名录） |
| 开发库 observations | 0 条 |
| 开发库 sessions / photos | 0 / 0 条 |
| 测试遗留临时 schema | 0 个 |

## v2 2.1 本次交付

- 新增 `DraftObservation`，暂不填写 `species_id`，暂不关联照片。
- 新增 `TextSplitService`：一次模型调用取得共享上下文和观测列表，再由程序确定性地下发
  地点、日期、时段并生成草稿编号。
- 空输入、不合规工具调用、空列表、字段类型或日期格式错误均整批失败；未知物种强制标记
  `needs_confirmation`。
- 本切片不访问照片、物种名录或数据库，也没有接入 Web；独立离线测试不需要外部服务。

## v2 2.2 本次交付

- `bird_id` 保留 v1 文本工具契约，同时增加结构化 `identify()` 接口；中文名、英文名、
  学名、懂鸟候选 ID 和 0~100 置信度不再埋在展示文本中。
- `PhotoPreprocessService` 按输入顺序逐张识别；自动结果严格取第一目标的第一候选。
- 未识别和失败分别返回明确状态与 warning；单张失败不影响同批其他照片。
- 本切片不使用 LLM、不访问数据库、不保存照片；离线桩测试无需真实图片或外部 API 配额。

## v2 2.3 本次交付

- 新增 `0002` migration：创建 `species`，并给 `observations` 增加可空 `species_id` 外键。
- 名录来源固定为 eBird Taxonomy，`speciesCode` 是稳定外部 key；真实导入当前 11,167 个物种。
- 名称按“科学名 → 规范中文名 → 别名”逐级精确解析；未映射和多义名称显式返回。
- dry-run 只在文本和照片解析到同一内部 UUID 时配对；同种多图归同一草稿，多个候选草稿时
  不擅自选择。
- 本切片只允许更新 species 名录，不修改草稿、不写 observations、不自动创建未匹配记录。

## v2 2.4 本次交付

- 新增 `0003` migration：创建 `sessions` / `photos`，并给 `observations` 增加可空
  `session_id` 外键；开发库已升级到 `0003`。
- 新增严格确认请求和部分成功响应模型；未明确确认、重复草稿 ID 或重复媒体 ID 均在事务前
  拒绝。
- 批量服务先锁定并认领照片，再创建 session；未知或已被其他 session 认领的媒体会令整批
  回滚。
- 每条 observation 在独立 savepoint 内写入；单条数据失败不影响同批成功项，最终返回
  `created[]` / `failed[]` 并记录 completed / partial / failed 状态。
- 本切片只关联已存在的照片元数据，不读写媒体文件，也不实现 2.5 的未匹配照片自动建记录。

## v2 2.5 本次交付

- 新增 `ParseResult` / `PhotoDraft` 和 `ParseAssemblyService`，把文本草稿、匹配照片及自动生成
  的照片来源草稿组装成统一确认前预览。
- 已匹配照片归入原文本草稿；已可靠解析但文字未提及的照片按 `species_id` 合并，同种多图
  只生成一条 `photo-draft-N` 草稿。
- 自动草稿不猜数量或聚合置信度，并始终标记为需要用户确认；公共地点、日期和时段只有在
  全部文本草稿一致时才继承。
- ambiguous / unmapped / unrecognized / failed 照片不会自动生成记录，原因继续保留在 warnings。
- 本切片不修改输入对象、不调用批量写入服务，也不写 observations / sessions / photos。

保留的查询语义包括：大小写敏感子串、`%`/`_` 按普通字符处理、`start..end`
日期范围、空日期排除、插入顺序和空库返回 `[]`。

## 运行要求

1. `.env` 设置 `DATABASE_URL`；本地默认值见根目录 `.env.example`。
2. `docker compose up -d postgres` 启动数据库。
3. `python -m alembic upgrade head` 升级 schema。
4. `python scripts/import_ebird_taxonomy.py` 导入/更新物种名录。
5. `python -m vibirding "<笔记或查询>"` 运行正式 CLI。

PostgreSQL volume 持久保存数据；`docker compose down -v` 会删除该 volume，不应作为普通
停止命令使用。

## 保留的开发入口

- `scripts/check_s1.py`、`check_s3.py`、`check_s4.py`、`check_s5.py`、`check_s6.py`：分切片回归。
- `scripts/check_v2_db.py`：真实 migration 验证。
- `scripts/check_v2_text_split.py`、`check_v2_photo_preprocess.py`、
  `check_v2_taxonomy_matching.py`、`check_v2_batch_write.py`、
  `check_v2_unmatched_photos.py`：v2 批量切片验证。
- `scripts/import_ebird_taxonomy.py`：从 eBird API 幂等导入当前物种名录。
- `scripts/db_test_support.py`：测试 schema 隔离。
- `scripts/run_s2.py`：Gemini 备用 provider 手动冒烟。
- `scripts/run_s6.py`：预算耗尽和工具失败手动演示。
- `evals/run_evals.py`：离线/在线两档 eval。

正式交付入口始终是 `python -m vibirding`。

## 当前 review 边界

当前只 review 2.5 未匹配照片草稿；通过后提交，再开始 Web/API。
