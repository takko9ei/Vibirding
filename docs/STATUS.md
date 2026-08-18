# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：**S8（cli + README + DECISIONS）完成 → v1 收尾**。新增 `vibirding/cli.py`（交付级入口，记录/查询两用）+ `vibirding/__main__.py`（`python -m vibirding`）+ 根 `.env.example`；README 重写、DECISIONS 补到 12 条、architecture §3 加 `__main__.py`/`.env.example`/入口层意图前言说明。回归：check_sX 132/132、离线 eval 13/13。父提交 = `7c4b68f`（S7）。

---

## 1. 项目是什么
一个个人级“观鸟速记” agent（Python）：把一段随手记的、乱糟糟的观鸟笔记（可带本地照片）整理成结构化记录——必要时调工具做视觉鉴种 / 季节·分布核验 / 查个人历史，经写入权限闸后落盘成一条 `Observation`，之后还能从日志查回。
完整架构、目录、数据结构（§4）、契约（§6）、切片路线（§10）见 **[docs/architecture.md](architecture.md)（唯一事实来源）**。

---

## 2. 切片完成情况（对照 architecture §10，S1–S8 + 已登记的 S9）

| 切片 | 状态 | 实际交付 / 对应文件 |
|---|---|---|
| **S1** | ✅ done | **离线循环骨架**（MockClient，零成本跑通 model→tool→model）。`vibirding/schemas.py`（5 个数据结构，**最先锁**）、`llm/mock.py`、`agent/loop.py`（`run_agent_turn`，签名自此锁定）、`agent/prompt.py`、`tools/registry.py`（`ToolManager` + `Tool` 协议 + `ToolContext` + 统一执行管线）、`tools/log_read.py`（曾是假 read_log，S5 改真读）、`harness/{trace,budget,permissions}.py`（薄版）、`config.py`、`scripts/{run_s1,check_s1}.py`。 |
| **S2** | ✅ done | **接真模型产出结构化 Observation**。`vibirding/llm/deepseek_client.py`（**DeepSeekClient**：openai SDK、OpenAI 兼容端点、`deepseek-v4-flash`、**手动函数调用**）为运行时；`llm/client.py`（GeminiClient）保留为备用 provider；`config.py` 读 `DEEPSEEK_API_KEY`；入口 `scripts/run_deepseek.py`、`scripts/run_s2.py`（Gemini，备用参考）。 |
| **S3** | ✅ done | **range_check：eBird 季节/分布核验（范式B）**——`place+date → 当地近期实际记录的物种清单`，模型在清单内挑种。`tools/range_check.py`（httpx 调 `obs/geo/recent`，10s 超时，去重/中文名/截断；容错降级）、`tools/locations.py`（地名→坐标预存表，8 点 + `resolve_place`）、`config.py`（eBird 常量，俗名 **`sppLocale=zh_SIM`**）、`agent/prompt.py`、`scripts/{check_s3,run_s3}.py`。**踩坑**：俗名参数是 `sppLocale` 不是 `locale`。 |
| **S4** | ✅ done | **bird_id：懂鸟(hholove) 视觉鉴种**，补裁决第3条（无种名+有图 → 图片定种，source="bird_id"）。`tools/bird_id.py`（**异步两步+轮询全封在 run() 内**：上传长超时、取结果 timeout30、轮询≤5；返回数组 `[code,payload]` 解析、中文名按 `|` 切首段、置信度 0~100；1008/1009 未认出→ok=True）、`config.py`（HHO 常量）、`agent/prompt.py`、`scripts/{check_s4,run_s4}.py`。**踩坑**：上传海外慢须长超时；poll 用 urlencoded `data=`。 |
| **S5** | ✅ done | **append_log 写日志 + 权限闸**，第一次持久写入。`memory/log.py`（`Log.append` 只追加 / `Log.query` 顺序扫描过滤，append-only、目录自动建、坏行跳过）、`tools/log_write.py`（`append_log`，risk=**write**，唯一过权限闸；id/timestamp 由 `run()` 补）、`tools/log_read.py`（改真读 `Log.query`、可注入 Log）、`harness/permissions.py`（真实现：可注入审批回调、read→allow、write→回调、支持“本回合一直允许”、无回调 fail-closed）、`config.py`(+`OBSERVATIONS_PATH`)、`agent/prompt.py`（“输出 JSON”→“调用 append_log”）、`scripts/{check_s5,run_s5}.py`。**端到端已手动验收通过**（写入+权限闸+读回）。 |
| **S6** | ✅ done | **纯鲁棒性：budget 完整化 + 工具报错容错 + 日期注入**。`harness/budget.py`（+`observe`/`max_tokens`，token 触顶→`stop_reason="max_tokens"`；`tick`/`stop_reason` 签名不变；`max_tokens=None` 向后兼容）、`agent/loop.py`（**仅加一行** `budget.observe(resp.usage)`，签名/控制流不变）、`tools/failures.py`（`tool_failure` 统一失败文案 “⚠ <tool> 暂不可用：…”）、`tools/range_check.py`（补非-httpx 异常捕获）、`memory/log.py`（`query` 坏行跳过）、`tools/bird_id.py`（ok=False 套统一文案）、`agent/prompt.py`（加“工具失败处理策略”段 + `today_hint()` 日期注入）、`scripts/{check_s6,run_s6}.py`。**日期注入已覆盖全部 6 个真模型入口**（run_s2/s3/s4/s5/s6 + run_deepseek）。验收：check_s6 **24/24** + 回归全绿。 |
| **S7** | ✅ done | **evals：固定用例 + 通过率，一条命令出结果**。`evals/tasks.yaml`（13 条题目，无图）+ `evals/answers.yaml`（13 条 expected，**答案单独一份、防泄题**）+ `evals/run_evals.py`（**两档**：离线 MockClient+桩工具 / 在线真 DeepSeek，`--online` 切换；比对器覆盖 11 类断言键，隔离用临时 Log+注入 approver+真日志污染守卫）+ `evals/REPORT.md`（首跑报告）。`requirements.txt` 加 `pyyaml`。**结果**：离线 **13/13**、在线 **11/13(84.6%)**、check_sX 仍 132/132。两条在线 FAIL 见 §7 与 REPORT.md。注：`scripts/check_s*.py` 是各切片离线自检，**不是** eval 框架。 |
| **S8** | ✅ done | **v1 收尾：cli 打磨 + README + DECISIONS**。`vibirding/cli.py`（交付级统一入口：注册四工具、记录/查询两用由模型据入口层意图前言自判、`--image`/`--yes`/`--verbose`/`--max-steps`、缺 key/网络失败给人类可读提示不抛裸栈）+ `vibirding/__main__.py`（`python -m vibirding`）+ 根 `.env.example`（三把 key 占位）。`README.md` 重写为项目门面（含 mermaid 数据流 / 快速开始 / eval 真实数字 / 已知边界）。`DECISIONS.md` 6→**12 条**（补：手写 harness 不用框架、写入过闸、JSONL 不用 DB、手动函数调用、eval 分文件+合成理想模型、CLI 不设子命令）。**只加入口/文档，未改 agent 任何行为**：check_sX 132/132、离线 eval 13/13。 |
| **S9** | 🗒️ 已登记，未实现 | **批量笔记**（同登记于 architecture §11）：一篇笔记含多条记录、各记录可带各自的本地照片路径 `image_path`，一次输入 → 多条 Observation。**依赖 S1–S8 单条主线完整且经 eval 验证后再做**，见 §6。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：**S1–S8 全部完成 → v1 收尾**。四工具 `read_log + range_check + bird_id + append_log` 全接入；agent 能整理笔记→（鉴种/核验）→过权限闸写盘→查回；budget 步数+token 双上限与优雅收尾；工具失败统一容错；日期锚点覆盖所有入口。测量体系：`evals/` 两档一条命令出通过率（离线 13/13 / 在线 11/13）。**交付面**：`vibirding/cli.py` 统一入口（`python -m vibirding` 记录/查询两用，已端到端冒烟通过）+ README 门面 + `.env.example` + 12 条 DECISIONS，可 clone 跑起来。
- **下一步 = 未来切片（v1 已完，非必须）**：S9 批量笔记（一篇多记录、各带图 → 多条 Observation，待解权限粒度/图文配对/部分失败/预算放大/多记录 eval）；§11 进阶（核验子 agent / 本地模型 `--local` / SQLite 替代 JSONL / 大工具结果移出 prompt）。均登记于 architecture §10-§11，按需再开工。
- 铁律：改接口/数据结构先改 architecture 再改代码；一次一个切片、commit per slice。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序，每条三行内）

0. **S8 v1 收尾切片**（本轮，随本提交入库）
   - 新建 `vibirding/cli.py`（交付级统一入口，记录/查询两用由模型据**入口层意图前言**自判、`--image`/`--yes`/`--verbose`）+ `vibirding/__main__.py`（`python -m vibirding`）+ 根 `.env.example`；重写 `README.md`；`DECISIONS.md` 6→12 条。
   - architecture §3 加 `__main__.py`/`.env.example`/入口层意图前言说明（`SYSTEM_PROMPT` 常量与工具行为均不改）。**只加入口/文档、未改 agent 行为**——check_sX 132/132、离线 eval 13/13。
   - 端到端冒烟通过：记录路径（→append_log 写入）与查询路径（→read_log 读回、不写盘）均正确路由；演示数据已清理，真日志回到初始空态。

1. **S7 evals 切片**（commit `7c4b68f`）
   - `evals/{tasks,answers}.yaml`（题目/答案**分文件防泄题**）+ `run_evals.py`（两档）+ `REPORT.md`；`requirements.txt` 加 `pyyaml`。architecture §9 评分契约扩成 11 类断言键。
   - 结果：离线 13/13、在线 11/13(84.6%)；两条 FAIL（t04 用户指定种名漏季节核验 / t02 模糊量词未估值）忠实量化、**未改 prompt 迎合**，详见 `evals/REPORT.md`。

2. **`photo_url → image_path` 术语统一**（commit `8d90da0`）
   - 早期文档遗留的 `photo_url` / “照片 URL” 与 S4 的实际实现不符：`bird_id` 的入参一直是**本地路径 `image_path`**（`tools/bird_id.py` 会做 `Path().exists()` 校验，明确不吃 URL）。纯术语，无代码改动。

3. **文档一致性同步 + 修正过时表述**（commit `b071589`）
   - architecture §3 补 `today_hint()`、§9 写入 S7 跑法决策与懂鸟配额约束；**§8 删掉“range_check 尚未实现”的过时注**（S3 早已接入，该注会误导冷启动者）。
   - DECISIONS.md 修正“v1 暂不接 eBird”的过时代价行，并新增两条取舍（日期注入放入口层 / S7 用真 DeepSeek）。

4. **S7 跑法决策落盘**（commit `bc87963`）
   - 定为**真 DeepSeek + 脚本内限调用次数**（不用 Mock：Mock 测不出模型真实抽取/裁决能力）；
   - 记下真正的配额瓶颈是**懂鸟(hholove) 仅 50 次免费调用**，而非 DeepSeek（很便宜）。

5. **日期注入补齐到全部入口**（commit `b67d50f`）
   - `today_hint()` 原先只接进 run_s6，其余 5 个真模型入口漏接、模型仍在猜“今天”（run_s5 甚至写死 `2025-06-27`）；现 6 个入口统一 `SYSTEM_PROMPT + "\n\n" + today_hint()`。
   - MockClient 入口（run_s1/check_s1）刻意不接——脚本化假模型下日期锚点无意义。

6. **`ToolRegistry → ToolManager` 全仓改名**（commit `f96f356`）
   - 类定义 + 全部脚本/注释/`tools/__init__.py`/architecture §3·§6 同步，**零残留**；纯重命名无行为变化，改名后 132/132 回归全绿。

7. **S6 鲁棒性切片**（commit `15b51d3`）
   - budget 加 token 预算（`observe`/`max_tokens`，签名不变）；loop 加一行喂 token；工具失败文案统一 + range_check 坏 JSON / log.query 坏行容错；搭车做运行时日期注入机制。

8. **S5 写日志 + append_log + 权限闸**（commit `68d713e`）
   - 新建 `memory/log.py` + `tools/log_write.py`（唯一 write 工具）；read_log 改真读；permissions 长成真实现；prompt 由“输出 JSON”改“调用 append_log”，落地架构 §8 回合3/4。

9. **更早的对齐**（`8a74898` S4 / `69a67f8`+`bd04472` S3 / `b800e47` / `cad77db` 等）
   - S4 接懂鸟视觉鉴种（异步两步全封 run() 内）；S3 接 eBird `obs/geo/recent`（踩坑：俗名须 `sppLocale=zh_SIM`）；docs 入库治理（architecture.md 首次进 git）；物种来源优先级四分支裁决写入 prompt；range_check 升格为正式 S3、运行时由 Gemini 切 DeepSeek；read_log 正名为“个人历史/弱先验”（权威核验剥离给 range_check）。

---

## 5. 关键约定速查（冷启动对齐，提炼自 CLAUDE.md + architecture）
- **唯一事实来源**：`docs/architecture.md`；改接口/数据结构/契约 → **先改文档，再改代码**。
- **运行时模型**：DeepSeek（OpenAI 兼容端点，`openai` SDK，`deepseek-v4-flash`，temperature=0）；GeminiClient 留作备用 provider。Claude Code 只是开发工具，与运行时模型无关。
- **provider 中立**：循环/工具/记忆/eval 只认内部归一化类型（`ModelResponse`/`ToolCall`/`ToolResult`/`Observation`/`TraceEvent`）；provider 原生形状封死在 `llm/deepseek_client.py`。
- **架构形态**：**单 agent + 工具循环**（model→tool→model）；工具统一契约由 `ToolManager` 收口：find → schema 校验 → 若 write 过权限闸 → run → 归一化 `{ok, output}`。
- **手动函数调用**：只声明 tools、自己执行、自己把结果作为 `role="tool"` 消息回填；**不用任何 SDK 的自动函数执行**。
- **外部 API**：用 `httpx`，**必设超时**；失败在工具 `run()` 内归一化成 ToolResult，绝不抛裸栈（坏结构/解析失败也在 run() 内显式接，走 `tools/failures.py` 的统一文案 + 回退建议）。
- **流程纪律**：**一次只实现一个模块/切片**；每个能跑的切片停下 review 再 `git commit`（**commit per slice**）。
- **代码风格**：清晰**英文注释** + 关键逻辑写完用**中文**逐段解释；与人用中文交流；倾向最小实现。
- **运行环境**：一律用 `.venv\Scripts\python.exe`（**不是**全局 anaconda，它没装 openai/httpx）；命令用 **PowerShell**（Windows）。
- **包名**：可导入包小写 `vibirding`（仓库根文件夹是 `Vibirding`）。
- **不可擅改**：`loop.py` / `schemas.py` / `registry.py` 的结构与签名；budget `tick()/stop_reason()` 签名（S1 锁定）。S6 那处 loop 一行 `budget.observe` 是经用户批准、不改签名/控制流的例外。
- **eval 是纯观测**：`evals/` 只跑现有 agent、只读结果打分，**绝不改被测对象**（loop/工具/prompt）；两档一条命令（`run_evals.py` 默认离线 / `--online` 真模型），隔离用临时 Log+注入 approver+真日志污染守卫。
- **交付入口**：正式入口是 `vibirding/cli.py`（`python -m vibirding "<笔记或问句>" [--image/--yes/--verbose]`）；记录/查询两用由模型据**入口层意图前言**自判（前言在 cli 拼进 system，`SYSTEM_PROMPT` 常量不变）。`scripts/run_*.py` 仅开发期脚手架，非交付入口。
- **密钥**：均从 `config.py` 经 python-dotenv 读项目根 `.env`，不硬编码——`DEEPSEEK_API_KEY` / `EBIRD_API_KEY` / `HHO_API_KEY`（备用 `GEMINI_API_KEY`）；根有 `.env.example` 占位模板。

---

## 6. 尚未实现但已规划（待办 + 所在切片）

> **准确性提示**：早期计划/模板里列为“待办”的 **range_check 真正接 eBird、视觉鉴种、以及三个待解小事（地名→坐标预存表 / eBird 名单按近期收窄 / 中文名用 `sppLocale`）均已在 S3/S4 落地**，**不再是待办**。以下是真正剩余的工作：

- **S7（已完成）**：evals 已交付（`evals/`，两档 + 报告）。**遗留可优化项**：① 两条在线 FAIL 是模型/prompt 边界（t04 用户指定种名时不必然做季节核验；t02 模糊量词"十几只"不估值），若日后想让其稳定通过属"核验子 agent / prompt 分支1 强化"课题、**当前不改**；② range_check 名单收窄仍只按 `back` 天 + 展示截断（未按目标科）、坐标表仅 8 点 exact-match；③ 用例集现 13 条全无图——带图用例受懂鸟 50 次额度限制暂缺（`--online-images` 已备好开关）。
- **S8（已完成）**：cli 入口 + README + `.env.example` + DECISIONS(12 条) 全部交付，v1 收尾。**遗留可优化项**：① README 的 mermaid 若在某些渲染器不显示可退化为文字图；② CLI 记录/查询路由靠模型，极端问法可能误判（无硬保证，`--yes` 时有写前摘要兜底）；③ 无 `pyproject.toml`/console_scripts，入口只有 `python -m vibirding`（个人级够用）。
- **S9（已登记，未实现）**：批量笔记——一篇含多条记录、各带各自的本地照片路径 `image_path` → 多条 Observation。待解点：多次/批量 `append_log` 的**权限确认粒度**、**图文配对**、**部分失败处理**、**预算放大**、**多记录 eval**。依赖 S1–S8 单条主线完整且经 eval 验证后再做（同登记于 architecture §11）。
- **§11 进阶（v1 之后）**：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）；本地模型（OpenAI 兼容端点，`--local`，只动 `llm/` 一个文件）；大工具结果移出 prompt / SQLite 替代 JSONL（数据量大了再说）。

---

## 7. 当前已知未决 / 需人拍板
- **⚠ 最重要的资源约束：懂鸟(hholove) API 只有 50 次免费调用。** 它是 `bird_id` 的后端，每跑一次 `run_s4.py` 或一条带图 eval 用例就消耗一次。S7 用例集现**全为无图**（不碰此额度）；日后加带图用例须严格限量，在线跑用 `--online-images` 才放开。
- **S7 在线两条 FAIL（已知、非阻塞）**：t04 红嘴鸥（用户指定种名时漏 range_check 季节核验）、t02 家燕"十几只"（模糊量词未估值 count）。均忠实量化、未改 prompt 迎合；详见 `evals/REPORT.md`。
- **S6 端到端 `run_s6.py` 真模型触发未实测**：离线 check_s6 24/24 已绿；live 三种触发（`--max-steps 1` / `--max-tokens 50` / `--break-ebird`）可手动跑看 trace，非阻塞。（S5 端到端已手动验收通过。）
- **`scripts/run_s4.py` 的 `TESTIMGS_DIR` 硬编码**到桌面 `C:\Users\Takko\Desktop\testimgs`（个人用例集，非交付目录）：每张 `<stem>.jpg` 配一份 `<stem>_discribe.txt`，`run_s4.py <stem>` 选图、不带参随机。
- **`scripts/run_s2.py`（Gemini 入口）** 暂留作备用 provider 参考，最终可能删。
- **DeepSeek 账户额度**：曾遇 `429`/`503`；用户表示 DeepSeek 很便宜、额度不必担心（瓶颈在懂鸟）。
- 其余无阻塞性未决项；**S1–S8 全部完成，v1 收尾**。后续为可选切片（S9 批量 / §11 进阶），按需再开。

---

## 8. git 状态
- **父提交（本次 S8 提交前的 HEAD）**：`7c4b68f feat: s7 evals — fixed cases + pass rate (two lanes)`。其前 `8d90da0`(photo_url 统一) / `11b9fe0`(STATUS) / `b071589`(文档一致性同步) / `bc87963`(S7决策)。
- **本次 S8 提交内容**：新增 `vibirding/cli.py`、`vibirding/__main__.py`、根 `.env.example`；改 `README.md`(重写)、`DECISIONS.md`(6→12 条)、`docs/architecture.md`(§3)、`docs/STATUS.md`。**agent 行为零改动**（loop/schemas/registry/工具/prompt 未动）；check_sX 132/132、离线 eval 13/13。演示日志已清理，`data/observations.jsonl` 回到初始空态。
- 切片提交链（新→旧）：S8 v1收尾(本次) → S7 evals `7c4b68f` → photo_url 统一 `8d90da0` → STATUS `11b9fe0` → 文档同步 `b071589` → S7决策 `bc87963` → 日期注入 `b67d50f` → STATUS `98bf526` → 改名 `f96f356` → status 修订 `f75d9a2` → 快照 `df55da9` → S9登记 `bb49219` → S6 `15b51d3` → S5 `68d713e` → S4 `8a74898`（+ 文档 `fdbda66`）→ S3 `bd04472`+`69a67f8` → docs 入库治理 `b800e47` → `cad77db fix: prompt` → `cd8038a add deepseek` → `08b6ccf add gemini` → `0e7dbda s1 finished`。
- `docs/` 已正常跟踪，改动**不再需要 `git add -f`**。
