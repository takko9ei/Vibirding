# Vibirding · 开发状态盘点（STATUS）

> 本文件是“当前进度快照”，给冷启动（无上下文）的人快速对齐用。
> **唯一事实来源仍是 [docs/architecture.md](architecture.md)**；本文若与 architecture 冲突，以 architecture 为准。
> 最后更新：S6（budget 上限 + 工具报错容错 + 日期注入）已提交、S9（批量笔记）已登记之后；HEAD = `bb49219`，工作树干净。

---

## 1. 项目是什么
一个个人级“观鸟速记” agent（Python）：把一段随手记的、乱糟糟的观鸟笔记（可带本地照片）整理成结构化记录——必要时调工具做视觉鉴种 / 季节·分布核验 / 查个人历史，写入权限闸后落盘成一条 `Observation`，之后还能从日志查回。
完整架构、目录、数据结构（§4）、契约（§6）、切片路线（§10）见 **[docs/architecture.md](architecture.md)（唯一事实来源）**。

---

## 2. 切片完成情况（对照 architecture §10，S1–S8 + 已登记的 S9）

| 切片 | 状态 | 实际交付 / 对应文件 |
|---|---|---|
| **S1** | ✅ done | **离线循环骨架**（MockClient，零成本跑通 model→tool→model）。`vibirding/schemas.py`（5 个数据结构，**最先锁**）、`llm/mock.py`、`agent/loop.py`（`run_agent_turn`，签名自此锁定）、`agent/prompt.py`、`tools/registry.py`（Tool 协议 + ToolContext + 统一执行管线）、`tools/log_read.py`（曾是假 read_log，S5 改真读）、`harness/{trace,budget,permissions}.py`（薄版）、`config.py`、`scripts/{run_s1,check_s1}.py`。 |
| **S2** | ✅ done | **接真模型产出结构化 Observation**。`vibirding/llm/deepseek_client.py`（**DeepSeekClient**：openai SDK、OpenAI 兼容端点、`deepseek-v4-flash`、**手动函数调用**）为运行时；`llm/client.py`（GeminiClient）保留为备用 provider；`config.py` 读 `DEEPSEEK_API_KEY`；入口 `scripts/run_deepseek.py`、`scripts/run_s2.py`（Gemini，备用参考）。 |
| **S3** | ✅ done | **range_check：eBird 季节/分布核验（范式B）**——`place+date → 当地近期实际记录的物种清单`，模型在清单内挑种。`tools/range_check.py`（httpx 调 `obs/geo/recent`，10s 超时，去重/中文名/截断；容错降级）、`tools/locations.py`（地名→坐标预存表，8 点 + `resolve_place`）、`config.py`（eBird 常量，俗名 **`sppLocale=zh_SIM`**）、`agent/prompt.py`、`scripts/{check_s3,run_s3}.py`。**踩坑**：俗名参数是 `sppLocale` 不是 `locale`。 |
| **S4** | ✅ done | **bird_id：懂鸟(hholove) 视觉鉴种**，补裁决第3条（无种名+有图 → 图片定种，source="bird_id"）。`tools/bird_id.py`（**异步两步+轮询全封在 run() 内**：上传长超时、取结果 timeout30、轮询≤5；返回数组 `[code,payload]` 解析、中文名按 `|` 切首段、置信度 0~100；1008/1009 未认出→ok=True）、`config.py`（HHO 常量）、`agent/prompt.py`、`scripts/{check_s4,run_s4}.py`。**踩坑**：上传海外慢须长超时；poll 用 urlencoded `data=`。 |
| **S5** | ✅ done | **append_log 写日志 + 权限闸**，第一次持久写入。`memory/log.py`（`Log.append` 只追加 / `Log.query` 顺序扫描过滤，append-only、目录自动建）、`tools/log_write.py`（`append_log`，risk=**write**，唯一过权限闸；id/timestamp 由 `run()` 补）、`tools/log_read.py`（改真读 `Log.query`、可注入 Log）、`harness/permissions.py`（真实现：可注入审批回调、read→allow、write→回调、支持“本回合一直允许”、无回调 fail-closed）、`config.py`(+`OBSERVATIONS_PATH`)、`agent/prompt.py`（“输出 JSON”→“调用 append_log”）、`scripts/{check_s5,run_s5}.py` + `check_s1` 连带修订。**端到端已手动验收通过**（写入+权限闸+读回）。 |
| **S6** | ✅ done | **纯鲁棒性：budget 完整化 + 工具报错容错 + 日期注入**。`harness/budget.py`（+`observe`/`max_tokens`，token 触顶→`stop_reason="max_tokens"`；`tick`/`stop_reason` 签名不变；`max_tokens=None` 向后兼容）、`agent/loop.py`（**仅加一行** `budget.observe(resp.usage)`，签名/控制流不变）、`tools/failures.py`（`tool_failure` 统一失败文案）、`tools/range_check.py`（补非-httpx 异常捕获）、`memory/log.py`（`query` 坏行跳过）、`tools/bird_id.py`（ok=False 套统一文案）、`agent/prompt.py`（加“工具失败处理策略”段 + `today_hint()` 日期注入）、`scripts/{check_s6,run_s6}.py`。验收：check_s6 **24/24** + 回归 check_s1/s3/s4/s5 全绿。 |
| **S7** | ⬜ 未开始 | `evals`：`evals/tasks.yaml` + `evals/run_evals.py` + 通过率。`evals/` 目录尚不存在。注：`scripts/check_s*.py` 是各切片的离线自检，**不是** eval 框架。 |
| **S8** | ⬜ 未开始（部分） | `cli` 打磨 + `README` + `DECISIONS.md`。现状：`DECISIONS.md` 已建（4 条取舍）、`README.md` 很简、`vibirding/cli.py` 未建。 |
| **S9** | 🗒️ 已登记，未实现 | **批量笔记**（同登记于 architecture §11）：一篇笔记含多条记录、各记录可带各自照片 URL，一次输入 → 多条 Observation。**依赖 S1–S8 单条主线完整且经 eval 验证后再做**，见 §6。 |

---

## 3. 当前所处切片 / 下一步
- **现在**：S1–S6 全部完成并提交（HEAD `bb49219`，工作树干净）。四个工具 `read_log + range_check + bird_id + append_log` 均已接入；agent 能整理笔记→（鉴种/核验）→过权限闸写盘→查回；budget 有步数+token 双上限与优雅收尾；工具失败统一容错、运行时日期已注入。离线自检五套全绿（check_s1 28 / s3 19 / s4 30 / s5 31 / s6 24）。
- **下一步 = 开工 S7（evals：10–15 用例 + 通过率，验收“一条命令出通过率”）**。要点：
  1. `evals/tasks.yaml`：每条含 `input_note` / `photo_url` / `expected`（`place`/`count`/`must_call_tools`/`species_in: [...,null]`）；
  2. `evals/run_evals.py`：对每条跑 agent，比对①结构化字段②是否调了该调的工具③是否乱调写入，输出**通过率 + 逐条 pass/fail**；
  3. 用 MockClient 还是低温真 DeepSeek 跑用例——开工前先拍板（见 §7）；
  4. eval 不能污染真 `data/observations.jsonl`：用注入式自动 approver + 临时 Log（复用 S5/S6 范式）。
- 铁律：开工前先在 architecture 确认契约（§9 eval 设计 / §4 数据结构），再写代码；一次一个切片、commit per slice。

---

## 4. 与 architecture.md 已对齐的最近重要改动（时间倒序，每条三行内）

1. **S9 批量笔记登记**（commit `bb49219`）
   - 在 architecture §11 + 本文件 §6 登记“批量笔记”为未来切片（暂定 S9），**仅登记、不实现**。
   - 明确依赖 S1–S8 单条主线完整 + eval 验证后再做。

2. **S6 鲁棒性切片**（commit `15b51d3`）
   - budget 加 token 预算（`observe`/`max_tokens`，签名不变）；loop 加一行喂 token；工具失败文案统一（`tools/failures.py`）+ range_check 坏 JSON / log.query 坏行容错。
   - 搭车做运行时日期注入（`today_hint()`，入口层拼进 system，修“年份猜错”）。

3. **S5 写日志 + append_log + 权限闸**（commit `68d713e`）
   - 新建 `memory/log.py` + `tools/log_write.py`（write 工具）；read_log 改真读；permissions 长成真实现；prompt 由“输出 JSON”改“调用 append_log”，落地架构 §8 回合3/4。
   - 日志句柄走构造器注入（不动 registry 的 ToolContext）。

4. **S4 `bird_id` 视觉鉴种**（commit `8a74898`）
   - 接懂鸟(hholove)：异步两步（上传+轮询）全封在 `run()` 内、补裁决第3条；入参本地 `image_path`（非 URL）。

5. **S3 `range_check` 季节/分布核验**（commit `69a67f8` + `bd04472`）
   - 接 eBird `obs/geo/recent`（范式B），补“无图仅描述”短板；踩坑：俗名参数须 `sppLocale=zh_SIM`。

6. **更早的对齐**（commit `b800e47` / `cad77db` / 等）
   - docs 入库治理（architecture.md 首次进 git）；物种来源优先级四分支裁决写入 prompt；range_check 升格为正式 S3、运行时由 Gemini 切 DeepSeek；read_log 正名为“个人历史/弱先验”。

---

## 5. 关键约定速查（冷启动对齐，提炼自 CLAUDE.md + architecture）
- **唯一事实来源**：`docs/architecture.md`；改接口/数据结构/契约 → **先改文档，再改代码**。
- **运行时模型**：DeepSeek（OpenAI 兼容端点，`openai` SDK，`deepseek-v4-flash`，temperature=0）；GeminiClient 留作备用 provider。Claude Code 只是开发工具，与运行时模型无关。
- **provider 中立**：循环/工具/记忆/eval 只认内部归一化类型（`ModelResponse`/`ToolCall`/`ToolResult`/`Observation`/`TraceEvent`）；provider 原生形状封死在 `llm/deepseek_client.py`。
- **架构形态**：**单 agent + 工具循环**（model→tool→model）；工具统一契约：find → schema 校验 → 若 write 过权限闸 → run → 归一化 `{ok, output}`。
- **手动函数调用**：只声明 tools、自己执行、自己把结果作为 `role="tool"` 消息回填；**不用任何 SDK 的自动函数执行**。
- **外部 API**：用 `httpx`，**必设超时**；失败在工具 `run()` 内归一化成 ToolResult，绝不抛裸栈（坏结构/解析失败也在 run() 内显式接，给定制文案 + 统一前缀，见 `tools/failures.py`）。
- **流程纪律**：**一次只实现一个模块/切片**；每个能跑的切片停下 review 再 `git commit`（**commit per slice**）。
- **代码风格**：清晰**英文注释** + 关键逻辑写完用**中文**逐段解释；与人用中文交流；倾向最小实现。
- **运行环境**：一律用 `.venv\Scripts\python.exe`（**不是**全局 anaconda，它没装 openai/httpx）；命令用 **PowerShell**（Windows）。
- **包名**：可导入包小写 `vibirding`（仓库根文件夹是 `Vibirding`）。
- **不可擅改**：`loop.py` / `schemas.py` / `registry.py` 的结构与签名；budget `tick()/stop_reason()` 签名（S1 锁定）。S6 那处 loop 一行 `budget.observe` 是经用户批准、不改签名/控制流的例外。
- **密钥**：均从 `config.py` 经 python-dotenv 读项目根 `.env`，不硬编码——`DEEPSEEK_API_KEY` / `EBIRD_API_KEY` / `HHO_API_KEY`（备用 `GEMINI_API_KEY`）。

---

## 6. 尚未实现但已规划（待办 + 所在切片）

> **准确性提示**：早期计划/模板里列为“待办”的 **range_check 真正接 eBird、视觉鉴种、以及三个待解小事（地名→坐标预存表 / eBird 名单按近期收窄 / 中文名用 `sppLocale`）均已在 S3/S4 落地**，**不再是待办**。以下是真正剩余的工作：

- **S7（下一步）**：evals（10–15 用例 + 通过率）。eval 时观察“range_check 清单内挑种”准确度（曾见模型对“黑头红腿小涉禽”选蛎鹬而非黑翅长脚鹬）；range_check 名单收窄目前只按 `back` 天 + 展示截断（未按目标科）、坐标表仅 8 点 exact-match——按需在此优化。
- **S8**：`cli` 打磨 + `README`（让别人能 clone 跑起来）+ 继续补 `DECISIONS.md`。
- **S9（已登记，未实现）**：批量笔记——一篇含多条记录、各带各自照片 URL → 多条 Observation。待解点：多次/批量 `append_log` 的**权限确认粒度**、**图文配对**、**部分失败处理**、**预算放大**、**多记录 eval**。依赖 S1–S8 单条主线完整且经 eval 验证后再做（同登记于 architecture §11）。
- **§11 进阶（v1 之后）**：核验子 agent（多 agent，把 bird_id + range_check + read_log 合起来判 flags）；本地模型（OpenAI 兼容端点，`--local`，只动 `llm/` 一个文件）；大工具结果移出 prompt / SQLite 替代 JSONL（数据量大了再说）。

---

## 7. 当前已知未决 / 需人拍板
- **S7 用 Mock 还是真模型跑用例？** architecture §9 给了两选项：MockClient（零成本，但每条要写脚本化响应）或低温真 DeepSeek（更真实但花钱/不确定）。开工前需拍板（建议默认 Mock，真模型作可选开关）。
- **S6 端到端 `run_s6.py` 真模型触发**：离线 check_s6 24/24 已绿；live 三种触发（`--max-steps 1` / `--max-tokens 50` / `--break-ebird`）可手动跑看 trace，非阻塞。
- **DeepSeek 账户额度**：真模型验收时遇到过 `429`（额度耗尽）/`503`（过载）。用户已表示额度不用担心。
- **`scripts/run_s4.py` 的 `TESTIMGS_DIR` 硬编码**到桌面 `C:\Users\Takko\Desktop\testimgs`（个人用例集，非交付目录）：每张 `<stem>.jpg` 配一份 `<stem>_discribe.txt`，`run_s4.py <stem>` 选图、不带参随机。
- **`scripts/run_s2.py`（Gemini 入口）** 暂留作备用 provider 参考，最终可能删。

---

## 8. git 状态
- **最近一次 commit（HEAD）**：`bb49219 chore: docs optimize`（= S9 批量笔记登记，改 architecture §11 + STATUS §6）。
- **未提交的改动**：本次盘点写完后，仅 `docs/STATUS.md` 一个文件——确认无误即 commit。
- 切片提交链（新→旧）：S9登记 `bb49219` → S6 `15b51d3` → S5 `68d713e` → S4 `8a74898`（+ 文档 `fdbda66`）→ S3 `bd04472`+`69a67f8` → docs 入库治理 `b800e47` → `cad77db fix: prompt` → `cd8038a add deepseek` → `08b6ccf add gemini` → `0e7dbda s1 finished`。
- `docs/` 已正常跟踪，改动**不再需要 `git add -f`**。
