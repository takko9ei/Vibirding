# Vibirding · 观鸟速记 Agent — 架构设计文档

> 本文档是后续 vibe coding 的**唯一事实来源**。原则：**先锁结构与接口，再写实现**。
> 任何一次 coding session 开始前，先把这份文档发给 AI 当上下文；任何对结构/契约的改动，先改这份文档，再改代码。
>
> **运行时大模型：DeepSeek**（OpenAI 兼容端点，`openai` SDK，模型 `deepseek-v4-flash`，手动函数调用）。Claude Code 只是开发工具，与运行时模型无关，二者互不影响。

---

## 1. 产品范围

**一句话**：在野外随手丢一段乱糟糟的观鸟笔记（可带一张照片 URL），程序自动把它整理成结构化记录、（有照片时）调鉴种 API、对地点/季节做合理性核验、写进你的个人观鸟日志；之后还能从日志里回答查询。

**核心流程**

```
乱糟糟的笔记(+可选照片url)
      │
      ▼
  [Agent 回合]  ── 需要时调用工具 ──►  bird_id / read_log
      │                                      │
      │  推理出一条结构化 Observation        │
      ▼                                      ▼
  调 append_log(写入，需过权限闸) ──► 追加到 observations.jsonl
      │
      ▼
  给用户一段最终总结
   （每一步都写一行 trace）
```

**做（in scope, v1）**：单 agent + 工具循环、结构化记录、鉴种 API 适配器、读/写日志、写入权限闸、步数预算、JSONL 轨迹、固定 eval 集。

**不做（out of scope, v1）**：MCP、花哨 TUI、三套上下文压缩、会话 fork、多 provider（只留抽象接缝）、流式输出、多 agent 编排。

> **重要的右尺寸判断**：你单条笔记的对话很短（一句话 → 几次工具调用），**根本不会撑爆上下文**，所以 v1 不需要任何压缩机制，只需 `max_steps` 兜底。别把 MiniCode 为"通用编码助手"付的税也背上。

---

## 2. 设计原则（借鉴 MiniCode，砍到个人级）

1. **循环优先**：系统围绕 `model → tool → model` 这一个回合循环组织。
2. **工具即协议**：所有工具走同一套"注册 → schema 校验 → 执行 → 归一化 `{ok, output}`"。
3. **权限在执行路径内**：写入类操作（`append_log`）在真正执行前必须过闸，不是事后补。
4. **记忆是 append-only 文件**：观鸟日志就是一个只追加的 JSONL，永不改写历史行。
5. **可观测性内建**：每一步都落一行结构化 trace，既是 debug 工具也是面试 demo。
6. **eval 是项目的一部分**：固定测试集 + 通过率，不是"我试了下好像行"。
7. **provider 中立**：循环/工具/记忆/eval 全部只认内部归一化类型，不认 DeepSeek/OpenAI 的原生形状；所有 provider 特有的东西封死在 `llm/deepseek_client.py` 一个文件里。

---

## 3. 目录结构

```
Vibirding/
├── README.md
├── DECISIONS.md                 # 每个取舍记三行 ← 面试逐字稿
├── requirements.txt
├── vibirding/                    # 主包（可导入的 Python 包，小写）
│   ├── __init__.py
│   ├── config.py                # 路径、模型名(deepseek-v4-flash)、base_url、从 .env 读 DEEPSEEK_API_KEY
│   ├── schemas.py               # ★所有数据结构(pydantic)，最先锁
│   ├── llm/
│   │   ├── deepseek_client.py   # 运行时客户端：DeepSeekClient(openai SDK, OpenAI 兼容)
│   │   ├── client.py            # 备用 provider：GeminiClient(google-genai)（保留）
│   │   └── mock.py              # 脚本化假模型，离线测循环 & 跑 eval
│   ├── agent/
│   │   ├── loop.py              # run_agent_turn()：手动循环+预算+容错
│   │   └── prompt.py            # system prompt
│   ├── tools/
│   │   ├── registry.py          # ToolRegistry：注册/校验/执行/归一化
│   │   ├── bird_id.py           # 鉴种 API 适配器（可替换）
│   │   ├── range_check.py       # ★季节/分布核验适配器（eBird）
│   │   ├── log_read.py          # read_log 工具（只读）
│   │   └── log_write.py         # append_log 工具（写入，过闸）
│   ├── memory/
│   │   └── log.py               # append-only JSONL 日志：append() / query()
│   ├── harness/
│   │   ├── permissions.py       # 风险分级 + 写入审批
│   │   ├── budget.py            # 步数/token 预算 + 停止原因
│   │   └── trace.py             # JSONL 轨迹写入器
│   └── cli.py                   # 入口：读笔记 → 跑 agent → 显示结果
├── evals/
│   ├── tasks.yaml               # 固定测试用例
│   └── run_evals.py             # 跑 agent、打分、出通过率
├── scripts/                     # 开发期临时冒烟测试脚本（如 run_s1.py），不属于最终交付结构
└── data/                        # gitignore：日志、轨迹
    ├── observations.jsonl
    └── traces/
```

---

## 4. 核心数据结构（`schemas.py`，**最先锁这一个文件**）

> 这些是整个系统的"血型"，**完全 provider 中立**。先定死它们，多 agent、记忆、eval 才能干净地插进来。用 pydantic。

**ToolCall** — 模型发出的一个工具请求

```
id: str            # 配对用，对应 tool_result（OpenAI 的 tool_call.id 映射到这里）
name: str          # 工具名
input: dict        # 模型填的参数（OpenAI 的 tool_call.function.arguments(JSON 字符串)解析后映射到这里）
```

**ToolResult** — 工具执行后的归一化返回（**所有工具都返回这个形状**）

```
ok: bool           # 成功 / 失败
output: str        # 给模型看的文本（结果或错误信息）
```

**ModelResponse** — `llm/client` 归一化后的模型响应（屏蔽 provider 差异；这是循环唯一认识的形状）

```
text: str | None              # 文字答案（最终答案或中间话）
tool_calls: list[ToolCall]    # 模型这一轮想调的工具（可能为空）
stop_reason: str              # ★内部归一化值: "tool_use" | "end_turn" | "max_tokens" | ...
                              #   DeepSeekClient 负责把"响应里有没有 tool_calls / OpenAI 的
                              #   finish_reason"映射成这些内部值（finish_reason 取值如 stop/length/tool_calls）
usage: dict | None            # 归一化用量 {input_tokens, output_tokens}
                              #   由 DeepSeekClient 从 OpenAI 的 usage(prompt_tokens/completion_tokens) 映射而来
```

**Observation** — 写进日志的一条观测记录（**这是 agent 的最终产物**）

```
id: str
timestamp: str                # ISO 时间
place: str | None
obs_date: str | None          # 观测日期
time_of_day: str | None       # 上午/黄昏...
species: str | None           # 鉴定出的种；不确定可为 None
count: int | None
behavior: str | None
raw_note: str                 # 原始乱笔记，永远保留
confidence: float | None      # 来自 bird_id 或模型自评
source: str                   # "user" | "bird_id" | "inferred" | "manual"
flags: list[str]              # 如 ["season_unusual", "low_confidence"]
```

**TraceEvent** — 每个循环步骤落一行（可观测性）

```
step: int
timestamp: str
kind: str          # "model_call" | "tool_call" | "tool_result" | "final" | "budget_stop"
summary: str       # 一句话人读
detail: dict       # tool 名、input 预览、output 预览、stop_reason、usage
```

---

## 5. 模块职责 + 对应 MiniCode 模式

| 模块                            | 职责                                                            | 对应 MiniCode                                                                                                                            |
| ------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/loop.py`                 | `model→tool→model` 回合循环；步数上限；工具报错计数；空响应重试 | `src/agent-loop.ts`                                                                                                                      |
| `tools/registry.py`             | 统一工具契约：find → 校验 → 执行 → `{ok,output}`                | `src/tool.ts`                                                                                                                            |
| `harness/permissions.py`        | 写入类工具执行前审批；记住"本回合一直允许"                      | `src/permissions.ts`                                                                                                                     |
| `memory/log.py`                 | append-only JSONL 观测日志                                      | `src/session.ts`                                                                                                                         |
| `harness/trace.py`              | 结构化轨迹                                                      | （MiniCode 散在 TUI；你独立成模块更清晰）                                                                                                |
| `harness/budget.py`             | 预算与停止条件                                                  | `agent-loop.ts` 里的 `maxSteps`                                                                                                          |
| `llm/deepseek_client.py` + `llm/mock.py` | 模型适配（实现为 **DeepSeekClient**，走 openai SDK）+ 离线 mock | MiniCode 对应 `src/anthropic-adapter.ts` + `src/mock-model.ts`（注：那是 MiniCode 用 Anthropic 的文件名；我们这边换成 DeepSeek，OpenAI 兼容，结构同构） |

---

## 6. 关键契约（vibe coding 必须遵守的接口）

> 这一节是给 AI 写代码时的"硬约束"。每次让它实现某模块，把对应契约贴过去。

**LLM 客户端**

```
class LLMClient:
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelResponse
```

- 实现：`DeepSeekClient`（真 API，`openai` SDK，OpenAI 兼容端点，模型 `deepseek-v4-flash`，**手动函数调用**：只声明 tools、自己执行、自己回 role=tool 消息，不用任何自动函数执行）、`MockClient`（脚本化，按预设依次返回 ModelResponse）。
- `DeepSeekClient` 的职责就是**双向翻译**：把内部 `messages` 译成 OpenAI chat messages（role: system/user/assistant/tool）、把工具定义译成 OpenAI `tools`（type=function）；再把 OpenAI 的 `message.tool_calls` 译回内部 `ModelResponse`（含 `tool_calls` 和归一化的 `stop_reason`）。
- `MockClient` 是关键：让你**不花一分钱、不连真模型**就能把整个循环测通，它返回的 `ModelResponse` 和 `DeepSeekClient` 一模一样，所以循环换 client 时毫无察觉。

**工具定义**（每个工具一个）

```
name: str
description: str          # 给模型看的菜单描述
input_schema: dict        # JSON Schema；DeepSeekClient 把它作为 OpenAI function 的 parameters 传给模型
schema: pydantic.Model    # 你这边的输入校验
risk: str                 # "read" | "write"
run(input, ctx) -> ToolResult
```

**工具注册表**

```
ToolRegistry.execute(name, input, ctx) -> ToolResult
# 内部顺序：find(name) → schema 校验 → 若 risk=="write" 过 permissions → run() → try/except 归一化
```

**Agent 回合**

```
run_agent_turn(
    messages, tools, llm, permissions, budget, trace, on_event=...
) -> (final_messages, final_text)
# 行为：循环调 llm.complete → 若 stop_reason=="tool_use" 则逐个 execute 工具、
#       把 tool_call + tool_result 追加进 messages、每步写 trace →
#       直到 end_turn 或 budget 耗尽 → 返回
# 注：这里的 "tool_use" 是内部归一化值，与 provider 无关；
#     loop 永远不直接碰 DeepSeek/OpenAI 的形状，那些都在 DeepSeekClient 里处理掉了。
```

> **签名自 S1 起锁定**：`run_agent_turn(messages, tools, llm, permissions, budget, trace, ...)` 这个签名从 S1 就固定下来。S1 即建**薄实现**满足它——`budget` 仅做 `max_steps` 止捞，`permissions` 仅 `read→allow`；完整的写入审批见 S5，token 预算与工具容错见 S6。**后续切片只填充 `permissions`/`budget` 的实现深度，不改这个签名。**

**权限闸**

```
permissions.check(tool_name, risk, input) -> "allow" | "deny"
# read 自动 allow；write 触发审批回调（CLI 里 y/n；eval/mock 里按策略自动）
```

**预算**

```
budget.tick() -> bool            # 还能继续吗
budget.stop_reason() -> str      # "max_steps" | "max_tokens" | None
budget.observe(usage) -> None    # S6: loop 每次 model_call 后调用，按归一化 usage 累加 token；tick() 据此可返回 "max_tokens"
```

> S6 注：token 经 `budget.observe(usage)` 喂入——loop 在每次 model_call 之后加一行 `budget.observe(resp.usage)`（`run_agent_turn` 签名不变）；`tick()` 在下一次调用**前**据累计 token 决定是否停，绝不切断进行中的响应（优雅收尾）。token 口径=Σ(input+output)，多轮重发上下文会重复计入，是有意的保守高估。

**日志（记忆）**

```
log.append(obs: Observation) -> None                       # 追加一行 JSONL
log.query(place=None, species=None, date_range=None) -> list[Observation]
```

---

## 7. 工具清单（v1）

| 工具         | risk      | 作用                         | 备注                                                                                               |
| ------------ | --------- | ---------------------------- | -------------------------------------------------------------------------------------------------- |
| `bird_id`    | read      | **本地图片路径** `image_path` → 候选鸟种 + 置信度（中文名） | **懂鸟(hholove)实现**（S4）：**异步两步**——先上传图片拿识别ID、再用ID轮询取结果；上传须**长超时**（海外 `WriteTimeout` 坑：`connect=10,read=60,write=60,pool=10`），取结果 `timeout=30`、轮询≤5次。鉴权头 `api_key`，所有请求 POST `/dongniao` 走 multipart。**返回是数组 `[code, payload]`**（非字典）：上传 `1000`→payload 是识别ID，取结果 `1000`→payload 是检测目标数组、`1001`→未算完重试、`1008/1009`→未认出。置信度 0~100；物种名 `中文名\|英文名\|拉丁名` 取首段。**异步复杂度全封装在 `run()` 内**，对外只回一个 ToolResult；入参是本地 `image_path`（**非 URL**）。 |
| `read_log`   | read      | 查**你自己的**历史观测（按地点/种/日期） | 用于"我去年在这儿见过啥""这地方我记录过哪些种"——只是个人历史/**弱先验**，不做权威的季节/分布核验（那归 `range_check`，见 §7 / 新 S3） |
| `range_check` | read | place + date → 该地当季合理出现的**物种清单**（数据源 eBird） | 季节/分布核验的**正主**；模型从清单里挑与外形描述匹配的种。与 `read_log` 区别：range_check 是**权威**物候/分布数据，read_log 只是**个人历史/弱先验**。**注：`date` 仅作季节提示——实际查询走 eBird `recent`（近 `back` 天、≤30 天、截至今天）作"当季"代理，吃不了任意历史日期；笔记记的是当天/近期时该代理成立。** |
| `append_log` | **write** | 写入一条 Observation         | **唯一需要过权限闸的工具**                                                                         |

> **注意**：把乱笔记整理成结构化字段，**不是一个工具**，而是模型自己的本职——它推理后直接把结果填进 `append_log` 的参数里。
> 另注：`bird_id` 是**鉴种服务的 API**，和运行时大模型（DeepSeek）是两套独立的 API，别混淆。
> `range_check` 三个小事的落地（S3 已实现）：① 地名→坐标：用"常去观测点预存坐标表"（`tools/locations.py`）；② eBird 名单可能过长：按近期 `back=N` 天取 + 展示截断；③ 中文鸟名：用 obs 端点的 **`sppLocale` 参数**（注意**不是** `locale`——obs 端点会忽略 `locale`），本实现取 `zh_SIM`（简体）。
> S6 注：工具失败（ok=False）输出统一走 `tools/failures.py` 的 `tool_failure(tool, reason, fallback)`——格式为"⚠ <tool> 暂不可用：<原因>"+回退建议，便于模型识别并按来源优先级回退。仅 `range_check`/`bird_id` 会发**工具级** ok=False；`read_log`/`append_log` 的失败在 registry 级（invalid input / permission denied / tool error）。

---

## 8. 数据流（完整一遍）

```
cli 读入笔记 → messages=[{user: 笔记}]
  → run_agent_turn:
      回合1: llm.complete(=DeepSeekClient) → stop_reason=tool_use, 请求 bird_id
             registry.execute(bird_id) [read,自动allow] → 候选鸟种
             追加 tool_call + tool_result;trace×2
      回合2:（无种名时）llm.complete → 请求 range_check(place,date) 取当地当季合理物种清单 → 模型在清单内匹配外形描述选种；read_log 可选作个人弱先验 → 同上
      回合3: llm.complete → 请求 append_log(Observation)
             registry.execute(append_log) [write→permissions.check→y/n]
             → log.append 写入 observations.jsonl;trace
      回合4: llm.complete → stop_reason=end_turn, 给最终总结
  → 返回总结给用户;trace(final)
```

**物种来源优先级（裁决规则）** —— species 该信谁的：用户指定 > 图片鉴定 > 描述推断（经 `range_check` 核验）：

1. 笔记里**直接指定**了物种名 → `species` 填用户给的名字，`confidence=None`，`source="user"`；有没有图片/描述都如此。
2. 在第1条基础上，若同时有图片或外形描述，且自动鉴定（图片或描述推断）结果与用户指定**不一致** → `species` 仍用用户指定，但 `flags` 加入 `"autoid_conflict"`（与自动鉴定有分歧）。
3. 没指定种名但**有图片** → 以 `bird_id` 结果为准，`source="bird_id"`。
4. 既没种名也没图片 → 走"描述 → 模型推断 → `range_check` 季节核验"，`source="inferred"`；拿不准就 `species=None` 并加 `"low_confidence"`。**注：`range_check` 尚未实现，接入前第4条暂降级为"仅靠模型鸟类学知识推断"。**

---

## 9. Eval 设计

**`tasks.yaml`** —— 每条一个测试用例

```
- id: t01
  input_note: "上午卡西临海公园，大概20只黑头红腿小型涉禽"
  photo_url: null
  expected:
    place: "卡西临海公园"
    count: 20
    must_call_tools: ["append_log"]      # 期望它最终写了日志
    species_in: ["黑翅长脚鹬", null]       # 允许的种（含"拿不准"）
```

**`run_evals.py`** —— 对每条任务跑 agent（用 `MockClient` 或低温的真 DeepSeek），比对：结构化字段是否匹配、是否调了该调的工具、是否乱调写入。输出**通过率 + 逐条 pass/fail**。

> 这个通过率曲线 + 你能解释"没过的为什么难"，是简历里最硬的一块。

---

## 10. 推荐搭建顺序（每个切片都能跑）

| 切片 | 内容                                                                         | 验收                                       |
| ---- | ---------------------------------------------------------------------------- | ------------------------------------------ |
| S1   | `schemas` + `MockClient` + `loop` + `registry` + 假 `read_log` + `trace` + 薄版 `budget`(仅 max_steps) + 薄版 `permissions`(read→allow) + `scripts/run_s1.py`；S1 锁定 loop 签名，权限/预算完整逻辑在 S5/S6 填充 | 离线、零成本，循环能跑通，trace 打印出每步 |
| S2   | `DeepSeekClient`(openai/OpenAI 兼容) 接真模型，能产出结构化 `Observation`     | 真模型跑通一条笔记                         |
| S3   | `range_check` 适配器（eBird，纯文本+HTTP）：place+date → 当地当季合理物种清单；补"无图仅描述"识别短板 | 给定 place+date 能取回当季合理物种清单，模型能在清单内选种 |
| S4   | `bird_id` 真适配器（先验证鉴种 API）                                         | 带照片能拿到候选种                         |
| S5   | `memory/log` 的 append/query + `append_log` 写入 + 权限闸                    | 能写日志、写前要确认、能查回来             |
| S6   | `budget` 步数上限 + 工具报错容错                                             | 死循环/报错不会失控                        |
| S7   | `evals`：10–15 条用例 + 通过率                                               | 一条命令出通过率                           |
| S8   | `cli` 打磨 + `README` + `DECISIONS.md`                                       | 别人能 clone 跑起来                        |

> S1 用 MockClient 把循环逻辑和真模型解耦，是整条路最省钱、最好 debug 的起点。**先把脑子（循环）调通，再接嘴（DeepSeek）和手（鉴种 API）。**

---

## 11. 可选进阶（面试谈资，做完 v1 再说，别提前背上）

- **核验子 agent（多 agent）**：一个专职 agent 拿 `bird_id` 结果 + `range_check` 的结果（分布数据）+ `read_log` 的个人历史，二次判断"这个种在这个时间地点合不合理"，给 `flags`。这是把单 agent 升级成多 agent 协同最自然的一步。
- **季节/分布核验**：已升为正式切片（新 S3 `range_check`，数据源 eBird），见 §7 / §10——不再属于"可选进阶"。
- **本地模型**：给 `LLMClient` 再加一个走 OpenAI 兼容端点的实现，接 llama.cpp/vllm，`--local` 开关——因为接口是 provider 中立的，这一步和接 DeepSeek 一样只动 `llm/` 一个文件。**别一开始碰这个**。
- **大工具结果移出 prompt** / **SQLite 替代 JSONL**：数据量大了再说。

---

## 12. 给 vibe coding 的三条铁律

1. 每个切片开工前，把本文档 + 该切片要碰的契约发给 AI，**不要让它自由发挥结构**。
2. 一次只让它实现一个模块，你读懂 diff 再进下一个；每个能跑的切片 `git commit` 一次。
3. 边做边往 `DECISIONS.md` 记取舍（为什么 JSONL 不用数据库？为什么写入过闸？为什么 DeepSeek 手动函数调用、不用自动执行？）——这是你"思考"的显性化。
