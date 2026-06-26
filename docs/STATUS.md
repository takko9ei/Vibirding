# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：S4（bird_id 懂鸟视觉鉴种）完成并提交（commit `8a74898`）之后，做的一次完整盘点。

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
| **S5** | ⬜ 未开始 | `memory/log.py`（append-only JSONL：`append(obs)` / `query`）+ `tools/log_write.py`（`append_log`，risk=**write**）+ 充实 `harness/permissions.py` 的写入审批。让 Observation **真正落盘**到 `data/observations.jsonl`。 |
| **S6** | ⬜ 未开始（薄版已存在） | 完整 `budget`（token 预算）+ 工具报错容错。注：薄版 budget（仅 max_steps）自 S1 就位并锁定签名。 |
| **S7** | ⬜ 未开始 | `evals`：`evals/tasks.yaml` + `evals/run_evals.py` + 通过率。注：`scripts/check_s*.py` 只是各切片的离线自检，**不是** eval 框架。 |
| **S8** | ⬜ 未开始（部分） | `cli` 打磨 + `README` + `DECISIONS.md`。注：`DECISIONS.md` 已建（4 条取舍），`README.md` 很简、`vibirding/cli.py` 未建。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：S1、S2、S3、S4 已完成并提交。三个只读工具 `read_log + range_check + bird_id` 均已接入，`scripts/run_s4.py` 三个都注册。最近一次端到端验收（cang 用例）：无种名+图 → 模型调 bird_id（苍鹰）→ 再调 range_check 核验 → 产出 `source="bird_id"` 的合法 Observation。
- **下一步（推荐）= 开工 S5（写日志 + append_log + 完整权限闸）**，让产出的 Observation 真正落盘：
  1. 写 `vibirding/memory/log.py`：`append(obs)` 追加一行 JSONL、`query(place/species/date_range)`；
  2. 写 `vibirding/tools/log_write.py`：`append_log` 工具，**risk="write"**（唯一需过权限闸的工具）；
  3. 充实 `harness/permissions.py` 写入审批（CLI 里 y/n；eval/mock 自动策略）——签名自 S1 锁定，只填实现深度；
  4. 把假的 `read_log` 换成读真日志（`memory/log.query`）；
  5. **顺带做“运行时日期注入”**（见 §6）。
- 铁律：开工前先在 architecture 确认 `append_log` / `log` 契约（§6 已有），再写代码。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序）

1. **S4 `bird_id` 视觉鉴种**（commit `8a74898`）
   - 接懂鸟(hholove) API：异步两步（上传+轮询）全封在 `run()` 内、补裁决第3条；architecture §7 bird_id 备注更新为懂鸟实现、入参本地 `image_path`（非 URL）。
   - 踩坑：上传海外慢须长超时（否则 WriteTimeout）；poll 用 urlencoded `data=`；返回是数组 `[code,payload]`。

2. **S3 `range_check` 季节/分布核验**（commit `69a67f8` + `bd04472`）
   - 接 eBird `obs/geo/recent`（范式B：place+date→当地近期物种清单），补“无图仅描述”短板；prompt 启用、architecture §7 补 date 语义。
   - 踩坑：俗名参数须用 `sppLocale=zh_SIM`（`locale` 被 obs 端点忽略回英文）。

3. **docs 入库治理**（commit `b800e47`）
   - 从 `.gitignore` 移除 `docs/` 与 `CLAUDE.md`，**首次把唯一事实来源 `architecture.md` 提交进 git**。
   - 之前 `docs/` 被忽略、architecture.md 被 `git rm --cached` 移出跟踪，导致一系列架构大更新长期没进版本控制。

4. **物种来源优先级裁决规则**（commit `cad77db`）
   - `agent/prompt.py` 写入四分支裁决（用户指定 > 图片鉴定 > 描述推断经 range_check）；`schemas.source` 取值含 `"user"`。
   - 明确“species 该信谁”，冲突打 `autoid_conflict`，没把握 `species=null`+`low_confidence`。

5. **range_check 升格为正式 S3 + 运行时切 DeepSeek**（architecture 大更新；client 见 `cd8038a`/`08b6ccf`）
   - 季节/分布核验从“可选进阶”升为正式新 S3（数据源 eBird），原视觉鉴种顺延为 S4；运行时由 Gemini 改 DeepSeek。
   - 得益于 provider 中立，换 client 不动 loop/registry/工具/trace/schemas。

6. **read_log 正名**
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

> 注：早期 README/计划里列为“待办”的 **range_check 接 eBird、视觉鉴种、三个待解小事（地名→坐标预存表 / eBird 名单收窄 / 中文名 locale）已在 S3/S4 全部落地**，不再是待办。以下是真正剩余的工作。

- **S5**：`memory/log`（append/query JSONL）+ `append_log` 写入工具 + 完整写入权限闸；把假 read_log 换成读真日志。
- **S5 顺带：运行时日期注入**——模型不知道“今天”，date 靠猜（实测把 today 猜成 `2025-06-25`，年份都错）。解法**不是 tool、也不是改 prompt 措辞**，而是组装 messages 时用 `datetime.now()` 注入运行时日期（与静态 SYSTEM_PROMPT 分开）；这让 prompt 里“obs_date/range_check date 没写就用今天”两条规则真正生效。放 S5 以统一覆盖多个入口脚本 + 未来 cli。
- **S6**：完整 budget（token 预算）+ 工具报错容错。含一处登记：`range_check.run()` 未显式捕获非-httpx 异常（如 eBird 返回 200 但坏 JSON），目前落到 registry 兜底成**通用**文案；S6 时给它定制捕获（bird_id 已按此做了）。
- **S7**：evals（10–15 用例 + 通过率）。eval 时观察“range_check 清单内挑种”准确度（曾见模型对“黑头红腿小涉禽”选蛎鹬而非黑翅长脚鹬）；range_check 名单收窄目前只按 `back` 天 + 展示截断（未按目标科）、坐标表仅 8 点 exact-match——按需在此优化。
- **S8**：cli 打磨 + README + DECISIONS。
- **§11 进阶（v1 之后）**：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）；本地模型（OpenAI 兼容端点，`--local`）。

---

## 7. 已知未决 / 需人拍板
- **DeepSeek 账户额度**：真模型验收时遇到过 `429`（预付额度耗尽）/`503`（过载）。用户已表示额度不用担心。
- **`scripts/run_s4.py` 的 `TESTIMGS_DIR` 硬编码**到桌面 `C:\Users\Takko\Desktop\testimgs`（个人用例集，非交付目录）；换图片源需改这个常量。该文件夹里每张 `<stem>.jpg` 配一份 `<stem>_discribe.txt` 作笔记，运行 `run_s4.py <stem>` 选图、不带参数则随机。
- **`scripts/run_s2.py`（Gemini 入口）** 暂保留为备用 provider 参考，最终可能删。
- 其余无阻塞性未决项；S4 vs S5 次序已定（S4 已做，下一步 S5）。

---

## 8. git 状态
- **最近一次 commit（HEAD）**：`8a74898 feat: add dongniao api tool`（= S4 bird_id 实现，含 architecture §7 文档更新）。
- **未提交的改动**：仅本文件 `docs/STATUS.md`（本次完整盘点）——写完即 commit。
- 切片提交链（新→旧）：S4 `8a74898` → S3 `bd04472`+`69a67f8` → docs 入库治理 `b800e47` → 一致性修订 `911c4ba` → `8a898af docs: STATUS` → `cad77db fix: prompt` → `cd8038a add deepseek` → `08b6ccf add gemini` → `0e7dbda s1 finished`。
- `docs/` 已正常跟踪，改动**不再需要 `git add -f`**。
