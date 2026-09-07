# Vibirding v2 · 架构设计文档

> 本文档是 v2 后续开发的**唯一事实来源**。开始任何实现前，先阅读本文、
> `docs/SNAPSHOT-v1.md` 和 `docs/V2-REQUIREMENTS.md`；发生结构或契约变化时，
> 先修改本文，再修改代码。
>
> `SNAPSHOT-v1.md` 只描述 v1 代码的真实历史现状，不是 v2 的设计规范；
> `V2-REQUIREMENTS.md` 记录需求来源和决策过程；`DECISIONS.md` 记录取舍。

---

## 0. 当前阶段与边界

**v2 的 PostgreSQL 存储底座已经完成。** PostgreSQL、SQLAlchemy、Alembic 和 psycopg 3
已经替换 JSONL 持久化，并保留 v1 单条 CLI、工具契约与离线 eval 基线。

**2.1–2.6 和 3.1–3.9 已完成、验证并提交，Web 视觉与响应式方向也已确认。3.10 React
输入流程已经实现并通过自动验收，当前等待 review。** 本切片只接通“记一笔”页面的上传、
解析预览、草稿编辑、照片归属和明确确认写入；review 前不得进入 3.11 管理页能力。

**不迁移旧数据。** v1 真实 `data/` 为空；这次是 schema migration，不是数据 migration。

---

## 1. 产品范围

### 1.1 v2 一句话

用户提交一篇可含多个物种的自然语言观鸟笔记和任意数量照片；系统拆出多条观测、
鉴定照片、按统一物种 ID 完成图文匹配，向用户预览，获得一次确认后将成功记录、
媒体与批次关系写入 PostgreSQL 和本地媒体库。

产品定位：**观察记录本 + 媒体库**。

### 1.2 主流程

```text
文本 + N 张照片
      │
      ├── POST /api/media：哈希去重并保存媒体（独立、可复用）
      │
      ▼
POST /api/parse（只读、无持久化副作用、可重试）
      │
      ├── 文本拆分为 DraftObservation，共享地点/日期下发
      ├── 每张照片经 bird_id 得到首候选与置信度
      ├── 文本和照片均映射到 species_id
      └── 按 species_id 匹配；未匹配照片自动生成新的照片来源草稿记录
      │
      ▼
前端预览全部草稿（含照片自动生成的记录）并允许用户调整
      │
      ▼
POST /api/observations（一次确认、事务化批量写入）
      │
      ├── 创建 session，记录原始笔记与本批媒体
      ├── 成功记录和照片关联落盘
      └── 返回 created[] / failed[]，允许部分成功
```

### 1.3 范围

**v2 做：** PostgreSQL、文件系统媒体库、批量拆分与图文匹配、物种名录与 ID、
FastAPI、React 输入页与记录管理页、记录编辑/删除、批量预览确认、部分失败结果。

**v2 暂不做：** 用户认证与授权（仅预留 `user_id`）、跨提交对话上下文、流式输出、
取消执行、异步 job 队列、多 agent 编排、多 provider 产品化。`/api/parse` 当前同步执行；
其响应结构要预留未来 job 语义，但当前不建立队列。

---

## 2. 设计原则

1. **文档和切片优先**：一次只实现一个可独立验收的切片；每个切片先更新本文、
   再实现、离线自检、review、commit。
2. **副作用分离**：上传、解析预览、确认写入是独立能力。`/api/parse` 不写 observations，
   可安全重试；写入只能由确认后的 `POST /api/observations` 触发。
3. **权限在执行路径内**：v1 的写入闸不后移为 UI 提示。CLI 工具路径保留 registry 内的
   write gate；Web 用“预览 → 明确确认请求 → 写入”表达同一授权边界。
4. **稳定 ID，而非名称猜测**：物种展示名可变、可有别名；文本和图片只在同一
   `species_id` 下自动匹配。映射失败必须可见，不能静默退化为字符串严格匹配。
5. **媒体与数据库各司其职**：照片二进制在 `media/`，以内容哈希命名；数据库保存元数据、
   鉴定与关系。不得按物种名二次改名。
6. **兼容优先的地基替换**：第 1 步只改存储；旧的 `Log.append/query`、工具输入输出、
   MockClient 路径和离线 13/13 基线均不得退化。
7. **显式事务与可观测性**：数据库写入用事务；批量操作逐条汇报成功或失败；保留结构化 trace。
8. **API 是能力，不是页面拼装**：按资源和操作设计，前端只是消费者；普通列表查询直接读 API，
   不经 LLM 复述。

---

## 3. 目标目录结构

以下是 v2 完成态；标记“后续”者不得在第 1 步提前实现。

```text
Vibirding/
├── CLAUDE.md
├── DECISIONS.md
├── README.md
├── requirements.txt
├── docker-compose.yml                    # 第 1 步：本地 PostgreSQL
├── alembic.ini                           # 第 1 步：Alembic 配置
├── .env.example                          # 增加 DATABASE_URL 等非敏感占位
├── docs/
│   ├── architecture.md                   # 本文，唯一事实来源
│   ├── SNAPSHOT-v1.md                    # v1 历史事实快照
│   ├── V2-REQUIREMENTS.md                # 需求与已拍板决定
│   └── STATUS.md
├── migrations/                           # 第 1 步：数据库迁移
├── media/                                # 第 3.1 步：gitignore，SHA-256.jpg 文件名
├── vibirding/
│   ├── schemas.py                        # v1 兼容模型 + 第 2.1/2.2 步批量模型
│   ├── config.py                         # 路径、模型、外部 API、数据库配置
│   ├── db/                               # 第 1 步
│   │   ├── session.py                    # engine / session factory / 注入点
│   │   ├── models.py                     # SQLAlchemy ORM 映射
│   │   └── repository.py                 # ObservationRepository / SpeciesRepository
│   ├── memory/
│   │   └── log.py                        # Log 兼容外观，底层改为 PostgreSQL
│   ├── agent/                            # 继承：loop.py / prompt.py
│   ├── llm/                              # 继承：DeepSeekClient / MockClient
│   ├── harness/                          # 继承：permissions / budget / trace
│   ├── tools/                            # 继承并后续扩展批量能力
│   ├── services/
│   │   ├── parse.py                      # 第 2.1/2.2 步：文本拆分和照片预处理
│   │   ├── taxonomy.py                   # 第 2.3/3.7 步：名录导入、解析和 Web 查询
│   │   ├── matching.py                   # 第 2.3 步：只读图文匹配计划
│   │   ├── assembly.py                   # 第 2.5 步：组装预览并生成未匹配照片草稿
│   │   ├── batch.py                      # 第 2.4 步：确认后的事务化批量写入
│   │   ├── media.py                      # 第 3.1 步：哈希、校验、文件保存和去重
│   │   ├── preview.py                    # 第 3.2 步：读取媒体并编排解析预览流水线
│   │   └── observations.py               # 第 3.4–3.6 步：观测读取、编辑与删除服务
│   └── api/
│       └── app.py                        # 第 3.1–3.7 步：FastAPI 工厂和当前 HTTP 路由
├── frontend/                             # 第 3.9 步起：Vite + React + TypeScript
│   ├── src/
│   │   ├── api/                          # HTTP client 与公开 API 类型
│   │   ├── components/                   # 跨页面共享壳层组件
│   │   ├── pages/                        # 记一笔 / 观察记录
│   │   ├── App.tsx                       # 路由表
│   │   ├── main.tsx                      # React 入口
│   │   └── styles.css                    # 设计 token、全局样式与响应式壳层
│   ├── index.html
│   ├── package.json
│   ├── tsconfig*.json
│   └── vite.config.ts                    # `/api`、`/media` 开发代理
├── evals/                                # 保留 v1 eval，后续新增 v2 用例
└── scripts/                              # 开发期自检与冒烟脚本
```

---

## 4. 数据模型

### 4.1 v1 兼容 Observation

在第 1 步，工具与 agent 仍以如下兼容形状读写一条观测：

```text
Observation
  id: str                         # DB 原生 UUID 序列化为字符串；不再截断为 8 位
  timestamp: str                  # UTC ISO 8601；DB 使用 timestamptz
  place: str | None
  obs_date: str | None            # 第 1 步保持字符串，避免改变 v1 输入语义
  time_of_day: str | None
  species: str | None             # 兼容展示字段；第 2 步起同时关联 species_id
  count: int | None
  behavior: str | None
  raw_note: str
  confidence: float | None
  source: str
  flags: list[str]
```

`AppendLogInput` 仍是 Observation 去掉 `id` / `timestamp` 后的单条输入；
`raw_note` 与 `source` 必填。第 1 步不能收紧 `source`、`flags`、`obs_date` 的 v1 校验。

### 4.2 批量草稿模型

第 2.1 步新增并实际使用 `DraftObservation`；`species_id` 和 `photo_ids` 先保持空值，
为后续物种规范化与照片匹配保留稳定边界。`ParseResult` 在照片流程接入时再启用，
本切片不提前制造空的照片领域对象。

```text
DraftObservation
  client_draft_id: str
  place / obs_date / time_of_day / count / behavior / raw_note
  species_label: str | None        # 展示给用户的名称
  species_id: UUID | None          # 规范化后的匹配键
  confidence / source / flags
  photo_ids: list[UUID]
  needs_confirmation: bool         # 无法规范化、冲突等需用户决定

ParseResult
  draft_observations: list[DraftObservation]
  unmatched_photos: list[PhotoDraft]  # 审计用：每项均已关联自动生成的草稿
  warnings: list[str]
  job_status: "completed"         # 当前同步；为未来异步保留字段

PhotoDraft
  photo_id: UUID
  client_draft_id: str            # 该照片对应的自动生成草稿
```

同种多张照片全部归属同一条 DraftObservation；一张照片多鸟时只使用懂鸟第一候选；
文本数量优先于照片张数。

第 2.2 步新增以下结构；`photo_id` 由调用方提供，本切片不负责创建或持久化媒体记录：

```text
PhotoInput
  photo_id: UUID
  image_path: str

BirdIdCandidate
  species_label: str               # 懂鸟名称字段的中文名首段
  english_name: str | None
  scientific_name: str | None
  confidence: float                # 懂鸟原始 0~100 百分制
  provider_candidate_id: str | None

BirdIdResult
  status: "identified" | "unrecognized" | "failed"
  targets: list[list[BirdIdCandidate]]
  message: str | None

PhotoIdentification
  photo_id: UUID
  candidate: BirdIdCandidate | None # 只取第一目标的第一候选
  status: "identified" | "unrecognized" | "failed"
  warning: str | None
```

第 2.3 步新增以下核心结构；解析结果与配对结果分开，dry-run 不直接改写输入草稿：

```text
SpeciesCatalogEntry
  taxonomy_source / taxonomy_key
  canonical_chinese_name / scientific_name / aliases

SpeciesRecord
  id: UUID
  + SpeciesCatalogEntry 全部字段

SpeciesLookup
  species_label / scientific_name

TaxonomyResolution
  status: "resolved" | "unmapped" | "ambiguous"
  species_id / matched_by / candidate_species_ids / warning

DraftSpeciesResolution
  client_draft_id / resolution

PhotoMatchPlan
  photo_id / resolution
  status: "matched" | "unmatched" | "ambiguous" | "unmapped" | "unrecognized" | "failed"
  client_draft_id / warning

DryRunMatchPlan
  drafts: list[DraftSpeciesResolution]
  photos: list[PhotoMatchPlan]
  warnings: list[str]
```

第 2.4 步新增确认写入结构：

```text
PhotoMetadataInput
  photo_id / content_hash / storage_path / original_filename
  mime_type / size_bytes / candidate

ConfirmedBatch
  raw_text: str
  media_ids: list[UUID]
  observations: list[DraftObservation]
  confirmed: bool
  user_id: UUID | None

CreatedObservation
  client_draft_id / observation_id

FailedObservation
  client_draft_id / reason

BatchWriteResult
  session_id / created[] / failed[]

StoredPhoto
  photo_id / content_hash / storage_path / original_filename
  mime_type / size_bytes / created

MediaUploadResponse
  media_id / hash / url

ParseRequest
  text: str
  media_ids: list[UUID]

ObservationCreateRequest
  text: str
  media_ids: list[UUID]
  observations: list[DraftObservation]
  confirmed: StrictBool

ObservationSummary
  observation_id / timestamp / species_label / species_id / count
  place / obs_date / time_of_day / photo_count / thumbnail_url

ObservationPhoto
  media_id / url / original_filename / mime_type / size_bytes

ObservationSessionInfo
  session_id / created_at / raw_text / status

ObservationDetail extends ObservationSummary
  behavior / raw_note / confidence / source / flags
  photos[] / session

ObservationListResponse
  items: list[ObservationSummary]

ObservationUpdateRequest
  place? / obs_date? / time_of_day? / species_label? / species_id?
  count? / behavior? / raw_note? / confidence? / flags?

SpeciesSearchItem
  species_id / canonical_chinese_name / scientific_name / aliases[]

SpeciesSearchResponse
  items: list[SpeciesSearchItem]
```

### 4.3 PostgreSQL 表设计

第 1 步只创建 `observations` 及数据库基础设施。`species`、`sessions`、`photos` 及关系表
属于后续批量切片，必须通过独立 migration 引入。

| 表 | 阶段 | 关键字段与约束 |
| --- | --- | --- |
| `observations` | 第 1 步 | `id UUID PK`、`sequence_no BIGINT GENERATED BY DEFAULT AS IDENTITY UNIQUE NOT NULL`（只用于稳定复现 v1 插入顺序）、`timestamp TIMESTAMPTZ NOT NULL`、v1 字段、`flags JSONB NOT NULL DEFAULT '[]'`、`user_id UUID NULL`；保留 `species TEXT NULL` 作为兼容展示值。 |
| `species` | 第 2.3 步 | `id UUID PK`（内部匹配键）、`canonical_chinese_name TEXT NOT NULL`、`scientific_name TEXT NULL`、`taxonomy_source TEXT NOT NULL`、`taxonomy_key TEXT NOT NULL`、`aliases JSONB NOT NULL DEFAULT '[]'`；`(taxonomy_source, taxonomy_key)` 唯一。 |
| `sessions` | 第 2.4 步 | `id UUID PK`、`created_at TIMESTAMPTZ`、`raw_text TEXT`、`status TEXT`、`user_id UUID NULL`；一次已确认提交一条，用于回溯整篇笔记的结果。 |
| `photos` | 第 2.4 步 | `id UUID PK`、`content_hash TEXT UNIQUE`、`storage_path`、`original_filename`、`mime_type`、`size_bytes`、第一候选名称/科学名/provider ID/置信度、`species_id NULL`、`session_id NULL`、`observation_id NULL`。一个 observation 可关联多张照片；一张照片只能被一个已确认批次和其中一条 observation 认领。 |

第 2.3 步给 `observations` 增加
`species_id UUID NULL REFERENCES species(id) ON DELETE SET NULL`。匹配一律使用 `species_id`；
兼容 `species` 文本仍保存当时的显示/原始标签。2.3 只建立 schema，不写 observation 值。

第 2.4 步再给 `observations` 增加可空 `session_id` 外键；v1 CLI 创建的旧式单条记录继续为
NULL。`photos` 行代表已经由上传阶段保存到文件系统的媒体元数据；2.4 只认领和关联这些行，
不读取、复制或删除 `storage_path` 对应文件。

第 1 步数据库技术栈固定为 **SQLAlchemy 2.x + Alembic + psycopg 3**。应用和测试均从
`DATABASE_URL` 建立同步连接；本地 Docker 使用独立的 `vibirding` 数据库。Alembic 是 schema
的唯一演进入口，应用启动和正式迁移不得用 `Base.metadata.create_all()` 代替 migration；
`create_all()` 仅允许用于每个离线用例的临时 schema 初始化，且表结构须由 migration 测试
单独验证一致性。

### 4.4 数据一致性

- 确认写入以一个数据库事务提交 session、成功的观测和照片归属；每条观测用 savepoint
  隔离可预期的校验失败，失败记录到 `failed[]`，不能让已成功的条目回滚。
- 媒体文件先按哈希写入，DB 只提交引用；若 DB 失败，孤儿文件可由后续清理任务处理，
  不能伪称事务能覆盖文件系统。
- `user_id` 仅预留可空列；不得在 v2 引入认证系统。

---

## 5. 模块职责

| 模块 | 职责 |
| --- | --- |
| `agent/loop.py` | 保留 v1 的 `model → tool → model` 循环、预算、trace、容错；不感知 PostgreSQL/FastAPI。 |
| `tools/registry.py` | 统一工具注册、pydantic 校验、写入权限闸、执行和 `{ok, output}` 归一化。 |
| `memory/log.py` | 兼容层，只暴露 `append()` / `query()`；从 JSONL 实现替换为 repository。 |
| `db/session.py` | 只负责 engine、session factory、事务边界和测试注入。 |
| `db/models.py` | SQLAlchemy ORM 表映射，不能包含 LLM 或 HTTP 行为。 |
| `db/repository.py` | 查询和持久化语义；不格式化给模型看的文本。 |
| `services/taxonomy.py` | 第 2.3/3.7 步：eBird 名录适配/导入、名称映射，以及给 Web 使用的本地名录查询。 |
| `services/media.py` | 第 3.1 步：流式限制上传大小、校验 JPEG、按 SHA-256 保存，并与 photos 元数据幂等去重。 |
| `services/parse.py` | 第 2.1/2.2 步：文本拆分、照片预处理与草稿构造；解析阶段不写 observations。 |
| `tools/bird_id.py` | 保留 v1 `run()` 文本工具契约，并提供结构化 `identify()` 给批处理服务复用。 |
| `services/matching.py` | 第 2.3 步：按 `species_id` 关联图文，只输出可解释的 dry-run 方案。 |
| `services/batch.py` | 第 2.4 步：验证明确确认、锁定媒体、创建 session，以 savepoint 逐条写入并汇总 created/failed。 |
| `services/assembly.py` | 第 2.5 步：消费 dry-run 结果，复制并补全草稿、合并未匹配照片，输出统一确认前的 `ParseResult`；不写库。 |
| `services/preview.py` | 第 3.2 步：校验并读取 `media_ids`，按请求顺序构造照片输入，编排拆分、识别和预览组装；只读数据库。 |
| `services/observations.py` | 第 3.4–3.6 步：构造观测安全读模型，并在事务内执行单条编辑或删除。 |
| `api/app.py` | 第 3.1 步起：FastAPI 应用工厂、路由装配、依赖注入和 HTTP 错误映射；不直接嵌入业务 SQL。 |
| `frontend/` | 后续：输入预览确认和记录管理；不重复后端规则。 |

---

## 6. 关键契约

### 6.1 继承的 agent / 工具契约

```python
class LLMClient:
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelResponse

ToolManager.execute(name, input, ctx) -> ToolResult
run_agent_turn(messages, tools, llm, permissions, budget, trace, on_event=...) \
    -> tuple[list[dict], str]
permissions.check(tool_name, risk, input) -> "allow" | "deny" | "always"
```

这些契约继续 provider 中立。DeepSeek/OpenAI 特有的消息和 tool-call 翻译只能留在
`llm/deepseek_client.py`；不使用 SDK 自动函数执行。

### 6.2 第 1 步 Log 兼容契约

```python
log.append(obs: Observation) -> None
log.query(place=None, species=None, date_range=None) -> list[Observation]
```

第 1 步必须保留以下 v1 可观察语义：

- `place` / `species` 是大小写敏感的**子串**过滤；SQL 实现必须转义 `%`、`_`，不能意外采用 SQL 通配符语义。
- `date_range` 使用 `"start..end"`；不含 `..` 的值不做日期过滤；有日期过滤时 `obs_date is NULL` 不匹配。
- 结果维持插入顺序；空库返回 `[]`。
- JSONL 的“坏行静默跳过”不再模拟：数据库约束与事务保证不会写出坏行。因为没有历史 JSONL 数据，这不是迁移兼容问题。

`ReadLogTool` / `AppendLogTool` 的工具名、schema、risk、给模型的描述和文本输出在第 1 步不变；
`AppendLogTool` 仍由它生成机器字段，只是 ID 改为完整 UUID 字符串。

### 6.3 第 2.1 步文本拆分契约

```python
TextSplitService.split(
    text: str,
    reference_date: date | None = None,
) -> list[DraftObservation]
```

- 服务通过 provider-neutral 的 `LLMClient.complete()` 做一次模型调用，并声明无副作用的
  `return_text_split` 返回工具；模型必须用该工具返回结构化参数，服务不执行任何外部工具。
- 模型返回 `shared_context`（`place` / `obs_date` / `time_of_day`）和
  `observations[]`。每条 observation 可省略共享字段以继承上下文，也可显式提供自己的值覆盖它。
- `reference_date` 默认取本地当天，仅用于把“今天/昨天”等相对日期解析成 `YYYY-MM-DD`；
  离线测试必须显式传固定日期，避免随运行日变化。
- 服务按原顺序生成 `draft-1`、`draft-2`……作为本次响应内的 `client_draft_id`；
  第 2.1 步固定 `species_id=None`、`photo_ids=[]`，且绝不写数据库。
- 每条 `raw_note` 保存只与该条观测有关的原文片段；`source="user"`。无法确定物种或存在
  歧义时必须令 `needs_confirmation=True`，不得编造物种。
- 空白输入、缺少/重复返回工具调用、错误工具名、空 observations 或不符合 schema 的参数
  都抛出 `TextSplitError`，不返回看似成功的部分结果。

### 6.4 第 2.2 步照片预处理契约

```python
BirdIdTool.identify(image_path: str) -> BirdIdResult
PhotoPreprocessService.preprocess(
    photos: list[PhotoInput],
) -> list[PhotoIdentification]
```

- `BirdIdTool.identify()` 复用现有图片预检、上传和轮询逻辑，直接返回结构化候选；旧的
  `run()` 继续输出给模型阅读的中文文本，不改变工具名、schema、risk 或成功/失败语义。
- 每个懂鸟目标最多保留前三个候选，并将 `中文名|英文名|拉丁名` 拆成独立字段；置信度保留
  懂鸟原始 0~100 百分制，不换算成 0~1。
- 批处理保持输入顺序且每张照片恰有一个结果。一张照片检测出多只鸟时，只取第一目标的
  第一候选；其他候选只停留在 adapter 结果中，不进入自动匹配输入。
- 单张照片失败不得中止其他照片：传输/结构错误输出 `failed + warning`；正常返回但未识别出
  候选输出 `unrecognized + warning`。重复 `photo_id` 整批拒绝，空输入返回空列表。
- 本切片不调用 LLM、不做 taxonomy 映射、不匹配文本、不访问数据库，也不创建/复制/改名照片。

### 6.5 第 2.3 步名录与 dry-run 匹配契约

名录来源固定为 **eBird Taxonomy 当前版本**；当前官方版本为 v2025。通过 eBird API
`GET /v2/ref/taxonomy/ebird?cat=species&fmt=json&locale=zh_SIM` 获取，只导入
`category="species"`；`taxonomy_source="ebird"`，稳定外部键使用 `speciesCode`，中文规范名、
科学名分别使用 `comName` / `sciName`。年度更新通过相同 key 幂等更新，不因名称变化生成新 ID。

```python
EbirdTaxonomyAdapter.fetch_entries() -> list[SpeciesCatalogEntry]
TaxonomyService.import_entries(entries) -> list[SpeciesRecord]
TaxonomyService.resolve_many(lookups) -> list[TaxonomyResolution]
DryRunMatchingService.plan(
    drafts: list[DraftObservation],
    photos: list[PhotoIdentification],
) -> DryRunMatchPlan
```

- 名称匹配先做 Unicode NFKC、首尾清理、连续空白折叠和大小写归一；只做确定性的精确匹配，
  不做模糊猜测。优先级依次为科学名、规范中文名、别名；同一级命中多条时返回 ambiguous。
- 物种名录导入允许更新名称和 aliases，但 `(taxonomy_source, taxonomy_key)` 对应的内部 UUID
  保持不变；同一导入批次出现重复外部 key 时整批拒绝。正式导入入口为
  `python scripts/import_ebird_taxonomy.py`，使用分批 PostgreSQL upsert，避免逐条提交。
- 文本草稿和已识别照片分别解析为 `species_id`。照片只有在该 ID 恰好对应一条文本草稿时
  才输出 matched；没有文本草稿为 unmatched；对应多条文本草稿为 ambiguous。
- 同种多张照片分别指向同一 `client_draft_id`；数量仍以文本为准，dry-run 不读取照片数量。
- 未识别、识别失败、名录未映射和歧义均保留明确状态与 warning，禁止退回中文字符串匹配。
- 本切片允许写入/更新 `species` 名录；不得写 observations，不修改输入草稿的 `species_id` /
  `photo_ids`，不为 unmatched 照片创建草稿。

### 6.6 第 2.4 步批量确认写入契约

```python
PhotoRepository.add(metadata: PhotoMetadataInput) -> None
BatchWriteService.confirm(batch: ConfirmedBatch) -> BatchWriteResult
```

- `confirmed` 必须严格为 `True`；否则在打开数据库事务前抛出 `BatchConfirmationError`，不得
  创建 session、observation 或照片关联。空 observations、重复 client draft ID、重复
  media ID 属于批次级错误，整批拒绝。
- `media_ids` 必须全部对应已存在、尚未被其他 session 认领的 photos 行。确认事务先以
  `SELECT ... FOR UPDATE` 锁定它们，再创建 session 并把这些照片归入本批；未知或已被认领
  的 media ID 属于批次级错误，外层事务整体回滚。
- 每条草稿在独立 savepoint 内验证并写入。草稿引用批次外照片、重复引用已由前一成功草稿
  认领的照片、或引用不存在的 `species_id` 时，仅该草稿进入 `failed[]`；其他草稿继续。
- 成功项生成完整 observation UUID/UTC timestamp，保存 `session_id`、`species_id`、兼容
  species 显示名和 v1 字段；其照片写入 `observation_id`。同一草稿可关联多张照片。
- session 最终状态为 `completed`、`partial` 或 `failed`；即使所有草稿失败，也保留已确认
  的 session 和失败结果用于审计。`created[]` / `failed[]` 始终同时返回。
- 事务外异常回滚整个批次；只有已归一化的逐条领域/约束错误允许部分成功。2.4 不为未使用
  的 media 自动建 observation，那是 2.5 的职责。

### 6.7 第 2.5 步未匹配照片草稿契约

```python
ParseAssemblyService.assemble(
    drafts: list[DraftObservation],
    photos: list[PhotoIdentification],
) -> ParseResult
```

- 服务内部调用第 2.3 步 dry-run 匹配，并复制输入对象后组装结果；不得修改调用方的草稿/
  照片，也不得写数据库。重复 `client_draft_id` 或重复 `photo_id` 整批拒绝。
- 已解析文本草稿补上 `species_id`；匹配成功的照片 ID 归入对应草稿。无法解析或有歧义的
  文本草稿标记 `needs_confirmation=True`，匹配失败原因继续保留在 `warnings`。
- 只有状态为 `unmatched` 且已经解析到唯一 `species_id` 的照片才能自动生成草稿；unmapped、
  ambiguous、unrecognized、failed 照片不得猜测物种或创建记录。
- 同一 `species_id` 的多张未匹配照片合并到一条草稿，顺序由该物种第一张照片在输入中的
  位置决定；草稿 ID 使用不与现有 ID 冲突的 `photo-draft-N`。
- 自动草稿 `source="bird_id"`、`count=None`、`confidence=None`，带
  `auto_created_from_unmatched_photo` flag，并固定 `needs_confirmation=True`。地点、日期、时段
  只有在所有文本草稿的该字段完全一致时才继承，否则留空，禁止取第一条猜测共享上下文。
- `unmatched_photos` 为每张自动处理的照片保留 `photo_id -> client_draft_id` 对应关系；生成的
  草稿与普通文本草稿一起进入统一预览。2.5 本身不调用 2.4 写入服务，用户明确确认后才落库。

### 6.8 HTTP API 契约（后续第 3 步）

```text
POST   /api/media
       multipart photo -> {media_id, hash, url}

POST   /api/parse
       {text, media_ids[]} -> {draft_observations[], unmatched_photos[], warnings[], job_status}

POST   /api/observations
       {text, media_ids[], observations[], confirmed} -> {session_id, created[], failed[]}

GET    /api/observations?limit=&place=&species=&date_from=&date_to=
GET    /api/observations/{id}
PATCH  /api/observations/{id}
DELETE /api/observations/{id}
GET    /api/species?q=
```

`POST /api/parse` 无写 observation 副作用；`POST /api/observations` 是用户确认后的批量写入。
`created[]` 和 `failed[]` 必须始终同时存在，即使其中一个为空。

### 6.9 第 3.1 步 FastAPI 媒体上传契约

```python
MediaStorageService.store(
    stream: BinaryIO,
    original_filename: str,
    mime_type: str,
) -> StoredPhoto

POST /api/media
multipart field: photo
-> 201 MediaUploadResponse             # 新文件
-> 200 MediaUploadResponse             # 相同内容复用
```

- 应用使用 `create_app(session_factory=None, media_dir=None)` 工厂，以便正式运行读取
  `DATABASE_URL` / 根目录 `media/`，测试注入临时数据库 schema 和临时目录。3.1 不启用 CORS，
  后续确定 React 开发/部署来源时再配置明确 allowlist。
- 只接受声明为 `image/jpeg`（兼容 `image/jpg`）且文件头为 JPEG 的非空文件；上限固定为
  2 MiB，与现有懂鸟接口约束一致。读取必须分块并在超过上限时立即失败，不能先把任意大文件
  全部读入内存。
- 服务计算文件字节的 SHA-256，最终文件名固定为 `<hash>.jpg`，不得使用原始文件名拼路径；
  `original_filename` 只保存去除目录后的审计名称。临时文件与最终文件必须都限制在注入的
  media 根目录内。
- `photos.content_hash` 是去重键。同一内容重复上传返回已有 `media_id` 和相同 URL，数据库只
  保留一行，文件系统只保留一份；首次上传返回 201，复用返回 200。
- 数据库保存文件绝对路径、原始名称、规范 MIME 和实际字节数；3.1 不调用懂鸟，不写候选/
  `species_id`，不创建 session 或 observation。
- 返回 URL 为 `/media/<hash>.jpg`，由 FastAPI 静态文件挂载只读提供。非法 MIME 返回 415，
  空文件或伪 JPEG 返回 400，超过上限返回 413；失败不得留下临时文件或 photos 行。
- 文件系统与 PostgreSQL 无法共享事务：文件写成功而 DB 发生不可恢复错误时可能留下哈希命名
  的孤儿文件，后续清理任务可安全识别；不得声称数据库 rollback 能删除文件。

### 6.10 第 3.2 步 FastAPI 解析预览契约

```python
ParsePreviewService.parse(
    text: str,
    media_ids: list[UUID],
) -> ParseResult

POST /api/parse
{"text": str, "media_ids": list[UUID]}
-> 200 ParseResult
```

- `ParseRequest` 禁止额外字段，`text` 与 `media_ids` 都必须出现；允许纯文本或纯照片，但二者
  不能同时为空。一个请求内 `media_ids` 不得重复，结构错误由 FastAPI/Pydantic 返回 422。
- 所有媒体必须先从 `photos` 表查到，未知 ID 返回 404，并且必须发生在调用 DeepSeek 或懂鸟
  之前。数据库结果重新按请求中的 ID 顺序排列，照片处理顺序不能依赖 SQL 返回顺序。
- 有非空文本时只调用一次 `TextSplitService.split()`；纯照片请求不调用 LLM。每个媒体 ID 使用
  数据库中的 `storage_path` 构造 `PhotoInput`，再依次调用 `PhotoPreprocessService`，最后由
  `ParseAssemblyService` 完成名录解析、图文匹配和未匹配照片自动建草稿。
- 整个端点同步执行并返回 `job_status="completed"`。单张照片无法读取、未识别或懂鸟失败时，
  沿用 2.2/2.5 语义，以 warning/状态进入成功的 200 预览，不让其他照片或文本草稿丢失。
- 模型调用失败或模型没有返回合规拆分结构时返回 502；请求自身的批次语义错误返回 400。
  已存在但文件缺失的媒体不伪装成 404，而是作为该照片的识别失败出现在预览 warning 中。
- `create_app(session_factory=None, media_dir=None, parse_service=None)` 允许测试注入完整预览服务；
  正式服务只在首次调用 `/api/parse` 时惰性创建 DeepSeek/懂鸟流水线，因此缺少 AI key 不应
  阻止独立的 `/api/media` 上传能力启动。
- 3.2 只读取 `photos` / `species`：不缓存识别候选，不修改媒体元数据，不创建 session 或
  observation。重复 parse 可以重新计算但不能产生数据库副作用；确认写入仍只属于后续
  `POST /api/observations`。

### 6.11 第 3.3 步 FastAPI 批量确认写入契约

```python
POST /api/observations
{
    "text": str,
    "media_ids": list[UUID],
    "observations": list[DraftObservation],
    "confirmed": StrictBool,
}
-> 201 BatchWriteResult
```

- HTTP 使用独立 `ObservationCreateRequest`，禁止额外字段且不暴露预留的 `user_id`；路由只负责
  将 `text` 映射为内部 `ConfirmedBatch.raw_text` 并调用 `BatchWriteService.confirm()`，不得在
  API 层复制事务或照片归属规则。
- `confirmed` 必须是 JSON 布尔值 `true`；`false` 返回 400，字符串 `"true"` / `"yes"` 等
  宽松真值返回 422。未明确确认时不得创建 session、observation 或媒体关联。
- `observations` 至少一条；支持纯文本和纯照片确认，所以 `text` 可以为空，但此时
  `media_ids` 必须非空。`text` 与 `media_ids` 同时为空、结构/类型错误或空 observations 返回
  422。内部 `ConfirmedBatch.raw_text` 同步放宽为空字符串以保存真实的纯照片原始输入。
- 请求级重复 media/draft ID 返回 400；未知 media ID 返回 404；媒体已属于其他 session 返回
  409。以上批次级失败必须整体回滚，不创建新的 session。
- 一旦批次确认被接收，即创建审计 session 并返回 201。每条草稿继续使用 2.4 的 savepoint
  语义：有效项进入 `created[]`，物种/照片引用等单条错误进入 `failed[]`；部分成功乃至全部
  草稿失败仍是 201，因为对应的 confirmed session 已经创建并记录 partial/failed 状态。
- `created[]` 和 `failed[]` 始终同时出现并保持各自的输入顺序。成功 observation 保存编辑后的
  草稿字段，照片关联到同一 session 和对应 observation；本切片不删除媒体文件。
- `create_app(session_factory=None, media_dir=None, parse_service=None, batch_service=None)` 允许
  HTTP 测试注入固定时间/ID 的写入服务；正式应用直接用同一个 session factory 构造默认
  `BatchWriteService`。该 POST 有副作用，不承诺无 idempotency key 的自动重试安全，前端后续
  必须在提交期间禁用重复点击。

### 6.12 第 3.4 步 FastAPI 观测读取契约

```python
GET /api/observations
    ?limit=20
    &place=<substring>
    &species=<substring>
    &date_from=YYYY-MM-DD
    &date_to=YYYY-MM-DD
-> 200 ObservationListResponse

GET /api/observations/{observation_id}
-> 200 ObservationDetail
-> 404
```

- 列表默认 `limit=20`，范围 1–100；参数类型或日期格式错误返回 422，`date_from > date_to`
  返回 400。空白 place/species 等同未筛选；非空 place/species 对已确认时保存的展示文本做
  大小写敏感子串过滤，并将 `%` / `_` 当普通字符，不能改变 v1 查询语义。
- 列表按 `observations.sequence_no DESC` 返回最新记录，独立于 v1 `Log.query()` 的正序兼容
  契约。3.4 不引入 offset/cursor/total count；响应使用 `{items: [...]}` 信封，给后续分页保留
  扩展空间，但 `items` 只表示本次实际返回值。
- `ObservationSummary` 只提供管理列表所需字段；`species` 数据库兼容列对外命名为
  `species_label`。`photo_count` 是关联照片数，`thumbnail_url` 取按内容哈希稳定排序后的首张
  照片；没有照片时分别为 0 / null。
- 详情补充单条 `raw_note`、behavior/confidence/source/flags、全部关联照片和可空 session。
  session 只公开 ID、创建时间、整篇 `raw_text` 和状态；v1 单条记录返回 `session=null`。
- 照片只公开 `media_id`、`/media/<hash>.jpg` URL、原始文件名、MIME 和大小；不得泄露
  `storage_path`、候选 provider 字段、session/observation 外键或 `user_id`。照片按
  `content_hash` 稳定排序；当前 schema 不承诺还原原始上传顺序。
- 列表使用一次观测查询和一次批量照片查询，禁止逐条 N+1 读取；详情允许分别读取一条观测、
  其照片和可选 session。两个端点都直接查询 PostgreSQL，不调用 LLM/懂鸟/eBird 网络，不修改
  任意数据库行或媒体文件。

### 6.13 第 3.5 步 FastAPI 观测编辑契约

```python
PATCH /api/observations/{observation_id}
Content-Type: application/json
ObservationUpdateRequest
-> 200 ObservationDetail
-> 404  # observation 或请求引用的 species_id 不存在
-> 422  # 空补丁、未知/不可编辑字段、字段类型或日期格式错误
```

- 请求是局部更新：省略字段保持原值；显式 JSON `null` 清空对应可空字段。允许编辑
  `place`、`obs_date`、`time_of_day`、`species_label`、`species_id`、`count`、`behavior`、
  `raw_note`、`confidence`、`flags`。`raw_note` 和 `flags` 不可为 null，但可分别为空字符串和
  空列表；请求至少包含一个允许字段。
- 不允许通过此端点修改 `observation_id`、`timestamp`、`source`、`session`、照片、`user_id`
  或 `sequence_no`；额外字段统一返回 422。3.5 不上传、转移、解除关联或删除媒体文件。
- `obs_date` 非 null 时必须是 ISO `YYYY-MM-DD`，落库继续保存同格式文本。`species_id` 非 null
  时必须引用已有名录行，否则返回 404 且整次更新回滚。
- 为避免展示文字和内部物种键悄悄错配：只提交 `species_label` 而省略 `species_id` 时，更新
  展示文字并自动清空原 `species_id`；只要提交非 null `species_id`，该 ID 就是物种真值，
  展示文字统一采用名录行的规范中文名，即使请求同时给了其他 label；显式提交
  `species_id=null` 只清除规范化关联，`species_label` 是否改变仍由请求决定。
- 服务在一个数据库事务内用行锁读取并更新目标记录；失败不产生部分字段更新。成功后返回与
  3.4 完全相同的 `ObservationDetail`，其中照片和 session 只读回显，记录的 `timestamp`、
  `sequence_no` 及列表顺序保持不变。该端点不调用 LLM/懂鸟/eBird 网络。

### 6.14 第 3.6 步 FastAPI 观测删除契约

```python
DELETE /api/observations/{observation_id}
-> 204  # 成功，无响应体
-> 404  # observation 不存在或已删除
-> 422  # observation_id 不是 UUID
```

- 删除只针对目标 `observations` 行；服务在一个数据库事务内用行锁确认目标仍存在，然后删除。
  重复删除不会伪装成功，第二次返回 404。该端点不接受请求体，也不提供批量删除。
- 目标关联的 `photos` 行和哈希命名媒体文件必须保留。既有外键 `ON DELETE SET NULL` 只把这些
  photo 的 `observation_id` 清空；`session_id` 保持不变，所以原始批次仍可审计，照片也不会被
  自动视为可供另一批次重新认领的全新媒体。
- 目标所属 `sessions` 行、同 session 的其他 observation、`species` 名录和其他业务数据不得
  改动。session 的 completed/partial/failed 表示当时确认写入的结果，不因后续管理删除而重算。
- 成功使用标准 HTTP 204，响应体为空；删除后列表不再返回目标，详情、编辑和再次删除均返回
  404。该端点不调用 LLM/懂鸟/eBird 网络，也不删除或改写媒体文件。

### 6.15 第 3.7 步 FastAPI 物种查询契约

```python
GET /api/species?q=<query>&limit=20
-> 200 SpeciesSearchResponse
-> 400  # q 去除首尾/重复空白后为空
-> 422  # 缺少 q、q 超过 100 字符、limit 不在 1–50 或类型错误
```

- `q` 必填，先做 NFKC Unicode 规范化、折叠连续空白并去除首尾空白；规范化后为空返回 400。
  `limit` 默认 20，允许 1–50。响应使用 `{items: [...]}` 信封；没有匹配是 200 空列表。
- 查询同时覆盖 `canonical_chinese_name`、可空 `scientific_name` 和 `aliases` 数组中的每个别名，
  使用大小写不敏感子串匹配；`%`、`_` 等 SQL 通配符必须按普通字符处理。
- 排序按确定性相关度进行：规范中文名完全匹配、科学名完全匹配、别名完全匹配、规范中文名
  前缀、科学名前缀、别名前缀、普通子串；同级按规范中文名、科学名、taxonomy key 和 UUID
  稳定排序。limit 在排序后截取。
- `SpeciesSearchItem` 只公开 `species_id`、规范中文名、可空科学名和别名，不暴露或要求前端理解
  `taxonomy_source/taxonomy_key`。返回的 `species_id` 可直接用于 3.5 PATCH。
- 查询直接在 PostgreSQL 完成过滤和 limit，不把 11,167 条名录全部加载进应用内存；不调用
  LLM/懂鸟/eBird 网络，不修改名录或任何其他业务表。

---

## 7. 批量处理与权限流程（后续第 2 步）

1. 文本拆分：将一篇笔记拆成多条草稿，地点、日期等共享上下文下发给每条。
2. 照片鉴定：每张照片调用现有懂鸟适配器；只读取第一候选作为该照片的物种候选。
3. 规范化：文本物种和照片候选分别通过 taxonomy service 映射为 `species_id`；任何失败进入
   `warnings` / `needs_confirmation`，不能自动声称匹配成功。
4. 匹配：同一 `species_id` 的所有照片归属同一草稿；未与任何文本物种匹配的照片自动创建
   一条照片来源的 DraftObservation。`unmatched_photos` 保留该来源照片及其自动创建草稿的
   对应关系，供前端解释和审计，而不是等待用户决定是否建记录。
5. 预览确认：前端展示全部草稿（包括自动创建的照片来源记录）、归属照片和警告；用户可调整
   草稿内容，但以一次确认整个批次决定是否落库。
6. 写入：创建 session，逐条持久化；成功的记录与照片照常落盘，失败项精确返回原因。

v1 CLI 的单条 `append_log` 权限闸仍保留，不能用“Web 有确认按钮”倒推删除它。

---

## 8. Web 视觉、页面与响应式规范（后续第 3 步）

### 8.1 视觉语言

前端采用 **Neo Brutalism**，整体感觉是鲜明、直接、带手账感的个人观察工具，而不是传统
企业后台：

- 温暖奶油色作为页面底色，深色文字与结构线；黄色、珊瑚红、青绿、柔紫作为有限的强调色。
- 主要容器和操作使用 2–3px 深色边框、右下无模糊硬阴影和约 10–16px 圆角；避免玻璃拟态、
  渐变阴影和大量无意义装饰。
- 标题使用粗重、紧凑的展示字体，正文与表单使用清晰无衬线字体。鸟类图形只用于品牌和照片
  占位，不让插画压过记录内容。
- 色彩语义保持稳定：黄色表示主操作/当前步骤，青绿表示成功、选中或照片来源，珊瑚红表示
  高注意力操作，柔紫表示辅助状态。状态必须同时有文字或图标，不能只靠颜色表达。
- 所有可操作控件保留明显键盘焦点；移动端点击区域约 44px，输入字号不小于 16px；关键能力
  不得只在 hover 时出现。

### 8.2 全局框架与页面数量

v2 Web **固定两个页面**，不增加 Dashboard、登录、设置或独立详情页：

1. `记一笔`：输入整篇笔记和照片、查看解析预览、一次确认写入。
2. `观察记录`：浏览、筛选、查看、编辑和删除历史观测。

PC 端使用顶部导航以给内容保留最大宽度：左侧为鸟形品牌标识和 `VIBIRDING`，中间是两个
页面入口，右侧只保留轻量帮助/项目信息入口。只有两个导航项时不得引入常驻左侧栏。

移动端沿用同一顶部框架：品牌位于第一行，两个页面入口换到第二行并保持可见；不隐藏为汉堡
菜单。路由只对应上述两个页面，详情、编辑、删除确认和写入结果都是页面内状态。

### 8.3 `记一笔`页面

**PC（宽屏工作台）：** 主体分为约 40% / 60% 两栏。

- 左栏自上而下放置“输入 → 智能整理 → 确认”步骤提示、页面标题、大文本框、已上传照片
  缩略图网格、插入图片区域和“整理/重新整理”按钮。
- 照片缩略图必须展示上传中、成功、失败和移除状态；修改文字后重新解析不要求重新上传照片。
- 右栏顶部显示“确认观察记录”和草稿数量；下方按原顺序展示 observation 草稿卡片。
- 草稿卡片左侧是醒目序号，中部是物种、数量、地点、日期/时段与照片，右侧是“来自文字”或
  “照片生成”来源标签。无法映射、存在歧义和照片自动生成的记录在卡片内显示可见警告。
- 用户能在预览中修改草稿字段和照片归属。底部操作区显示即将写入的记录/照片数量，并提供
  “继续修改”和唯一主操作“确认写入 N 条”；未确认不得调用写入 API。

解析是同步长操作：执行期间步骤停在“智能整理”，提交按钮进入忙碌状态并阻止重复请求；失败时
保留原文本和已上传媒体，允许直接重试。确认后的 completed / partial / failed 结果在右栏就地
替换预览，不创建第三个结果页面；部分失败必须同时展示成功项与每条失败原因。

自然语言查询也从本页输入，但能确定为普通列表查询时直接调用资源 API。例如“最近 10 条”对应
`GET /api/observations?limit=10`，不让 LLM 查询数据库后再复述。

### 8.4 `观察记录`页面

**PC：** 页面标题与“记一笔”按钮位于顶部；其下是一整行高辨识度筛选栏，包含物种/地点
搜索、开始日期、结束日期和筛选操作。内容区分为约 65% / 35%：

- 左侧是记录列表。每行显示首张照片或占位图、物种、日期/时段、地点、数量和照片数；选中行
  使用完整背景、文字和边框共同表达选中状态。
- 右侧是所选记录详情，展示物种、全部关联照片、数量、地点、日期、时段、本次 session 的
  原始笔记以及编辑/删除操作。
- 编辑使用当前页抽屉或对话框；删除必须经过明确二次确认。详情不建立独立路由。
- 空列表、筛选无结果、加载失败和删除失败都要有页面内可恢复状态，不能只弹瞬时提示。

跨提交“修改刚才那条”不交给 agent 猜测，统一通过管理页的显式 PATCH/DELETE 操作完成。

### 8.5 响应式重排

响应式不是把 PC 页面等比例缩小，而是保持相同信息优先级后重新排列：

- `> 850px`：采用上述 PC 双栏结构；宽屏下输入页约 40/60，管理页约 65/35。
- `561–850px`：顶部导航换行；输入区置于预览区上方；记录详情置于列表下方；筛选栏允许两列。
- `<= 560px`：页面左右内边距收紧但保留粗边框/硬阴影；所有主区域单列，筛选字段和底部操作
  按钮全宽排列。点击记录后用全宽详情层/抽屉显示详情，仍留在“观察记录”路由。
- 草稿和记录的关键信息不得横向滚动；照片网格可减少列数。只有确实无法压缩的数据表才允许
  局部横向滚动。
- 实现验收至少覆盖 1024px、736px 和 360px；三个宽度均不得出现页面级横向溢出、文本遮挡、
  操作按钮被裁切或必须依靠 hover 才能完成的流程。

### 8.6 前端组件边界

React 实现应以共享设计 token 和可复用业务组件表达上述设计，至少包含：应用顶部框架、步骤
提示、笔记编辑器、照片网格、草稿卡片、警告/结果提示、筛选栏、记录列表、记录详情和确认
对话框。PC 与移动端使用同一组件和数据契约，通过 CSS 布局重排，不维护两套页面实现。

前端不得复制后端领域规则：物种解析、匹配、部分成功、媒体归属和确认权限均以后端响应为准；
前端只负责输入、状态展示、用户编辑和明确操作。

### 8.7 第 3.9 步 React 基础工程契约

- 前端独立位于 `frontend/`，使用 Vite + React + TypeScript 和 npm lockfile；路由使用
  React Router。固定 `/` 为“记一笔”，`/observations` 为“观察记录”，未知路径回到 `/`。
- 两个页面本切片只实现可辨认的工作区骨架与静态示例状态：共用顶部品牌/导航，PC 呈双栏，
  736px 与 360px 按 8.5 重排。不得在本切片调用 API、保存表单或伪造已经完成的业务结果。
- 全局颜色、边框、圆角、硬阴影、间距、字体、焦点环和容器宽度集中为 CSS custom properties；
  页面不得各自复制一套视觉常量。主文字不小于 16px，常用标签不小于 14px。
- `src/api/types.ts` 映射 3.1–3.7 已冻结的公开 HTTP 数据结构；`src/api/client.ts` 只负责
  base URL、JSON/FormData 请求、204 空响应和统一 `ApiError`，不得包含物种匹配等领域规则。
- 浏览器请求统一使用相对路径。Vite 开发服务器将 `/api` 与 `/media` 代理到
  `VITE_API_TARGET`（默认 `http://127.0.0.1:8000`），因此本切片不在 FastAPI 开放 CORS。
- `npm run typecheck` 与 `npm run build` 必须通过；保留 v1 离线 eval 13/13。3.9 本身不得
  接入上传、parse、确认写入、列表加载、编辑或删除交互。

### 8.8 第 3.10 步 React 输入流程契约

- `记一笔`使用同一页面内的四种互斥主状态：初始输入、解析中/解析错误、草稿预览、写入结果。
  原始文字和已成功上传的媒体 ID 是本次工作区的源输入；parse 失败不得清空它们，用户可以直接
  重试。文字改动或照片增删只把已有预览标记为“需要重新整理”，不会重复上传仍保留的照片。
- 照片选择支持一次多选 JPEG。前端先检查 MIME、扩展名与 2 MiB 上限以快速提示，但后端仍是
  最终校验者；每张照片独立调用 `POST /api/media`，并独立展示上传中、成功、失败和移除状态。
  只有成功上传的 `media_id` 会进入 parse/confirm 请求，单张失败不阻止其余输入继续。
- 整理按钮仅在非空文字或至少一张成功照片存在、且没有正在上传/解析/写入时可用。点击后调用
  `POST /api/parse`，同步等待期间显示当前步骤和忙碌文案并禁止重复提交；纯文本、纯照片、混合
  输入使用同一请求形状。全局 warnings 与每条草稿的 flags/`needs_confirmation` 都必须可见。
- 草稿按后端顺序显示并可编辑 place、obs_date、time_of_day、species_label、count、behavior 和
  raw_note；修改 species_label 时清空该草稿旧 `species_id` 并标记待确认，避免把新展示名静默
  绑定到旧物种 ID。`source`、confidence 与 client_draft_id 只展示不手改。
- 每张成功照片在预览中可选择归属某一草稿或“不写入任何草稿”。前端由这一选择重建每条草稿
  的 `photo_ids`，不自行执行物种匹配规则；同一照片最多属于一条草稿。未分配照片仍保留在批次
  `media_ids` 中供审计，并在确认区明确计数。
- 只有草稿预览状态显示“确认写入 N 条”主操作；点击这一明确操作后才向
  `POST /api/observations` 发送原始 text、全部成功 media IDs、当前编辑后的 observations 和
  `confirmed: true`。写入期间禁用再次确认；成功响应后用结果面板替换草稿，分别显示 created 与
  failed，覆盖 completed、partial 和 failed 三种结果，不把部分失败伪装成整体成功。
- 上传、parse 和 confirm 的错误都在对应区域持久显示可恢复提示，不能只用瞬时 toast。由于确认
  API 无 idempotency key，网络结果不明确时不得自动重试写入；保留草稿并让用户自行决定下一步。
- 组件边界至少拆为 `NoteEditor`、`PhotoGrid`、`DraftCard` 和 `WriteResultPanel`；页面负责状态编排，
  API client 继续只负责 HTTP。前端测试通过可注入的 client 覆盖纯文本、纯照片、混合、上传失败、
  parse 失败重试、草稿/照片编辑、显式确认、部分成功和 pending 防重复提交。

---

## 9. 测试与验收

### 第 1 步 PostgreSQL

- Docker 本地 PostgreSQL 能创建 schema 并执行 migration。
- 数据库驱动使用 psycopg 3；migration 使用 Alembic，`alembic upgrade head` 是本地建表入口。
- `append_log` / `read_log` 的现有工具契约不变；CLI 不需改成交付入口以外的形态。
- 每个 eval 用例使用独立临时 schema，结束后删除；不能污染开发 schema，也不能依赖 JSONL。
- v1 离线 eval 仍为 **13/13**；现有离线自检全部通过。
- 覆盖 UUID、`flags JSONB`、空库、子串查询、日期范围、事务失败等存储测试。

### 第 2 步批量与匹配

- 多条拆分及共享地点/日期下发正确。
- 同种多图、数量冲突、首候选、多种/未匹配照片、物种映射失败均有离线用例。
- 部分成功的 `created[]` / `failed[]` 可复现；v1 单条用例不退化。

### 第 2.6 步 v2 固定 eval

- `V2-REQUIREMENTS.md` 第 6 节原本明确包含第 2 步的第六小步；此前领域脚本验证了各服务，
  但固定 `evals/` 数据集仍只有 v1 的 13 条，因此该项不能记为已完成。
- 新增 `evals/v2_tasks.yaml`、`evals/v2_answers.yaml` 与 `evals/run_v2_evals.py`。固定 6 条离线
  用例覆盖多物种拆分、共享上下文、同种多图、按 `species_id` 图文匹配、未匹配照片自动成
  草稿、多个同种文本草稿，以及 ambiguous/unmapped/unrecognized/failed 等可见失败。
- `v2_tasks.yaml` 只保存输入及固定的模型/照片 provider fixture；正式 2.1–2.5 服务先执行，
  `v2_answers.yaml` 只在执行完成后参与评分，不能用答案反向合成被测服务的输出。
- v2 eval 默认只使用 MockClient、provider stub 与临时 PostgreSQL schema，不调用 DeepSeek、
  懂鸟或 eBird 网络，不污染开发库；逐例输出结果并汇总通过率。
- 验收要求 v2 固定用例全部通过、v1 离线 eval 仍为 13/13，并重跑 2.1–2.5 领域回归。该切片
  不修改生产 API、数据库 schema 或 React 页面。

### 第 3 步 Web

- 先用 HTTP 客户端覆盖 API，再接 React。
- 验证 parse 可重试且不写 observations；未确认不能创建记录；确认后才创建 session、记录和关联。
- React 只包含“记一笔 / 观察记录”两个页面；覆盖 loading、空状态、错误、部分成功、编辑和
  删除确认。
- 在 1024px、736px、360px 验证响应式布局、键盘操作和可见焦点，不得出现页面级横向溢出。
- 3.1 单独覆盖媒体 HTTP：新上传 201、重复内容 200、URL 可读、MIME/空文件/伪 JPEG/大小
  拒绝、文件与数据库去重，以及所有失败路径不残留临时文件。
- 3.2 单独覆盖解析 HTTP：纯文本、纯照片、图文匹配、未匹配照片建草稿、单图失败 warning、
  请求顺序、未知/重复媒体、上游模型失败，并确认 photos/sessions/observations 均无写入变化。
- 3.3 单独覆盖确认写入 HTTP：未确认零写入、完整成功、部分/全部失败、纯文本/纯照片、
  未知/已认领/重复媒体、严格布尔确认和 created/failed 稳定响应。
- 3.4 单独覆盖观测读取 HTTP：最新优先、limit/地点/物种/日期筛选、字面量通配符、空结果、
  详情照片/session、v1 无 session 记录、404/400/422、内部字段不泄露和零写入副作用。
- 3.5 单独覆盖观测编辑 HTTP：单字段/多字段/显式 null、ISO 日期、物种关联一致性、空补丁、
  未知/不可编辑字段、未知 observation/species、事务回滚、照片/session/身份与列表顺序不变。
- 3.6 单独覆盖观测删除 HTTP：204 空响应、未知/重复/非法 ID、列表和详情消失、同 session 其他
  记录保留、照片仅解除 observation 关联、session/物种/文件保留，以及 v1 无 session 记录删除。
- 3.7 单独覆盖物种查询 HTTP：三类名称字段、完全/前缀/子串排序、大小写/Unicode/空白、字面量
  通配符、limit、空结果、400/422、公开字段边界，以及零网络和零数据库写入。
- 3.8 在独立临时 schema 与媒体目录中启动真实 Uvicorn，通过真实 loopback HTTP 连续执行
  `media -> parse -> observations POST -> observations GET/detail -> species -> PATCH -> DELETE`。
  解析阶段使用离线确定性 provider stub，但必须经过正式拆分、照片预处理、taxonomy、匹配和
  组装服务；不得调用真实 DeepSeek/懂鸟/eBird，不得污染开发库或消耗配额。
- 3.8 核对 OpenAPI 已登记 8 个方法/路径组合、关键请求/响应 schema 和状态码；核对未确认零
  写入、parse 零写入、确认后的 session/photo/observation 关系、编辑关系不变、删除后媒体与
  session 保留，以及最终临时 schema/目录清理。
- 3.8 还必须重新运行 3.1–3.7 HTTP 回归、2.1–2.5 服务回归、migration、v1 自检和离线 eval。
  验收中发现缺陷可以在本切片修复并回归，但不得借机增加新 API。

---

## 10. 唯一权威实施计划

本表是后续切片编号、顺序、边界和状态的唯一执行清单。`V2-REQUIREMENTS.md` 决定产品需求，
本文把需求落实为当前契约；如果二者发生冲突，先按需求修正本文，禁止靠对话临时改号。
`STATUS.md` 只记录本表的执行结果，README 只提供使用说明，二者都不能另立开发顺序。

当前执行顺序固定为：**review/提交 3.10 → 3.11 → 3.12 → 4**。
已经提交的切片不重做；每次只进入表中第一个未完成切片。

| 切片 | 状态 / 后续次序 | 只做什么 | 完成与停止条件 |
| --- | --- | --- | --- |
| 0 文档对齐 | 已完成并提交 | 需求、架构、决策和 v1 快照对齐。 | 新会话只读文档即可说明范围与当前切片。 |
| 1 PostgreSQL | 已完成并提交 | Docker PostgreSQL、SQLAlchemy、Alembic、repository 与 v1 Log 兼容。 | migration 通过；v1 eval 13/13。 |
| 2.1 文本拆分 | 已完成并提交 | 一篇笔记拆成多个草稿，共享上下文下发。 | 独立离线测试通过；不访问照片或数据库。 |
| 2.2 照片预处理 | 已完成并提交 | 批量调用懂鸟适配器并输出结构化首候选。 | 离线 stub 测试通过；单图失败可隔离。 |
| 2.3 名录与 dry-run 匹配 | 已完成并提交 | eBird 名录、`species_id` 规范化和只读图文配对。 | 匹配与失败可解释；不写 observations。 |
| 2.4 批量确认写入 | 已完成并提交 | session、照片关系、一次确认和逐条 savepoint。 | completed/partial/failed 与事务回滚通过。 |
| 2.5 未匹配照片草稿 | 已完成并提交 | 可靠的未匹配照片按物种自动生成待确认草稿。 | 同种多图、上下文继承和失败边界通过。 |
| 2.6 v2 固定 eval | 已完成并提交 | 按第 9 节增加 6 条 v2 数据与离线 runner，不改生产能力。 | v2 6/6；2.1–2.5 为 156/156；v1 13/13。 |
| 3.1 媒体上传 API | 已完成并提交 | `POST /api/media`、哈希去重、文件与元数据。 | 201/200、校验和失败清理通过。 |
| 3.2 解析预览 API | 已完成并提交 | `POST /api/parse` 编排拆分、鉴定、匹配和组装。 | 图文/纯文本/纯照片与零持久化通过。 |
| 3.3 确认写入 API | 已完成并提交 | `POST /api/observations` 暴露批量写入。 | 201、部分成功、400/404/409/422 与回滚通过。 |
| 3.4 观测读取 API | 已完成并提交 | 列表、筛选和单条详情。 | 顺序、筛选、照片/session、404 与零副作用通过。 |
| 3.5 观测编辑 API | 已完成并提交 | 受限 PATCH 与物种 ID/展示名一致性。 | 字段语义、回滚和关系不变通过。 |
| 3.6 观测删除 API | 已完成并提交 | 只删除 observation，保留 session 与媒体。 | 204/404/422、外键解除和审计保留通过。 |
| 3.7 物种查询 API | 已完成并提交 | 本地名录联想与确定性相关度排序。 | 名称搜索、排序、边界和零网络/写入通过。 |
| 3.8 API 总体验收 | 已完成并提交 | 真实 Uvicorn 下串行验收 3.1–3.7 和 OpenAPI。 | 完整生命周期 37/37；全量检查 611/611。 |
| 3.9 React 基础工程 | 已完成并提交 | Vite、React、TypeScript、双路由、设计 token、API client 与代理。 | typecheck/lint/build、双路由与代理通过。 |
| 3.10 React 输入流程 | **已实现；当前 review** | 接入上传、parse、草稿编辑、照片归属、确认写入和部分成功展示。 | 纯文本/纯照片/混合、loading、错误重试和防重复提交通过；review 后单独提交。 |
| 3.11 React 管理流程 | **待做；后续第 2** | 接入筛选、列表、详情、物种联想、编辑和二次确认删除。 | 空态/失败/编辑/删除与媒体展示可用；停下 review。 |
| 3.12 前端总体验收 | **待做；后续第 3** | 两页真实联调以及视觉、键盘、触控和响应式验收。 | 核心流程 E2E；1024/736/360px 无页面横向溢出；停下 review。 |
| 4 v2 收尾发布 | **待做；后续第 4** | 更新文档、最终全量回归并打 `v2.0` tag；不擅自增加部署范围。 | 文档/代码/测试一致，用户确认后创建 tag。 |

---

## 11. 开发纪律

1. 不改的东西不要碰；一次一个模块、一个可验收切片。
2. 接口或数据结构变化先改本文，并将取舍以三行体写入 `DECISIONS.md`。
3. 任何核心改动后必须跑相关离线自检；存储和 agent 改动必须跑 v1 eval。
4. 真实 API 与带图测试消耗配额，默认不用它们替代离线回归。
5. 不提前引入框架、抽象或 agent；能用明确服务和工具解决的，不上子 agent。
