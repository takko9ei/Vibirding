# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：完成“docs 入库治理”（把唯一事实来源 architecture.md 纳入版本控制、从 .gitignore 移除 docs/ 与 CLAUDE.md、校正本文件 git 状态）之后。

---

## 1. 项目是什么
一个个人级“观鸟速记” agent（Python）：把一段随手记的、乱糟糟的观鸟笔记整理成结构化记录（必要时调工具核验地点/季节、查个人历史），产出一条可写入日志的 `Observation`。
完整架构、目录、数据结构（§4）、契约（§6）、切片路线（§10）见 **docs/architecture.md（唯一事实来源）**。

---

## 2. 切片完成情况（对照 architecture §10，已重编号为 S1–S8）

| 切片 | 状态 | 实际交付 / 对应文件 |
|---|---|---|
| **S1** | ✅ done | 离线循环骨架。`vibirding/schemas.py`（5 个数据结构）、`llm/mock.py`（MockClient）、`agent/loop.py`（run_agent_turn）、`agent/prompt.py`、`tools/registry.py`（+Tool 协议/ToolContext）、`tools/log_read.py`（假 read_log）、`harness/{trace,budget,permissions}.py`（trace + 薄版 budget 仅 max_steps + 薄版 permissions read→allow）、`config.py`、`scripts/run_s1.py`（冒烟）、`scripts/check_s1.py`（28 条验证全过）。 |
| **S2** | ✅ done | 接真模型并产出结构化 Observation。`vibirding/llm/deepseek_client.py`（**DeepSeekClient**，openai SDK，OpenAI 兼容，手动函数调用）为运行时；`llm/client.py`（GeminiClient，google-genai）保留为备用 provider；`config.py` 读 `DEEPSEEK_API_KEY`/base_url/模型名；入口 `scripts/run_deepseek.py`（真模型端到端验证通过，能产出并校验 Observation，含地点纠错）、`scripts/run_s2.py`（Gemini 入口，throwaway，最终会删）。 |
| **S3（新）** | ✅ done | `range_check` 季节/分布核验适配器（数据源 eBird，范式B：`place+date → 当地当季合理物种清单`）。`tools/range_check.py`（Tool 协议，httpx 调 `obs/geo/recent`，10s 超时，去重/中文名/截断；容错：超时/网络/401-403→ok=False，未知地点/空清单→ok=True 降级）、`tools/locations.py`（地名→坐标预存表，8 个常去点 + `resolve_place`）、`config.py`（`load_ebird_api_key` + eBird 常量，俗名用 **`sppLocale=zh_SIM`**）、`agent/prompt.py`（启用 range_check，第4分支从清单挑种）、`scripts/check_s3.py`（离线 19/19 全过）、`scripts/run_s3.py`（端到端：真 DeepSeek+真 eBird 跑通，模型调 range_check 并产出合法 Observation）。三个待解小事已落地（见 §6）。**踩坑修正**：eBird obs 端点俗名语言参数是 `sppLocale` 不是 `locale`（后者被忽略回英文）。 |
| **S4** | ⬜ 未开始 | `bird_id` 视觉鉴种真适配器（照片 URL → 候选种 + 置信度）。原 S3，现顺延为 S4。 |
| **S5** | ⬜ 未开始 | `memory/log` 的 append/query + `append_log` 写入 + 完整权限闸（写前审批）。注：薄版 permissions 已在 S1 就位，但写入链路与真审批未做。 |
| **S6** | ⬜ 未开始（薄版已存在） | 完整 `budget`（token 预算）+ 工具报错容错。注：薄版 budget（仅 max_steps 止捞）已在 S1 就位并锁定签名。 |
| **S7** | ⬜ 未开始 | `evals`：`evals/tasks.yaml` + `evals/run_evals.py` + 通过率。注：`scripts/check_s1.py` 只是 S1 的临时验证套件，**不是** eval 框架。 |
| **S8** | ⬜ 未开始（部分） | `cli` 打磨 + `README` + `DECISIONS.md`。注：`DECISIONS.md` 已建（含 1 条取舍），`README.md` 很简、`vibirding/cli.py` 未建。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：S1、S2、S3 已完成。S3 端到端验收通过（卡西临海公园→纠正为葛西临海公园→命中坐标表→range_check 真查 eBird→模型清单内挑种→合法 Observation）。
- **下一步（推荐）= 开工 S4 `bird_id`**（视觉鉴种真适配器，照片 URL → 候选种 + 置信度）：
  1. **先验证鉴种 API**（有没有公开 API；没有就退回 Merlin/eBird 或托管模型，上层不变）；
  2. 先在 architecture 把 `bird_id` 契约/形状定死，再写 `tools/bird_id.py`（risk=read，满足 Tool 协议）；
  3. 接入循环（裁决规则第3条：无种名但有图片 → 以 bird_id 为准，source="bird_id"）；
  4. 写入口/验证脚本跑通带照片的笔记。
- 也可考虑先做 S5（写日志 + append_log + 权限闸），让"产出的 Observation 真正落盘"，次序由你定。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序）

-1. **S3 `range_check` 实现**（本批，待 commit）
   - 改了什么：新增 `tools/range_check.py`、`tools/locations.py`、`scripts/{check_s3,run_s3}.py`；改 `config.py`（eBird 常量 + key 加载）、`agent/prompt.py`（启用 range_check + count 抽取微调：量词单只/音近误写如“一直”→count=1）、`requirements.txt`（httpx）、architecture §7（date 语义 + 三小事落地 + sppLocale 纠正）。
   - 为什么：补"无图仅描述"的权威季节/分布核验短板。**踩坑**：计划写的 `locale=zh` 被 eBird obs 端点忽略（回英文），实测须用 `sppLocale=zh_SIM`（简体）。验收：离线 19/19 + 真 eBird + 端到端均通过。

0. **docs 入库治理**（commit `b800e47`）
   - 改了什么：从 `.gitignore` 移除 `docs/` 与 `CLAUDE.md` 两行；**首次把 `docs/architecture.md`（唯一事实来源）的最新版提交进 git**；校正本 STATUS.md 的 §4/§7/§8。
   - 为什么：`docs/` 自 `b05fed2 "change on gitignore"` 起被忽略、且 architecture.md 当时被 `git rm --cached` 移出跟踪，导致此后所有架构大更新（range_check 升 S3、Gemini→DeepSeek、裁决规则…）**一直没进版本控制**——唯一事实来源只剩工作树一份、随时可能丢；STATUS.md 旧版还误称其“已提交”。

1. **全库一致性修订**（commit `911c4ba`，**已提交**）
   - 改了什么：把 architecture 的 DeepSeek 迁移传导到代码注释 + `CLAUDE.md`/`DECISIONS.md`（去 Gemini 化）、`schemas.source` 注释加 `"user"`、切片号 `S1–S7→S1–S8`、删 `scripts/smoke.py`。
   - 为什么：之前 Gemini→DeepSeek 只改了 architecture.md，没传导，造成全库 provider 措辞/编号/取值不一致。

2. **物种来源优先级裁决规则**（commit `cad77db fix: prompt`）
   - 改了什么：`agent/prompt.py` 写入四分支裁决（用户指定 > 图片鉴定 > 描述推断经 range_check）；`schemas.source` 引入 `"user"` 取值。
   - 为什么：明确“species 该信谁的”，冲突时打 `autoid_conflict`，没把握时 `species=null`+`low_confidence`。

3. **architecture.md 文档大更新**（内容早已写入工作树，但因 `docs/` 被忽略**直到本批第 0 条才真正提交进 git**）
   - 改了什么：`range_check` 由“可选进阶”升格为正式新 **S3**（原视觉鉴种→S4，整体顺延到 S8）；全文 Gemini→DeepSeek；§8 加裁决规则；§3 补 `range_check.py`。
   - 为什么：季节/分布核验应有权威工具（eBird），且运行时已换 DeepSeek。

4. **运行时切换到 DeepSeek**（commit `cd8038a`，GeminiClient 见 `08b6ccf`）
   - 改了什么：新增 `DeepSeekClient`（openai SDK、OpenAI 兼容、deepseek-v4-flash）+ `run_deepseek.py` 入口；config 改读 DEEPSEEK；GeminiClient 保留备用。
   - 为什么：换 provider；得益于 provider 中立，**只换 client，loop/registry/工具/trace/schemas 一行不改**。

5. **read_log 正名**（已提交）
   - 改了什么：`read_log` 职责收敛为“查我自己的历史观测（个人记录/弱先验）”，季节/分布核验职责剥离出去（→ 后来升格成 range_check）。
   - 为什么：个人日志不是物候权威，没记录过 ≠ 那儿没有；误用会误导模型。

---

## 5. 关键约定速查（冷启动对齐，提炼自 CLAUDE.md + architecture）
- **唯一事实来源**：`docs/architecture.md`；改接口/数据结构 → **先改文档，再改代码**。
- **运行时模型**：DeepSeek（OpenAI 兼容端点，`openai` SDK，`deepseek-v4-flash`，temperature=0）；`GeminiClient` 保留为备用 provider。
- **provider 中立**：循环/工具/记忆/eval 只认内部归一化类型（`ModelResponse`/`ToolCall`/`ToolResult`/`Observation`/`TraceEvent`）；provider 原生形状封死在 `llm/deepseek_client.py`。
- **架构形态**：单 agent + 工具循环（model→tool→model）；工具统一契约：find → schema 校验 → 若 write 过权限闸 → run → 归一化 `{ok, output}`。
- **手动函数调用**：只声明 tools、自己执行、自己把结果作为 `role="tool"` 消息回填；**不用任何 SDK 的自动函数执行**。
- **流程纪律**：一次只实现一个模块/切片；每个能跑的切片停下 review 再 `git commit`（commit per slice）。
- **代码风格**：清晰英文注释 + 关键逻辑写完用中文逐段解释；与人用中文交流；倾向最小实现。
- **运行环境**：一律用 `.venv\Scripts\python.exe`（**不是**全局 anaconda，它没装 openai/google-genai）；命令用 PowerShell（Windows）。
- **包名**：可导入包小写 `vibirding`（仓库根文件夹是 `Vibirding`）。

---

## 6. 尚未实现但已规划（待办 + 所在切片）
- **S4 视觉鉴种 `bird_id`**：照片 URL → 候选种 + 置信度的真适配器（先验证鉴种 API 是否有公开接口）。
- **更后面**：S5（memory/log + append_log + 权限闸）、S6（完整 budget + 工具容错）、S7（evals）、S8（cli + README）；§11 进阶：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）、本地模型（OpenAI 兼容端点，`--local`）。
- **S5 顺带做：运行时日期注入**（已定方案，留到 S5/cli 层统一做）：模型不知道"今天"，date 靠猜（实测把 today 猜成 `2025-06-25`，年份都错）。解法**不是 tool、也不是改 prompt 措辞**，而是在组装 messages 时用 `datetime.now()` 注入运行时日期（与静态 SYSTEM_PROMPT 分开，作一条运行时上下文）；这同时让 prompt 里已写的"obs_date/range_check date 没写就用今天"两条规则真正生效。放 S5 是因为要统一覆盖多个入口脚本 + 未来 cli，避免现在改三处回头又重来。
- **range_check 的可能改进（非阻塞，待定）**：地名→坐标目前仅 8 点 exact-match，命不中即降级；名单收窄目前只按 `back` 天 + 展示截断（未按目标科）；S7 eval 时观察"清单内挑种"准确度（端到端测试里模型对"黑头红腿小涉禽"选了蛎鹬而非黑翅长脚鹬）。

---

## 7. 已知未决 / 需人拍板
- **DeepSeek 账户额度**：真模型验收时遇到过 `429 RESOURCE_EXHAUSTED`（预付额度耗尽）和 `503`（过载）。用户已表示额度不用担心。
- **下一切片次序**：S4（bird_id 视觉鉴种）还是 S5（写日志 + append_log + 权限闸）先做，待你拍板（见 §3）。
- `scripts/run_s2.py`（Gemini 入口）暂**保留**为备用 provider 的参考入口。

> 已清掉的旧遗留：①一致性修订（已提交 `911c4ba`/`8a898af`）；②`docs/` 被 gitignore 致 architecture.md 未入库（已修，commit `b800e47`）；③`EBIRD_API_KEY` 已配置且验证可用（S3）。

---

## 8. git 状态
- **待提交（本批 = S3 实现）**：`tools/range_check.py`、`tools/locations.py`、`scripts/{check_s3,run_s3}.py`（新增）+ `config.py`、`agent/prompt.py`、`requirements.txt`、`docs/architecture.md`(§7)、`docs/STATUS.md`（修改）。待 review 后 commit。
- **当前 HEAD**：`b800e47`（docs 入库治理：移除 .gitignore 的 docs//CLAUDE.md，首次提交 architecture.md）。
- 之前 HEAD 链：`911c4ba`（全库一致性修订）→ `8a898af docs: add STATUS.md` → `cad77db fix: prompt` → `cd8038a add deepseek client` → `08b6ccf add gemini client` → `0e7dbda s1 finished`。
- 注：早先 `git status` 看似 clean，是因为 architecture.md 被 `.gitignore` 屏蔽而**不显示为未跟踪**——这正是它一直漏掉入库的原因，本批已修复。
- 自此 `docs/` 下文件正常跟踪，新增/改动**不再需要 `git add -f`**。
