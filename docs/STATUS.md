# Vibirding · 当前开发状态

> 本文件只做冷启动进度摘要。完整目录、数据结构、契约和实施边界以
> [architecture.md](architecture.md) 为唯一事实来源。

最后更新：2026-09-07。

## 当前状态

- 当前分支：`v2`。
- v1 的单条笔记、可选单图、CLI、四工具、权限闸、trace 和 eval 能力保留。
- v2 第 1 步 PostgreSQL 存储替换已实现、验证并提交。
- v2 **2.1 文本拆分已实现、验证并提交**。
- v2 **2.2 照片预处理已实现、验证并提交**。
- v2 **2.3 物种名录与 dry-run 匹配已实现、验证并提交**。
- v2 **2.4 批量确认写入已实现、验证并提交**。
- v2 **2.5 未匹配照片草稿已实现、验证并提交**。
- Web 的 Neo Brutalism 双页与响应式方向已确认。
- v2 **3.1 FastAPI 媒体上传已实现、验证并提交**。
- v2 **3.2 FastAPI 解析预览已实现、验证并提交**。
- v2 **3.3 FastAPI 批量确认写入已实现、验证并提交**。
- v2 **3.4 FastAPI 观测读取已实现、验证并提交**。
- v2 **3.5 FastAPI 观测编辑已实现、验证并提交**。
- v2 **3.6 FastAPI 观测删除已实现、验证并提交**。
- v2 **3.7 FastAPI 物种查询已实现并验证，当前等待 review**。

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
| 3.1 FastAPI 媒体上传 HTTP 测试 | 33/33 |
| 3.2 FastAPI 解析预览 HTTP 测试 | 38/38 |
| 3.3 FastAPI 批量确认写入 HTTP 测试 | 50/50 |
| 3.4 FastAPI 观测读取 HTTP 测试 | 42/42 |
| 3.5 FastAPI 观测编辑 HTTP 测试 | 30/30 |
| 3.6 FastAPI 观测删除 HTTP 测试 | 28/28 |
| 3.7 FastAPI 物种查询 HTTP 测试 | 21/21 |
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

## v2 3.1 本次交付

- 新增可注入的 FastAPI 应用工厂和 `POST /api/media`，接收 multipart 字段 `photo`。
- JPEG 按 64 KiB 分块读取，边读边限制 2 MiB 大小并计算 SHA-256；文件保存为
  `media/<hash>.jpg`，原始文件名不会参与磁盘路径。
- `photos.content_hash` 作为幂等去重键：新内容返回 201，相同内容返回 200，并复用同一个
  `media_id` 和媒体 URL。
- `/media/<hash>.jpg` 提供只读访问；空文件、伪 JPEG、错误 MIME 和超限文件会返回明确的
  4xx，并清理临时文件。
- 本切片不调用懂鸟、不生成候选物种，也不写 sessions / observations；parse、记录管理和
  React 仍未接入。

## v2 3.2 本次交付

- 新增 `POST /api/parse`，接收文本和 3.1 已上传的 `media_ids`，同步返回统一 `ParseResult`
  预览；支持图文混合、纯文本和纯照片输入。
- 新增只读 `ParsePreviewService`，先验证全部媒体，再按请求顺序串联文本拆分、懂鸟照片预处理、
  eBird 名录映射、图文匹配和未匹配照片草稿组装。
- 未知媒体在任何外部调用前返回 404；重复 ID、空请求和错误结构返回 422；模型或结构化拆分
  失败返回 502。单张照片缺失、未识别或懂鸟失败不会让整批失败，而是进入 warnings。
- 默认 AI 流水线惰性创建，因此只使用媒体上传时不要求提前初始化 DeepSeek/懂鸟 provider。
- parse 不缓存识别候选，不修改 photos，也不写 sessions / observations；用户确认写入仍未接入。

## v2 3.3 本次交付

- 新增 `POST /api/observations`，接收原始文本、全部媒体 ID、编辑后的预览草稿和严格布尔
  `confirmed`；公开模型不允许客户端伪造预留 `user_id`。
- `confirmed=false` 返回 400 且零写入；字符串确认、空草稿列表和文本/媒体同时为空返回 422。
- 未知媒体返回 404、已被其他 session 认领的媒体返回 409、批次内重复 media/draft ID 返回
  400；这些请求级错误全部回滚。
- 接受确认后创建 session 并返回 201。草稿逐条使用 savepoint，完整成功、部分成功和全部失败
  都稳定返回 `created[]` / `failed[]`，session 分别记录 completed / partial / failed。
- 统一了纯照片流程：没有文本但存在媒体时允许确认，session 如实保存空原文；确认写入不会
  删除媒体文件。本切片仍不实现列表、详情、编辑、删除或 species 查询。

## v2 3.4 本次交付

- 新增 `GET /api/observations`，默认返回最新 20 条、最多 100 条；支持地点/物种子串、起止
  日期和组合筛选，返回 `{items}` 列表信封。
- 新增 `GET /api/observations/{id}`，返回完整单条字段、关联照片安全元数据以及可空的 session
  原始整篇笔记和状态；v1 单条记录不会伪造 session。
- 管理列表使用独立 `sequence_no DESC` 读模型，不改变 v1 `Log.query()` 的正序兼容语义；
  列表以一次批量照片查询生成 photo_count/thumbnail，避免 N+1。
- API 不公开 storage_path、provider 候选字段或 user_id；照片 URL 可直接读取，照片按内容哈希
  稳定排序。所有读取均不调用 AI 或外部网络、不修改数据库和媒体文件。

保留的查询语义包括：大小写敏感子串、`%`/`_` 按普通字符处理、`start..end`
日期范围、空日期排除、插入顺序和空库返回 `[]`。

## v2 3.5 本次交付

- 新增 `PATCH /api/observations/{id}`，支持对地点、日期、时段、物种、数量、行为、单条原文、
  置信度和 flags 做局部更新；省略字段保持原值，显式 null 只清除可空字段。
- 记录 ID、创建时间、来源、session、照片归属和列表顺序均不可通过编辑改变；额外或不可编辑
  字段返回 422，未知记录或名录物种返回 404。
- 物种编辑保持展示文字与内部 ID 一致：只改文字会清除旧 ID，只给 ID 会自动采用名录规范
  中文名；未知 ID 会令整次补丁回滚。
- 更新在单个事务和目标行锁内完成，成功直接返回 3.4 的完整详情；不调用模型或外部网络，
  不创建业务行、不修改媒体文件。

## v2 3.6 本次交付

- 新增 `DELETE /api/observations/{id}`；成功返回标准 204 空响应，未知或已经删除的记录返回
  404，非法 UUID 返回 422。
- 删除在单个事务和目标行锁内完成，只删除 observation。数据库现有 `ON DELETE SET NULL`
  外键会解除照片的 observation 关联，但保留照片元数据、原 session 归属和磁盘媒体文件。
- session 的原始笔记与写入状态、同批其他记录、species 名录均保持不变；即使删除 session 的
  最后一条 observation，也不会删除或重算该审计 session。
- 删除后列表、详情与编辑都不再看到目标；媒体 URL 仍可读取。v1 无 session 的兼容记录使用
  同一端点删除，不需要特殊分支。

## v2 3.7 本次交付

- 新增 `GET /api/species?q=&limit=`，默认返回最多 20 条、上限 50 条本地物种建议；缺少或非法
  参数返回 400/422，无匹配返回 200 空列表。
- 同时搜索规范中文名、科学名与 JSONB aliases，大小写不敏感并把 `%`/`_` 当普通字符；输入
  先做 NFKC 和空白规范化。
- 结果按完全匹配、前缀匹配、普通子串的字段优先级排序，再以名称和稳定键排序；只公开
  `species_id`、规范中文名、学名和别名，可直接供 3.5 编辑 API 使用。
- 过滤、排序和 limit 均在 PostgreSQL 内完成，不把完整名录加载进应用内存；开发库 11,167
  条真实名录的 `Corvus` 查询实测约 68 ms，不访问 eBird 或修改数据库。

## 运行要求

1. `.env` 设置 `DATABASE_URL`；本地默认值见根目录 `.env.example`。
2. `docker compose up -d postgres` 启动数据库。
3. `python -m alembic upgrade head` 升级 schema。
4. `python scripts/import_ebird_taxonomy.py` 导入/更新物种名录。
5. `python -m vibirding "<笔记或查询>"` 运行正式 CLI。
6. `python -m uvicorn vibirding.api.app:create_app --factory --reload` 启动当前 Web API。

PostgreSQL volume 持久保存数据；`docker compose down -v` 会删除该 volume，不应作为普通
停止命令使用。

## 保留的开发入口

- `scripts/check_s1.py`、`check_s3.py`、`check_s4.py`、`check_s5.py`、`check_s6.py`：分切片回归。
- `scripts/check_v2_db.py`：真实 migration 验证。
- `scripts/check_v2_text_split.py`、`check_v2_photo_preprocess.py`、
  `check_v2_taxonomy_matching.py`、`check_v2_batch_write.py`、
  `check_v2_unmatched_photos.py`：v2 批量切片验证。
- `scripts/check_v2_media_api.py`：3.1 媒体上传 HTTP、文件和数据库验证。
- `scripts/check_v2_parse_api.py`：3.2 解析预览 HTTP、完整编排和零写入验证。
- `scripts/check_v2_observations_api.py`：3.3 确认写入 HTTP、事务和部分成功验证。
- `scripts/check_v2_observation_reads_api.py`：3.4 观测列表、筛选、详情和零副作用验证。
- `scripts/check_v2_observation_edit_api.py`：3.5 局部编辑、物种一致性、错误回滚和关系不变验证。
- `scripts/check_v2_observation_delete_api.py`：3.6 删除响应、关系解除、审计/媒体保留和 v1 删除验证。
- `scripts/check_v2_species_api.py`：3.7 名称搜索、相关度排序、参数边界和零副作用验证。
- `scripts/import_ebird_taxonomy.py`：从 eBird API 幂等导入当前物种名录。
- `scripts/db_test_support.py`：测试 schema 隔离。
- `scripts/run_s2.py`：Gemini 备用 provider 手动冒烟。
- `scripts/run_s6.py`：预算耗尽和工具失败手动演示。
- `evals/run_evals.py`：离线/在线两档 eval。

正式交付入口始终是 `python -m vibirding`。

## 当前 review 边界

当前只 review 3.7 FastAPI 物种查询；通过并提交后再开始 3.8，不得提前接入 CORS 或 React。
