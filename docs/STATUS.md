# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：完成“全库一致性修订（Gemini→DeepSeek 措辞传导）”之后。

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
| **S3（新）** | ⬜ 未开始（已规划） | `range_check` 季节/分布核验适配器（数据源 eBird，范式B：`place+date → 当地当季合理物种清单`）。文档已就位（§7 工具行、§8 数据流回合2、§10 切片表、§3 目录树占位 `tools/range_check.py`），**代码与 eBird 接入都还没做**。 |
| **S4** | ⬜ 未开始 | `bird_id` 视觉鉴种真适配器（照片 URL → 候选种 + 置信度）。原 S3，现顺延为 S4。 |
| **S5** | ⬜ 未开始 | `memory/log` 的 append/query + `append_log` 写入 + 完整权限闸（写前审批）。注：薄版 permissions 已在 S1 就位，但写入链路与真审批未做。 |
| **S6** | ⬜ 未开始（薄版已存在） | 完整 `budget`（token 预算）+ 工具报错容错。注：薄版 budget（仅 max_steps 止捞）已在 S1 就位并锁定签名。 |
| **S7** | ⬜ 未开始 | `evals`：`evals/tasks.yaml` + `evals/run_evals.py` + 通过率。注：`scripts/check_s1.py` 只是 S1 的临时验证套件，**不是** eval 框架。 |
| **S8** | ⬜ 未开始（部分） | `cli` 打磨 + `README` + `DECISIONS.md`。注：`DECISIONS.md` 已建（含 1 条取舍），`README.md` 很简、`vibirding/cli.py` 未建。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：S1、S2 已完成。最近几轮在做**文档与全库一致性巩固**（range_check 升格、运行时迁到 DeepSeek、物种来源优先级裁决规则、去 Gemini 化措辞），不是在写新功能切片。
- **下一步（推荐）= 开工 S3 `range_check`**：
  1. 申请/确认 eBird API key 与环境变量；
  2. 写 `vibirding/tools/range_check.py`（范式B：`range_check(place, date) -> 物种清单`，risk=read，满足 Tool 协议）；
  3. 注册进 registry、接入循环（与现有 read_log 并存，模型从清单内挑种）；
  4. 处理三个待解小事（见 §6）；
  5. 写一个入口/验证脚本跑通。
- 开工前按铁律：**先在 architecture.md 把 range_check 的契约/形状定死（已大部分就位），再写代码**。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序）

1. **全库一致性修订**（本批，**尚未提交**）
   - 改了什么：把 architecture 的 DeepSeek 迁移传导到代码注释 + `CLAUDE.md`/`DECISIONS.md`（去 Gemini 化）、`schemas.source` 注释加 `"user"`、切片号 `S1–S7→S1–S8`、删 `scripts/smoke.py`。
   - 为什么：之前 Gemini→DeepSeek 只改了 architecture.md，没传导，造成全库 provider 措辞/编号/取值不一致。

2. **物种来源优先级裁决规则**（commit `cad77db fix: prompt`）
   - 改了什么：`agent/prompt.py` 写入四分支裁决（用户指定 > 图片鉴定 > 描述推断经 range_check）；`schemas.source` 引入 `"user"` 取值。
   - 为什么：明确“species 该信谁的”，冲突时打 `autoid_conflict`，没把握时 `species=null`+`low_confidence`。

3. **architecture.md 文档大更新**（已提交）
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
- **S3 `range_check` 真正接 eBird**：写适配器（范式B：place+date→当季合理物种清单）、申请 eBird key、接入循环、把 prompt 裁决规则第4条从“仅模型知识推断”升级为真正调 range_check。
- **S4 视觉鉴种 `bird_id`**：照片 URL → 候选种 + 置信度的真适配器。
- **range_check 开工时的三个待解小事**：
  1. **地名 → 坐标**：先用“常去观测点预存坐标表”的方案；
  2. **eBird 返回名单可能过长**：按近期（`back=N` 天）或按目标科收窄；
  3. **中/日文鸟名对接**：用 eBird taxonomy 的 `locale` 参数。
- **更后面**：S5（memory/log + append_log + 权限闸）、S6（完整 budget + 工具容错）、S7（evals）、S8（cli + README）；§11 进阶：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）、本地模型（OpenAI 兼容端点，`--local`）。

---

## 7. 已知未决 / 需人拍板
- **上一批一致性修订（9 个文件）尚未 commit**：见 §8，待提交。
- **DeepSeek 账户额度**：真模型验收时遇到过 `429 RESOURCE_EXHAUSTED`（prepayment credits depleted，预付额度耗尽）和 `503`（过载）。跑真模型前需确认账户有额度。
- **range_check 何时开工 / 是否现在申请 eBird key**（涉及账号与成本），待定。
- `scripts/run_s2.py`（Gemini 入口）是 throwaway，最终会删。
- `.gitignore` 把 `docs/` 列入忽略：`docs/` 下新建文件（如本 STATUS.md）需 `git add -f` 才能提交；是否要清理这条忽略规则，待定（本批未动）。

---

## 8. git 状态
- **最近一次 commit**：`cad77db fix: prompt`（prompt.py 物种来源优先级）。
- 之前：`cd8038a feature: add deepseek client` → `08b6ccf feature: add gemini client` → `0e7dbda feature: s1 finished`。
- **未提交的改动**（上一批“全库一致性修订”，待提交）：
  - 修改：`CLAUDE.md`、`DECISIONS.md`、`scripts/check_s1.py`、`scripts/run_s1.py`、`vibirding/agent/loop.py`、`vibirding/llm/__init__.py`、`vibirding/llm/mock.py`、`vibirding/schemas.py`
  - 删除：`scripts/smoke.py`
- 本文件 `docs/STATUS.md` 为**新增**（提交时需 `git add -f`，因 `docs/` 被 gitignore）。
