# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：S6（budget 上限 + 工具报错容错 + 日期注入）落地、四套自检全绿之后（S6 代码待提交；HEAD 仍为 S5 的 `68d713e`）。

---

## 1. 项目是什么
一个个人级“观鸟速记” agent（Python）：把一段随手记的、乱糟糟的观鸟笔记（可带本地照片）整理成结构化记录——必要时调工具做视觉鉴种 / 季节·分布核验 / 查个人历史，产出一条可写入日志的 `Observation`。
完整架构、目录、数据结构（§4）、契约（§6）、切片路线（§10）见 **[docs/architecture.md](architecture.md)（唯一事实来源）**。

---

## 2. 切片完成情况（对照 architecture §10，S1–S8）

| 切片 | 状态 | 实际交付 / 对应文件 |
|---|---|---|
| **S1** | ✅ done | **离线循环骨架**（MockClient，零成本跑通 model→tool→model）。`vibirding/schemas.py`（5 个数据结构，**最先锁**）、`llm/mock.py`（MockClient）、`agent/loop.py`（`run_agent_turn`，签名自此锁定）、`agent/prompt.py`、`tools/registry.py`（Tool 协议 + ToolContext + 统一执行管线）、`tools/log_read.py`（假 read_log）、`harness/{trace,budget,permissions}.py`（trace + 薄版 budget 仅 max_steps + 薄版 permissions read→allow）、`config.py`、`scripts/{run_s1,check_s1}.py`（离线自检 28 条全过）。 |
| **S2** | ✅ done | **接真模型产出结构化 Observation**。`vibirding/llm/deepseek_client.py`（**DeepSeekClient**：openai SDK、OpenAI 兼容端点、`deepseek-v4-flash`、**手动函数调用**）为运行时；`llm/client.py`（GeminiClient，google-genai）保留为备用 provider；`config.py` 读 `DEEPSEEK_API_KEY`；入口 `scripts/run_deepseek.py`（真模型端到端，含地点纠错）。`scripts/run_s2.py`（Gemini 入口，throwaway，保留作备用 provider 参考）。 |
| **S3** | ✅ done | **range_check：eBird 季节/分布核验（范式B）**——`place+date → 当地近期实际记录的物种清单`，模型在清单内挑种。`tools/range_check.py`（Tool 协议，httpx 调 `obs/geo/recent`，10s 超时，去重/中文名/截断；容错：超时/网络/401-403→ok=False，未知地点/空清单→ok=True 降级）、`tools/locations.py`（地名→坐标预存表，8 个常去点 + `resolve_place`）、`config.py`（`load_ebird_api_key` + eBird 常量，俗名用 **`sppLocale=zh_SIM`**）、`agent/prompt.py`（启用 range_check + count 抽取微调）、`scripts/{check_s3,run_s3}.py`。验收：离线 19/19 + 真 eBird + 端到端均通过。**踩坑**：俗名参数是 `sppLocale` 不是 `locale`。 |
| **S4** | ✅ done | **bird_id：懂鸟(hholove) 视觉鉴种**，补裁决规则第3条（无种名+有图 → 以图片鉴定定种，source="bird_id"）。`tools/bird_id.py`（Tool 协议；**异步两步+轮询全封在 run() 内**：上传长超时 connect10/read60/write60/pool10、取结果 timeout30、轮询≤5；返回数组 `[code,payload]` 解析、中文名按 `|` 切首段、置信度 0~100；容错：缺key/文件不存在/超2M/上传非1000/超时/网络/**坏结构在 run() 内显式接**→ok=False，1008/1009 未认出→ok=True）、`config.py`（`load_hho_api_key` + HHO 常量，**poll 用 urlencoded `data=`**）、`agent/prompt.py`（启用分支3，图片路径经 user 消息传入）、`scripts/{check_s4,run_s4}.py`。验收：离线 30/30 + 真懂鸟三图全对（byx 北鹰鸮 / cang 苍鹰 / ljd 蓝矶鸫）+ 端到端（cang → source=bird_id）。 |
| **S5** | ✅ done | **append_log 写日志 + 权限闸**，第一次持久写入。`memory/log.py`（`Log.append` 只追加 / `Log.query` 顺序扫描过滤，文件/目录不存在自动建、严格 append-only）、`tools/log_write.py`（`append_log`，risk=**write**，唯一过权限闸；id/timestamp 由 `run()` 补、不让模型填）、`tools/log_read.py`（run() 改真读 `Log.query`、可注入 Log；name/desc/schema/risk 不变）、`harness/permissions.py`（真实现：可注入审批回调、read→allow、write→回调、支持“本回合一直允许”，无回调时 fail-closed）、`config.py`(+`OBSERVATIONS_PATH`)、`agent/prompt.py`（“输出 JSON 代码块”→“调用 append_log 工具”）、`scripts/{check_s5,run_s5}.py` + `check_s1` 连带修订（read_log 改真读后注入临时 Log）。验收：离线 check_s5 31/31 + check_s1 28/28 全绿；**真模型端到端 run_s5 截至提交未跑（见 §7）**。 |
| **S6** | ✅ done（待提交） | **鲁棒性：budget 完整化 + 工具报错容错 + 日期注入**。`harness/budget.py`（+`observe`/`max_tokens`，token 触顶→`stop_reason="max_tokens"`；`tick`/`stop_reason` 签名不变；`max_tokens=None` 向后兼容）、`agent/loop.py`（仅加一行 `budget.observe(resp.usage)`，签名/控制流不变）、`tools/failures.py`（`tool_failure` 统一失败文案）、`tools/range_check.py`（补非-httpx 异常捕获 + 统一文案）、`memory/log.py`（`query` 坏行跳过）、`tools/bird_id.py`（ok=False 套统一文案）、`agent/prompt.py`（加“工具失败处理策略”段 + `today_hint()` 日期注入）、`scripts/{check_s6,run_s6}.py`。验收：check_s6 **24/24** + 回归 check_s1/s3/s4/s5 全绿；run_s6 真模型触发留手动跑。 |
| **S7** | ⬜ 未开始 | `evals`：`evals/tasks.yaml` + `evals/run_evals.py` + 通过率。注：`scripts/check_s*.py` 只是各切片的离线自检，**不是** eval 框架。 |
| **S8** | ⬜ 未开始（部分） | `cli` 打磨 + `README` + `DECISIONS.md`。注：`DECISIONS.md` 已建（4 条取舍），`README.md` 很简、`vibirding/cli.py` 未建。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：S1–S6 代码均已落地（S1–S5 已提交 HEAD `68d713e`；**S6 待提交**）。budget 完整化（步数 + token 双上限、优雅收尾）、工具报错容错统一（失败文案 + 坏 JSON / 坏行捕获）、运行时日期注入均已完成。离线自检 check_s6 24/24 + 回归 check_s1/s3/s4/s5 全绿。
- **下一步 = 开工 S7（evals：10–15 用例 + 通过率）**。
- 铁律：开工前先在 architecture 确认对应契约（§9 eval 设计 / §4 数据结构），再写代码；一次一个切片、commit per slice。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序）

1. **S6 budget 上限 + 工具报错容错 + 日期注入**（鲁棒性切片，待提交）
   - budget 完整化（`observe`+`max_tokens`，`tick`/`stop_reason` 签名不变）；loop 加一行 `budget.observe(resp.usage)` 喂 token（用户批准，不改签名/控制流）；优雅收尾复用既有 `budget_stop`。
   - 工具容错：新建 `tools/failures.py` 统一失败文案；range_check 补非-httpx 异常捕获、`log.query` 坏行跳过、bird_id ok=False 套统一文案（正常路径不动，保留各 check 断言子串）；prompt 加失败处理策略 + `today_hint()` 日期注入（修“年份猜错”）。
   - 文档：architecture §6 补 `budget.observe`、§7 补统一失败文案。自检 check_s6 24/24 + check_s1/s3/s4/s5 全回归绿。

2. **S5 写日志 + append_log + 权限闸**（commit `68d713e`）
   - 新建 `memory/log.py`（append-only `Log.append`/`query`）+ `tools/log_write.py`（`append_log`，risk=write）；read_log 由假数据改真读 `Log.query`；permissions 从 S1 stub 长成真实现（可注入审批回调 + “本回合一直允许”）。prompt 由“输出 JSON 代码块”改“调用 append_log 工具”，落地架构 §8 回合3/4。
   - 与架构对齐：契约（append_log 工具六件套、`permissions.check` 签名）均按 §6/§7，**未改 architecture.md**；日志句柄走构造器注入（不动 registry 的 ToolContext，遵守“不改 loop/schemas/registry 结构”）。
   - 取舍：append_log 的 id/timestamp 是机器字段由 `run()` 补，不暴露给模型；写入失败暂交 registry 兜底（完整容错归 S6）。

3. **S4 `bird_id` 视觉鉴种**（commit `8a74898`）
   - 接懂鸟(hholove) API：异步两步（上传+轮询）全封在 `run()` 内、补裁决第3条；architecture §7 bird_id 备注更新为懂鸟实现、入参本地 `image_path`（非 URL）。
   - 踩坑：上传海外慢须长超时（否则 WriteTimeout）；poll 用 urlencoded `data=`；返回是数组 `[code,payload]`。

4. **S3 `range_check` 季节/分布核验**（commit `69a67f8` + `bd04472`）
   - 接 eBird `obs/geo/recent`（范式B：place+date→当地近期物种清单），补“无图仅描述”短板；prompt 启用、architecture §7 补 date 语义。
   - 踩坑：俗名参数须用 `sppLocale=zh_SIM`（`locale` 被 obs 端点忽略回英文）。

5. **docs 入库治理**（commit `b800e47`）
   - 从 `.gitignore` 移除 `docs/` 与 `CLAUDE.md`，**首次把唯一事实来源 `architecture.md` 提交进 git**。
   - 之前 `docs/` 被忽略、architecture.md 被 `git rm --cached` 移出跟踪，导致一系列架构大更新长期没进版本控制。

6. **物种来源优先级裁决规则**（commit `cad77db`）
   - `agent/prompt.py` 写入四分支裁决（用户指定 > 图片鉴定 > 描述推断经 range_check）；`schemas.source` 取值含 `”user”`。
   - 明确”species 该信谁”，冲突打 `autoid_conflict`，没把握 `species=null`+`low_confidence`。

7. **range_check 升格为正式 S3 + 运行时切 DeepSeek**（architecture 大更新；client 见 `cd8038a`/`08b6ccf`）
   - 季节/分布核验从”可选进阶”升为正式新 S3（数据源 eBird），原视觉鉴种顺延为 S4；运行时由 Gemini 改 DeepSeek。
   - 得益于 provider 中立，换 client 不动 loop/registry/工具/trace/schemas。

8. **read_log 正名**
   - `read_log` 职责收敛为“查我自己的历史观测（个人记录/弱先验）”，季节/分布核验剥离出去（→ 升格成 range_check）。
   - 个人日志不是物候权威：没记录过 ≠ 那儿没有；误用会误导模型。

---

## 5. 关键约定速查（冷启动对齐，提炼自 CLAUDE.md + architecture）
- **唯一事实来源**：`docs/architecture.md`；改接口/数据结构/契约 → **先改文档，再改代码**。
- **运行时模型**：DeepSeek（OpenAI 兼容端点，`openai` SDK，`deepseek-v4-flash`，temperature=0）；GeminiClient 留作备用 provider。
- **provider 中立**：循环/工具/记忆/eval 只认内部归一化类型（`ModelResponse`/`ToolCall`/`ToolResult`/`Observation`/`TraceEvent`）；provider 原生形状封死在 `llm/deepseek_client.py`。
- **架构形态**：单 agent + 工具循环（model→tool→model）；工具统一契约：find → schema 校验 → 若 write 过权限闸 → run → 归一化 `{ok, output}`。
- **手动函数调用**：只声明 tools、自己执行、自己把结果作为 `role="tool"` 消息回填；**不用任何 SDK 的自动函数执行**。
- **外部 API**：用 `httpx`，**必设超时**；所有失败在工具 `run()` 内归一化成 ToolResult，绝不抛裸栈（坏结构/解析失败也在 run() 内显式接、给定制文案，不只靠 registry 兜底）。
- **流程纪律**：一次只实现一个模块/切片；每个能跑的切片停下 review 再 `git commit`（commit per slice）。
- **代码风格**：清晰**英文注释** + 关键逻辑写完用**中文**逐段解释；与人用中文交流；倾向最小实现。
- **运行环境**：一律用 `.venv\Scripts\python.exe`（**不是**全局 anaconda，它没装 openai/httpx）；命令用 **PowerShell**（Windows）。
- **包名**：可导入包小写 `vibirding`（仓库根文件夹是 `Vibirding`）。
- **密钥**：均从 `config.py` 经 python-dotenv 读项目根 `.env`，不硬编码——`DEEPSEEK_API_KEY` / `EBIRD_API_KEY` / `HHO_API_KEY`（备用 `GEMINI_API_KEY`）。

---

## 6. 尚未实现但已规划（待办 + 所在切片）

> 注：range_check 接 eBird、视觉鉴种、append_log 写日志 + 权限闸（S5）、budget 完整化 + 工具报错容错 + 运行时日期注入（S6）、三个待解小事均已落地，不再是待办。以下是真正剩余的工作。

- **S7**：evals（10–15 用例 + 通过率）。eval 时观察“range_check 清单内挑种”准确度（曾见模型对“黑头红腿小涉禽”选蛎鹬而非黑翅长脚鹬）；range_check 名单收窄目前只按 `back` 天 + 展示截断（未按目标科）、坐标表仅 8 点 exact-match——按需在此优化。
- **S8**：cli 打磨 + README + DECISIONS。
- **§11 进阶（v1 之后）**：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）；本地模型（OpenAI 兼容端点，`--local`）。

---

## 7. 已知未决 / 需人拍板
- **S5 端到端已手动验收通过**：用户手动跑 `scripts/run_s5.py` 确认写入 + 权限闸 + 读回均正常（写前 y/n 确认、按 y 落盘、回合2 read_log 查回）。
- **DeepSeek 账户额度**：真模型验收时遇到过 `429`（预付额度耗尽）/`503`（过载）。用户已表示额度不用担心。
- **`scripts/run_s4.py` 的 `TESTIMGS_DIR` 硬编码**到桌面 `C:\Users\Takko\Desktop\testimgs`（个人用例集，非交付目录）；换图片源需改这个常量。该文件夹里每张 `<stem>.jpg` 配一份 `<stem>_discribe.txt` 作笔记，运行 `run_s4.py <stem>` 选图、不带参数则随机。
- **`scripts/run_s2.py`（Gemini 入口）** 暂保留为备用 provider 参考，最终可能删。
- 其余无阻塞性未决项；下一步 S7（evals）。

---

## 8. git 状态
- **最近一次 commit（HEAD）**：`68d713e feat: s5 write log`（S6 代码尚未提交）。
- **未提交的改动**：S6 全部改动（`harness/budget.py`、`agent/loop.py`、`agent/prompt.py`、`tools/{failures,range_check,bird_id}.py`、`memory/log.py`、`scripts/{check_s6,run_s6}.py`）+ 文档（`docs/architecture.md`、`docs/STATUS.md`）——待提交为 S6。
- 切片提交链（新→旧）：(S6 待提交) → S5 `68d713e` → S4 `8a74898` → S3 `bd04472`+`69a67f8` → docs 入库治理 `b800e47` → `8a898af docs: STATUS` → `cad77db fix: prompt` → `cd8038a add deepseek` → `08b6ccf add gemini` → `0e7dbda s1 finished`。
- `docs/` 已正常跟踪，改动**不再需要 `git add -f`**。
