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

**2.1–2.4 已完成并提交；2.5 未匹配照片草稿已实现并通过验证，正在等待 review/commit。**
本切片把已经解析到 `species_id`、但没有对应文本草稿的照片按物种合并，自动生成照片来源
草稿并纳入统一预览；它不写数据库，最终仍须经过 2.4 的明确确认服务。review 前不得开始
Web/API，也不得提前实现文件上传/哈希落盘、FastAPI 或 React。

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
├── media/                                # 后续：gitignore，内容哈希文件名
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
│   │   ├── taxonomy.py                   # 第 2.3 步：名录导入与名称解析
│   │   ├── matching.py                   # 第 2.3 步：只读图文匹配计划
│   │   ├── assembly.py                   # 第 2.5 步：组装预览并生成未匹配照片草稿
│   │   └── batch.py                      # 第 2.4 步：确认后的事务化批量写入
│   └── api/                              # 后续：FastAPI app、路由和依赖
├── frontend/                             # 后续：React 应用
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
| `services/taxonomy.py` | 第 2.3 步：eBird 名录适配、导入、别名/外部结果到内部 `species_id` 的映射。 |
| `services/media.py` | 后续：内容哈希、去重、文件落盘和元数据。 |
| `services/parse.py` | 第 2.1/2.2 步：文本拆分、照片预处理与草稿构造；解析阶段不写 observations。 |
| `tools/bird_id.py` | 保留 v1 `run()` 文本工具契约，并提供结构化 `identify()` 给批处理服务复用。 |
| `services/matching.py` | 第 2.3 步：按 `species_id` 关联图文，只输出可解释的 dry-run 方案。 |
| `services/batch.py` | 第 2.4 步：验证明确确认、锁定媒体、创建 session，以 savepoint 逐条写入并汇总 created/failed。 |
| `services/assembly.py` | 第 2.5 步：消费 dry-run 结果，复制并补全草稿、合并未匹配照片，输出统一确认前的 `ParseResult`；不写库。 |
| `api/` | 后续：FastAPI 输入验证、依赖注入、HTTP 状态码和响应；不直接嵌入业务 SQL。 |
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
       {text, media_ids[], observations[]} -> {session_id, created[], failed[]}

GET    /api/observations?limit=&place=&species=&date_from=
GET    /api/observations/{id}
PATCH  /api/observations/{id}
DELETE /api/observations/{id}
GET    /api/species?q=
```

`POST /api/parse` 无写 observation 副作用；`POST /api/observations` 是用户确认后的批量写入。
`created[]` 和 `failed[]` 必须始终同时存在，即使其中一个为空。

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

## 8. Web 交互边界（后续第 3 步）

### 输入页

文本框、插图按钮、发送按钮和解析预览。自然语言查询可在前端直接转为资源 API，例如
“最近 10 条”对应 `GET /api/observations?limit=10`；不让 LLM 查询数据库后再复述。

### 管理页

浏览、筛选、编辑、删除观测；查看其关联照片和批次。跨提交“修改刚才那条”不交给 agent
猜测，走这张管理页的显式 PATCH/DELETE 操作。

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

### 第 3 步 Web

- 先用 HTTP 客户端覆盖 API，再接 React。
- 验证 parse 可重试且不写 observations；未确认不能创建记录；确认后才创建 session、记录和关联。

---

## 10. 实施计划

| 阶段 | 只做什么 | 验收 |
| --- | --- | --- |
| 0. 文档对齐 | 本文、需求、决策和工作区指引一致；冻结 v1 快照。 | 新 AI 仅靠文档能说明现状、目标、当前切片和不做项。 |
| 1. PostgreSQL | Docker、SQLAlchemy、migration、`observations`、`Log` 兼容实现、eval 数据库隔离。 | v1 离线 eval 13/13，且不引入批量/媒体/Web。 |
| 2.1 文本拆分 | 一篇笔记 -> 多个草稿，共享上下文下发。 | 独立离线测试。 |
| 2.2 照片预处理 | 批量调用现有懂鸟适配器，输出规范化候选输入。 | 纯脚本/服务测试，不写库。 |
| 2.3 物种名录与 dry-run 匹配 | `species` migration、映射、只输出匹配方案。 | ID 匹配和失败可解释，不写 observations。 |
| 2.4 批量确认写入 | `sessions` / `photos` migration、一次确认、部分成功。 | 事务和失败结果测试。 |
| 2.5 未匹配照片 | 未匹配照片自动生成记录，并纳入同一批预览确认。 | 覆盖自动建记录与用户统一确认的边界用例。 |
| 3. Web | FastAPI API -> React 输入页 -> React 管理页。 | API 先验收，再验收 UI。 |
| 4. 收尾 | README / STATUS / DECISIONS 更新，最终回归，打 `v2.0` tag。 | 文档、测试、发布状态一致。 |

---

## 11. 开发纪律

1. 不改的东西不要碰；一次一个模块、一个可验收切片。
2. 接口或数据结构变化先改本文，并将取舍以三行体写入 `DECISIONS.md`。
3. 任何核心改动后必须跑相关离线自检；存储和 agent 改动必须跑 v1 eval。
4. 真实 API 与带图测试消耗配额，默认不用它们替代离线回归。
5. 不提前引入框架、抽象或 agent；能用明确服务和工具解决的，不上子 agent。
