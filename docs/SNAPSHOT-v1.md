# Vibirding v1 现状快照（给外部顾问）

> **性质**：这份文档描述**代码里实际是什么**，不是架构文档的理想设计。
> 凡文档与代码不一致处，一律在 §10 单独列出。
> **快照时间**：2026-08-28｜**快照对象**：`main` @ `333efef`（工作区干净）
> **核实方式**：所有代码片段直接摘自仓库文件；所有命令输出为本次实测；无法实测的项明确标注「未核实」。

---

## 1. 项目现状总览

### 切片进度

S1–S8 全部完成，v1 功能面收尾。S9（批量笔记）仅在文档中登记，**代码零实现**。

### git 状态（实测）

```
$ git log --oneline -5
333efef 123
1451830 feat: s8 v1 wrap-up — cli entry + README + DECISIONS
7c4b68f feat: s7 evals — fixed cases + pass rate (two lanes)
8d90da0 docs: rename photo_url -> image_path, refresh STATUS HEAD
11b9fe0 docs: status

$ git tag
（空）

$ git status --short
（空）

$ git branch --show-current
main
```

两点要注意：

1. **没有任何 tag** —— `v1.0` **未打**。`.git/refs/tags/` 是空目录。
2. **HEAD 是一个提交信息为 `123` 的提交**。内容已核实：仅 README 的 markdown 表格对齐重排 + 一句措辞修改（22 增 22 删，纯 README，无代码变更）。

### 一句话：能做什么 / 不能做什么

**能做**：把**一句**自然语言观鸟笔记（可选附**一张本地图片**）整理成**一条**结构化 `Observation`，过程中按需调用三个只读工具（个人历史 / eBird 分布 / 懂鸟视觉鉴种），经**写入权限闸**（终端 y/n/a）追加到一个 append-only JSONL 文件；之后能用自然语言查回历史。每步落一行 JSONL trace。

**不能做**：

- **一次多条记录**（一篇笔记含多次观测）—— 无任何支持，`append_log` 一次一条，模型也没被教怎么拆。
- **图文配对** —— 一次只能带一张图，且图片是通过在 user 消息里拼一行文本 `（附图，本地路径：…）` 告知模型的，不是结构化字段。
- **任何数据库** —— 只有一个 JSONL 文件，`query()` 是全文件顺序扫描。
- **任何 Web / HTTP 服务端** —— 只有一个终端 CLI，无 server、无 API、无前端。
- **并发写** —— `open(path, "a")` 无锁、无事务。
- **修改 / 删除已写记录** —— 只有 `append` 和 `query`，没有 update/delete。

---

## 2. 目录与文件清单

### 实际目录树（实测 `find`，已排除 `.git`/`__pycache__`）

```
Vibirding/
├── .env.example
├── .gitignore
├── CLAUDE.md
├── DECISIONS.md
├── README.md
├── requirements.txt
├── docs/
│   ├── STATUS.md
│   └── architecture.md
├── evals/
│   ├── REPORT.md
│   ├── answers.yaml
│   ├── run_evals.py
│   └── tasks.yaml
├── scripts/
│   ├── check_s1.py  check_s3.py  check_s4.py  check_s5.py  check_s6.py
│   ├── run_deepseek.py
│   └── run_s1.py  run_s2.py  run_s3.py  run_s4.py  run_s5.py  run_s6.py
└── vibirding/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── config.py
    ├── schemas.py
    ├── agent/     __init__.py  loop.py  prompt.py
    ├── harness/   __init__.py  budget.py  permissions.py  trace.py
    ├── llm/       __init__.py  client.py  deepseek_client.py  mock.py
    ├── memory/    __init__.py  log.py
    └── tools/     __init__.py  bird_id.py  failures.py  locations.py
                   log_read.py  log_write.py  range_check.py  registry.py
```

**注意 `data/` 目录当前不存在**（gitignored，且 S8 提交时清理过演示数据）。首次运行时由 `Log.append` / `TraceWriter.__init__` 自动创建。

### 正式代码（`vibirding/` 包内，全部是交付面）

| 文件 | 一句话职责 |
| --- | --- |
| `__main__.py` | 让 `python -m vibirding` 可用，只转发 `cli.main()` |
| `cli.py` | **唯一交付级入口**：注册四工具 → 组装 system 消息 → 跑一个回合 → 展示结果 |
| `config.py` | 路径常量、DeepSeek/eBird/懂鸟的端点与参数常量、三个 `load_*_api_key()` |
| `schemas.py` | 五个 pydantic 数据结构（见 §3），全系统的「血型」 |
| `agent/loop.py` | `run_agent_turn()`：model→tool→model 回合循环 |
| `agent/prompt.py` | `SYSTEM_PROMPT` 静态常量 + `today_hint()` 运行时日期锚点 |
| `harness/budget.py` | `Budget`：步数 + token 双上限、停止原因 |
| `harness/permissions.py` | `Permissions`：read→allow / write→可注入审批回调 |
| `harness/trace.py` | `TraceWriter`：每步一行，打印 + 追加 JSONL |
| `llm/deepseek_client.py` | **运行时客户端**：openai SDK 打 DeepSeek 兼容端点，双向翻译 |
| `llm/client.py` | `GeminiClient`（google-genai），备用 provider，**当前无任何交付路径引用** |
| `llm/mock.py` | `MockClient`：按预设剧本依次返回 `ModelResponse`，离线用 |
| `memory/log.py` | `Log`：append-only JSONL 的 `append()` / `query()` |
| `tools/registry.py` | `ToolManager` + `Tool` 协议 + `ToolContext`，统一执行管线 |
| `tools/log_read.py` | `read_log` 工具（read） |
| `tools/range_check.py` | `range_check` 工具（read，eBird HTTP） |
| `tools/bird_id.py` | `bird_id` 工具（read，懂鸟异步两步 + 轮询） |
| `tools/log_write.py` | `append_log` 工具（**write**，唯一过闸） |
| `tools/locations.py` | 地名→坐标预存表（8 个点）+ `resolve_place()` |
| `tools/failures.py` | `tool_failure()`：ok=False 的统一文案格式化 |

### 开发期脚手架（`scripts/`，**非交付入口**）

| 文件 | 性质 | 说明 |
| --- | --- | --- |
| `check_s1.py` `check_s3.py` `check_s4.py` `check_s5.py` `check_s6.py` | **离线自检** | 各切片的确定性断言套件，零网络零 key。合计声称 132 条（本次未逐条重跑，见 §9） |
| `run_s1.py` | 离线冒烟 | MockClient 跑通循环 |
| `run_s2.py` | 真模型冒烟 | **Gemini** 入口，备用 provider 参考，STATUS 标注「最终可能删」 |
| `run_s3.py` `run_s4.py` `run_s5.py` `run_s6.py` `run_deepseek.py` | 真模型冒烟 | 各切片的手动端到端脚本，需要真 key |

**`scripts/run_s4.py` 有硬编码本机路径**，见 §11。

---

## 3. 数据结构

### `vibirding/schemas.py` 全文（真实代码）

```python
"""Core data structures — the "blood type" of the whole system.

These models are completely provider-neutral: the loop, tools, memory and eval
layers only ever speak in terms of the types defined here, never in terms of
the runtime provider's native shapes (DeepSeek/OpenAI). Per docs/architecture.md section 4, this file is locked
first, before anything else is built.

All models use pydantic for validation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """One tool request emitted by the model.

    DeepSeekClient maps OpenAI's ``tool_call.id`` -> ``id`` and the JSON-string
    ``tool_call.function.arguments`` -> ``input``. In S1 the MockClient fills
    these directly.
    """

    id: str  # pairs this call with its matching ToolResult
    name: str  # tool name to invoke
    input: dict = Field(default_factory=dict)  # arguments the model filled in


class ToolResult(BaseModel):
    """Normalized return of a tool execution. EVERY tool returns this shape."""

    ok: bool  # success / failure
    output: str  # text shown back to the model (result or error message)


class ModelResponse(BaseModel):
    """The model response after llm/client has normalized it.

    This is the ONLY response shape the loop understands; it hides all provider
    differences. ``stop_reason`` holds an internal normalized value
    ("tool_use" | "end_turn" | "max_tokens" | ...) — the client is responsible
    for mapping the provider's finish_reason / presence-of-tool_calls into these
    values (DeepSeekClient for the OpenAI-compatible API).
    """

    text: str | None = None  # textual answer (final answer or interim message)
    tool_calls: list[ToolCall] = Field(default_factory=list)  # tools wanted this turn
    stop_reason: str  # normalized: "tool_use" | "end_turn" | "max_tokens" | ...
    usage: dict | None = None  # normalized usage {input_tokens, output_tokens}


class Observation(BaseModel):
    """One observation record written to the log — the agent's final product.

    Locked now because it is the system's blood type, but S1 does not yet write
    it (there is no append_log until S4).
    """

    id: str
    timestamp: str  # ISO time
    place: str | None = None
    obs_date: str | None = None  # date of the observation
    time_of_day: str | None = None  # morning / dusk ...
    species: str | None = None  # identified species; may be None if unsure
    count: int | None = None
    behavior: str | None = None
    raw_note: str  # the original messy note, always kept
    confidence: float | None = None  # from bird_id or the model's self-estimate
    source: str  # "user" | "bird_id" | "inferred" | "manual"
    flags: list[str] = Field(default_factory=list)  # e.g. ["season_unusual"]


class TraceEvent(BaseModel):
    """One line logged per loop step (observability)."""

    step: int
    timestamp: str
    kind: str  # "model_call" | "tool_call" | "tool_result" | "final" | "budget_stop"
    summary: str  # one human-readable sentence
    detail: dict = Field(default_factory=dict)  # tool name, input/output preview, etc.
```

> **注**：`Observation` 的 docstring 说「there is no append_log until S4」是**过时注释**，`append_log` 实际在 S5 才落地。见 §10。

### `Observation.species` 的真实情况

**类型**：`str | None`，默认 `None`。

**约束**：**零约束**。没有 enum、没有正则、没有长度限制、没有物种名录（taxonomy）校验、没有任何名称规范化（不做去空格以外的处理，实际连去空格都没有）。pydantic 只校验「是字符串或 None」。

搜索全仓，**不存在任何物种名录、别名表或规范化函数**。唯一与「名称规范」沾边的是 `tools/locations.py` 的**地名**表（8 个观测点，exact-match），与物种无关。

**实际取值来源**有三条路径，全部由模型自由填写：

1. 用户在笔记里写的原字符串（`source="user"`）
2. 懂鸟返回的 `中文名|英文名|拉丁名` 取 `split("|")[0]` 的首段（`source="bird_id"`）
3. 模型从 eBird 清单或自身知识推断出的中文名（`source="inferred"`）

**结论：`species` 是一个自由中文字符串**，中文俗名是**惯例**而非**约束**。v2 若要建物种维表 / 外键，这里是零基础起步。

### 实际落盘的 species 值长什么样

**真实日志当前为空** —— `data/` 目录不存在，`data/observations.jsonl` 不存在，**真实记录数 = 0 条**（见 §7）。

下面这行是**用真实代码路径（`AppendLogTool.run` → `Log.append`）现场跑出来的真实落盘行**（日志指向临时文件，未污染仓库）：

```json
{"id": "93952e87", "timestamp": "2026-08-28T06:26:53.788977+00:00", "place": "葛西临海公园", "obs_date": "2026-08-28", "time_of_day": "傍晚", "species": "家燕", "count": null, "behavior": "在低空来回飞", "raw_note": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞", "confidence": null, "source": "user", "flags": []}
```

注意 `count: null` —— 「十几只」这类模糊量词模型不折算，这是已知边界（eval t02 FAIL 的成因）。

### `source` 的实际取值集合

三处定义**互相不完全一致**，且**没有任何一处做校验**：

| 位置 | 声明的取值 |
| --- | --- |
| `schemas.py` 注释 | `"user" \| "bird_id" \| "inferred" \| "manual"` |
| `log_write.py` 的 `input_schema` description | `user \| bird_id \| inferred \| manual` |
| `SYSTEM_PROMPT`（**模型实际读到的**） | `取值 "user" \| "bird_id" \| "inferred"` |

pydantic 侧 `AppendLogInput.source: str` —— **纯字符串，必填，无 enum**。

**实际结论**：`"manual"` 从未被任何代码路径产生，模型也没被告知它存在；实际只会出现三个值，而且**任何字符串都能写进去**。

### `flags` 的实际取值集合

`list[str]`，默认 `[]`，**无 enum、无校验**。`SYSTEM_PROMPT` 教给模型的四个 token：

- `place_corrected` —— 纠正了地点拼写
- `autoid_conflict` —— 用户指定种名与自动鉴定分歧
- `low_confidence` —— 对种没把握
- `season_unusual` —— 季节/分布异常

eval 的 `flags_contains_any` 断言**刻意用子串匹配**（架构 §9 原文：「容忍模型用中文写 flag，如 "季节异常" 命中 "季节"」），这本身就承认了**模型实际会写出规范外的中文 flag**。

---

## 4. Agent 循环与契约

### `run_agent_turn` 全文（真实代码，`vibirding/agent/loop.py`）

```python
def run_agent_turn(
    messages: list[dict],
    tools,  # ToolManager — see module docstring
    llm,  # LLMClient (MockClient offline; DeepSeekClient/GeminiClient for real models)
    permissions,
    budget,
    trace,
    on_event: Callable[[TraceEvent], None] | None = None,
) -> tuple[list[dict], str | None]:
    # Build the execution context once; the write gate reads permissions from it.
    ctx = ToolContext(permissions=permissions)
    step = 0  # trace line counter (distinct from budget's loop-step counter)
    final_text: str | None = None

    def emit(kind: str, summary: str, detail: dict) -> None:
        """Write one trace line to the primary sink and the optional observer."""
        nonlocal step
        step += 1
        event = TraceEvent(
            step=step,
            timestamp=datetime.now().isoformat(),
            kind=kind,
            summary=summary,
            detail=detail,
        )
        trace.emit(event)  # primary sink: prints + appends JSONL
        if on_event is not None:
            on_event(event)  # optional extra observer

    # Each budget.tick() consumes one loop step; returns False once max_steps hit.
    while budget.tick():
        resp = llm.complete(messages, tools=tools.specs())
        emit(
            "model_call",
            f"模型响应 stop_reason={resp.stop_reason}，请求 {len(resp.tool_calls)} 个工具",
            {
                "stop_reason": resp.stop_reason,
                "n_tool_calls": len(resp.tool_calls),
                "usage": resp.usage,
                "text_preview": _preview(resp.text),
            },
        )
        # S6: feed this call's token usage to the budget. Signature/control flow
        # are unchanged; tick() (checked before the next call) will stop the loop
        # if the token cap is now exceeded — never mid-response.
        budget.observe(resp.usage)

        if resp.stop_reason == "tool_use":
            # 1. record the assistant's tool-call turn in the conversation
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.text,
                    "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
                }
            )
            # 2. run each requested tool, appending its result + two trace lines
            for call in resp.tool_calls:
                emit(
                    "tool_call",
                    f"调用工具 {call.name}",
                    {"name": call.name, "input": call.input},
                )
                result = tools.execute(call.name, call.input, ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result.output,
                    }
                )
                emit(
                    "tool_result",
                    f"工具 {call.name} 返回 ok={result.ok}",
                    {
                        "name": call.name,
                        "ok": result.ok,
                        "output_preview": _preview(result.output),
                    },
                )
            # 3. loop again so the model sees the tool results
            continue

        # Any non-tool_use stop_reason ends the turn (normally "end_turn").
        final_text = resp.text
        messages.append({"role": "assistant", "content": resp.text})
        emit(
            "final",
            f"最终答复：{_preview(resp.text)}",
            {"stop_reason": resp.stop_reason, "text_preview": _preview(resp.text)},
        )
        return messages, final_text

    # Fell out of the while: budget ran out before the model ended its turn.
    emit(
        "budget_stop",
        f"预算耗尽停止：{budget.stop_reason()}",
        {"stop_reason": budget.stop_reason()},
    )
    return messages, final_text
```

`_preview` 是同文件的私有辅助，把长文本截断到 120 字符加省略号。

**对 v2 重要的几点行为事实**：

- `messages` 是**原地修改**（`messages.append`），调用方传进去的 list 会被改。
- **单个 tool_call 失败不中断循环** —— `execute` 永远返回 `ToolResult`，失败文本原样回填给模型。
- **模型一轮可以请求多个工具**，循环会顺序全跑完再回到模型。
- **没有任何重试** —— 空响应、模型胡说、工具连续失败都不重试，只靠 `max_steps` 兜底。
- 结束条件只有两个：`stop_reason != "tool_use"`（正常收尾）或 `budget.tick()` 返回 False（预算停）。

### `messages` 的真实结构（本次实测导出）

这是一次真实跑完后 `messages[1:]` 的实际内容：

```json
{"role": "user", "content": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "name": "range_check", "input": {"place": "葛西临海公园", "date": "2026-08-28"}}]}
{"role": "tool", "tool_call_id": "call_1", "name": "range_check", "content": "⚠ range_check 暂不可用：EBIRD_API_KEY 未设置：请在项目根 .env 写入 EBIRD_API_KEY=<your-key>。\n回退建议：靠你自身的鸟类学知识判断该种是否合理，并酌情给 species 标 low_confidence。"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_2", "name": "append_log", "input": {"place": "葛西临海公园", "obs_date": "2026-08-28", "time_of_day": "傍晚", "species": "家燕", "behavior": "在低空来回飞", "raw_note": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞", "source": "user", "flags": []}}]}
{"role": "tool", "tool_call_id": "call_2", "name": "append_log", "content": "已写入日志：葛西临海公园 2026-08-28 家燕 ×? （source=user, id=93952e87）"}
{"role": "assistant", "content": "已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。"}
```

四种角色：

| role | 字段 | 说明 |
| --- | --- | --- |
| `system` | `content` | 由入口层拼接（见 §8） |
| `user` | `content` | 笔记原文；**有图时在末尾拼一行文本** `\n（附图，本地路径：<path>）` |
| `assistant` | `content` + 可选 `tool_calls` | `tool_calls` 是**内部形状** `{id, name, input}`，不是 OpenAI 形状 |
| `tool` | `tool_call_id` + `name` + `content` | `content` 就是 `ToolResult.output` 字符串 |

**内部形状 → OpenAI 形状的翻译全部封在 `DeepSeekClient._to_messages()` 里**：`input` dict 会被 `json.dumps` 成 OpenAI 要的 `function.arguments` 字符串；内部多出来的 `name` 字段在 tool 消息里被丢弃。

### `ToolManager.execute` 全文（`vibirding/tools/registry.py`）

```python
    def execute(self, name: str, input: dict, ctx: ToolContext) -> ToolResult:
        """Run one tool, normalizing every outcome into a ToolResult.

        Order is fixed by the contract: find -> validate -> (write?) gate -> run.
        Any failure becomes ok=False so the loop can feed it back to the model.
        """
        # 1. find
        tool = self.find(name)
        if tool is None:
            return ToolResult(ok=False, output=f"unknown tool: {name}")

        # 2. validate the model-supplied input against the tool's pydantic schema
        try:
            tool.schema.model_validate(input)
        except ValidationError as e:
            return ToolResult(ok=False, output=f"invalid input for {name}: {e}")

        # 3. write gate — read tools skip this entirely
        if tool.risk == "write":
            decision = (
                ctx.permissions.check(name, tool.risk, input)
                if ctx.permissions is not None
                else "deny"  # fail closed if no permissions wired in
            )
            if decision != "allow":
                return ToolResult(ok=False, output=f"permission denied: {name}")

        # 4. run, normalizing any exception into a ToolResult
        try:
            return tool.run(input, ctx)
        except Exception as e:  # normalize ALL tool errors so the loop stays alive
            return ToolResult(ok=False, output=f"tool error in {name}: {e}")
```

`specs()` 产出的是**内部菜单形状**，不是 OpenAI 形状：

```python
    def specs(self) -> list[dict]:
        """The menu handed to the model: name / description / input_schema only."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]
```

**注意**：`schema.model_validate(input)` 只**校验**，**校验后的对象被丢弃**；传给 `run()` 的仍是原始 `input` dict。所以 pydantic 的类型强制转换（coercion）结果不会生效，`run()` 内部一律用 `input.get(...)` 取原值。

### `ToolContext`（真实代码）

```python
@dataclass
class ToolContext:
    """Execution context passed to a tool's run() and used by the write gate.

    Holds only what S1 needs (permissions for the gate). Later slices grow it
    (e.g. the append-only log handle in S4) without changing the registry API.
    """

    permissions: Permissions | None = None
```

**实际至今只有 `permissions` 一个字段**。docstring 预告的「log handle 进 ctx」**没有发生**——`Log` 是通过**工具构造函数注入**的（`ReadLogTool(log)` / `AppendLogTool(log)`）。见 §10。

### `Budget` 全文（`vibirding/harness/budget.py`）

```python
class Budget:
    """Counts loop steps AND accumulated tokens; stops the loop when either caps."""

    def __init__(self, max_steps: int, max_tokens: int | None = None) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens  # None => no token cap (back-compatible default)
        self.steps_used = 0
        self.tokens_used = 0
        self._stop_reason: str | None = None

    def observe(self, usage: dict | None) -> None:
        if not usage:
            return
        self.tokens_used += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)

    def tick(self) -> bool:
        if self.max_tokens is not None and self.tokens_used >= self.max_tokens:
            self._stop_reason = "max_tokens"
            return False
        if self.steps_used >= self.max_steps:
            self._stop_reason = "max_steps"
            return False
        self.steps_used += 1
        return True

    def stop_reason(self) -> str | None:
        return self._stop_reason
```

**实现深度：完整**（步数 + token 双上限都实现了）。

**但是——token 上限在交付路径里是关闭的**。实测所有 `Budget(...)` 调用点：

```
vibirding/cli.py:176        Budget(max_steps=args.max_steps)          ← 交付入口，无 max_tokens
evals/run_evals.py:277      Budget(max_steps=len(script) + 2)         ← 离线档，无
evals/run_evals.py:281      Budget(max_steps=args.max_steps)          ← 在线档，无
scripts/run_s6.py:95        Budget(max_steps=..., max_tokens=...)     ← 唯一会设的，是开发脚手架
scripts/check_s6.py         Budget(max_steps=5, max_tokens=100) 等     ← 自检
```

也就是说：**`max_tokens` 默认 `None`，`cli.py` 从不传它，所以正式使用时 token 预算是惰性的，只有步数上限（默认 6）在起作用**。README 宣称的「步数 + token 双上限」在交付路径上只兑现了一半。见 §10。

另注：token 口径是 Σ(input + output) 逐轮累加，**多轮重发的上下文会被重复计入**（代码注释里明确说这是有意的保守高估）。

### `Permissions` 全文（`vibirding/harness/permissions.py`）

```python
Approver = Callable[[str, str, dict], str]


class Permissions:
    """Decides whether a tool call may execute, based on its risk level."""

    def __init__(self, approver: Approver | None = None) -> None:
        # No approver -> writes fail closed (deny). Scripts inject a y/n/a prompt;
        # evals/self-checks inject an automatic allow/deny/always policy.
        self._approver = approver
        # Set once the user answers "always": skip prompting for the rest of the turn.
        self._allow_all_writes = False

    def check(self, tool_name: str, risk: str, input: dict) -> str:
        # Read-only tools never mutate anything -> always allowed.
        if risk == "read":
            return "allow"

        # From here on it's a write (or any non-read risk -> treated as write).
        # "remember allow for the rest of this turn" short-circuits the prompt.
        if self._allow_all_writes:
            return "allow"

        # No approval mechanism -> fail closed (matches the S1 default).
        if self._approver is None:
            return "deny"

        # Ask the injected approver and map its richer answer to allow/deny.
        decision = self._approver(tool_name, risk, input)
        if decision == "always":
            self._allow_all_writes = True  # don't ask again this turn
            return "allow"
        if decision == "allow":
            return "allow"
        return "deny"  # "deny" or anything unexpected -> fail closed
```

**实现深度：完整**。三个关键性质：

1. **闸在执行路径内**（`ToolManager.execute` 第 3 步），不是事后审计。
2. **审批回调可注入**，`input()` 只存在于入口层（`cli.py`），从不进 `permissions.check`。
3. **fail-closed**：没接 approver 时写入一律 deny。
4. `_allow_all_writes` 的作用域是 **`Permissions` 实例的生命周期**，即「本回合」——`cli.py` 每次运行新建一个实例，所以 `a` 不跨进程持久。

### `TraceWriter` 全文（`vibirding/harness/trace.py`）

```python
class TraceWriter:
    """Writes TraceEvents to console and to a per-run JSONL file."""

    def __init__(
        self,
        run_id: str | None = None,
        traces_dir: Path = TRACES_DIR,
        to_console: bool = True,
    ) -> None:
        self.run_id = run_id or _new_run_id()
        self.to_console = to_console
        # Ensure the output dir exists here (config only declares paths).
        traces_dir.mkdir(parents=True, exist_ok=True)
        self.path = traces_dir / f"{self.run_id}.jsonl"

    def emit(self, event: TraceEvent) -> None:
        """Record one step: print a human line, then append one JSON line."""
        if self.to_console:
            print(f"step {event.step:>2} | {event.kind:<12} | {event.summary}")
        # ensure_ascii=False keeps Chinese readable inside the JSONL file.
        line = json.dumps(event.model_dump(), ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
```

**实现深度：完整但极简**。一个 run 一个文件，`traces_dir` 可注入（eval 用临时目录）。**没有轮转、没有清理、没有大小上限**——`data/traces/` 会无限增长。

---

## 5. 工具现状

四个工具全部注册在 `cli.py`：

```python
def build_registry(log: Log) -> ToolManager:
    """Register all four tools against one shared Log handle (the real log)."""
    registry = ToolManager()
    registry.register(ReadLogTool(log))
    registry.register(RangeCheckTool())
    registry.register(BirdIdTool())
    registry.register(AppendLogTool(log))
    return registry
```

注意 `read_log` 与 `append_log` **共用同一个 `Log` 实例**，所以刚写的记录同回合能读回。

---

### 5.1 `read_log`（risk = `read`）

**给模型看的 description 原文**：

```
查你自己的历史观测记录，可按地点(place)、鸟种(species)、日期范围(date_range)过滤。这是个人记录、弱先验（“我以前在这儿/这季节记录过什么”），不是权威的季节/分布核验。
```

**input_schema（真实）**：

```python
    input_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "地点名"},
            "species": {"type": "string", "description": "鸟种名"},
            "date_range": {"type": "string", "description": "日期范围，如 2025-01..2025-12"},
        },
        "required": [],
    }
```

**pydantic schema（真实）**：

```python
class ReadLogInput(BaseModel):
    place: str | None = None
    species: str | None = None
    date_range: str | None = None  # free-form, e.g. "2025-01..2025-12"
```

**`run()` 真实行为**：

```python
    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        rows = self._log.query(
            place=input.get("place"),
            species=input.get("species"),
            date_range=input.get("date_range"),
        )
        if not rows:
            return ToolResult(ok=True, output="（无匹配的历史观测记录）")
        lines = [_format_row(o) for o in rows]
        return ToolResult(ok=True, output="历史观测：\n" + "\n".join(lines))
```

每行格式：`{obs_date} {place} {species} ×{count}`，None 一律渲染成 `?`。

**失败分支**：**没有工具级 ok=False**。空结果是 `ok=True`。唯一的失败路径在 registry 层（schema 校验失败 / `run()` 抛异常被 `except Exception` 兜住）。

**⚠️ 对 v2 重要的两个隐性行为**（代码里有、文档里没有）：

1. **无结果条数上限、无分页** —— `query()` 返回多少就全部渲染进 prompt。日志涨到几千条时，一次 `read_log()` 无过滤调用会把整个日志塞进上下文。
2. `place` / `species` 是**子串包含匹配**，不是精确匹配（见 §7 的 `_matches`）。

---

### 5.2 `range_check`（risk = `read`，外部 API：eBird）

**给模型看的 description 原文**：

```
查某地近期 eBird 实际记录到的鸟种清单（中文名），作为该地“当季合理出现的物种”的权威分布依据：你应从清单里挑选与笔记外形描述匹配的种。与 read_log 不同——read_log 只是你的个人历史/弱先验，本工具是权威分布数据。参数 date 仅作季节提示（实际取近 N 天到今天的记录当作“当季”代理）。
```

**input_schema / pydantic schema（真实）**：

```python
    input_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "观测地点（用标准官方名，如 葛西临海公园）"},
            "date": {"type": "string", "description": "观测日期 ISO，如 2026-06-24，用于推断季节"},
        },
        "required": ["place"],
    }

class RangeCheckInput(BaseModel):
    place: str
    date: str | None = None
```

**外部 API 真实调用参数**：

```python
def _fetch_recent(lat: float, lng: float, key: str) -> list[dict]:
    url = f"{config.EBIRD_BASE_URL}/data/obs/geo/recent"
    params = {
        "lat": round(lat, 2),
        "lng": round(lng, 2),
        "dist": config.EBIRD_DIST_KM,      # km radius, <= 50
        "back": config.EBIRD_BACK_DAYS,    # look-back days, 1..30
        # eBird obs endpoints use `sppLocale` (NOT `locale`) for common-name lang.
        "sppLocale": config.EBIRD_SPP_LOCALE,  # zh_SIM -> Simplified Chinese names
        "maxResults": _MAX_RESULTS,
    }
    headers = {"x-ebirdapitoken": key}
    resp = httpx.get(url, params=params, headers=headers, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()
```

对应 `config.py` 常量：

```python
EBIRD_BASE_URL = "https://api.ebird.org/v2"
EBIRD_DIST_KM = 25          # 搜索半径 km（eBird 上限 50）
EBIRD_BACK_DAYS = 14        # 回看天数（eBird 允许 1..30）
EBIRD_SPP_LOCALE = "zh_SIM" # 注意是 sppLocale 不是 locale
```

模块级常量：`_HTTP_TIMEOUT = 10.0` 秒｜`_MAX_RESULTS = 200`（请求上限）｜`_MAX_SPECIES_SHOWN = 80`（展示截断）。

**`date` 参数实际不参与查询** —— 它只被拼进输出文本里作展示（`date={when}`）。真实查询永远是「近 `back` 天到今天」。**吃不了任意历史日期**，这是设计取舍，代码注释里写明了。

**各分支的真实归一化文案**：

| 情况 | ok | 输出 |
| --- | --- | --- |
| 地点不在坐标表 | **True** | `未知地点 '<place>'：不在预存坐标表中，无法做 eBird 分布核验；请基于你的鸟类学知识判断该种在此地此季是否合理。` |
| 近 N 天无记录（空清单） | **True** | `<place> 近 14 天 eBird 无记录（date=<date>）；无法据此核验，请用你的鸟类学知识判断。` |
| 成功 | True | `<place> 近 14 天 eBird 实际记录的鸟种（共 N 种，作“当季合理出现”的代理；date=…）：\n绿头鸭（Anas platyrhynchos）、…` 超过 80 种时追加 `…（另有 M 种未列出）` |
| 缺 `EBIRD_API_KEY` | False | `⚠ range_check 暂不可用：EBIRD_API_KEY 未设置：…` |
| HTTP 超时 | False | `⚠ range_check 暂不可用：eBird 请求超时，未能取回物种清单。` |
| 401 / 403 | False | `⚠ range_check 暂不可用：eBird API key 无效或无权限（401/403）。` |
| 其他非 2xx | False | `⚠ range_check 暂不可用：eBird 返回异常状态码 <status>。` |
| 网络错误 | False | `⚠ range_check 暂不可用：网络连接 eBird 失败。` |
| 200 但坏 JSON / 结构异常 | False | `⚠ range_check 暂不可用：eBird 返回内容无法解析（坏 JSON 或结构异常）：<e>` |

**所有 ok=False 都追加一行回退建议**：`回退建议：靠你自身的鸟类学知识判断该种是否合理，并酌情给 species 标 low_confidence。`

**关键设计**：「未知地点」和「空清单」被判为**合法结果**（ok=True）而非失败，与 `bird_id` 的「未认出」语义一致。

---

### 5.3 `bird_id`（risk = `read`，外部 API：懂鸟 hholove）

**给模型看的 description 原文**：

```
对本地鸟类照片做视觉鉴种（懂鸟服务）。当用户【没给出种名但提供了图片】时，用本工具上传图片，得到候选鸟种（中文名 + 置信度），你再据此定种。入参 image_path 是本地图片文件路径（不是 URL）。
```

**input_schema / pydantic schema（真实）**：

```python
    input_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "本地鸟类图片文件路径（jpg，≤2MB）"},
        },
        "required": ["image_path"],
    }

class BirdIdInput(BaseModel):
    image_path: str
```

**外部 API 真实参数**（`config.py`）：

```python
HHO_BASE_URL = "https://ai.open.hhodata.com/api/v2"
HHO_PATH = "/dongniao"
HHO_DID = "vibirding01"          # 设备 id，1..32 字母数字
HHO_CLASS = "B"                  # 识别类别："B" = 只认鸟
HHO_MAX_IMAGE_BYTES = 2 * 1024 * 1024   # API 限制 ≤2MB jpg
HHO_UPLOAD_TIMEOUT = {"connect": 10, "read": 60, "write": 60, "pool": 10}
HHO_RESULT_TIMEOUT_S = 30
HHO_POLL_MAX = 5                 # 最多轮询 5 次
HHO_POLL_INTERVAL_S = 2          # 每次间隔 2 秒
```

**异步两步 + 轮询，全部封在 `run()` 内**，对外只回一个 `ToolResult`：

- **步骤 1（上传）**：`POST {BASE}/dongniao`，header `api_key`，**multipart**：`files={"image": (name, bytes, "image/jpeg")}`，`data={"upload": "1", "did": ..., "class": "B"}`，超时 `httpx.Timeout(connect=10, read=60, write=60, pool=10)`（**海外上传慢，httpx 默认 ~5s 会 WriteTimeout**，这是踩过的坑）。
- **步骤 2（取结果）**：同端点 `POST`，**urlencoded** `data={"resultid": <id>}`，`timeout=30`，最多轮 5 次、每次隔 2 秒。

**返回是数组 `[code, payload]`，不是字典**。code 语义：

| code | 阶段 | 含义 | 归一化 |
| --- | --- | --- | --- |
| 1000 | 上传 | payload 是识别 ID | 继续轮询 |
| 1000 | 取结果 | payload 是检测目标数组 | ok=True + 候选列表 |
| 1001 | 上传 | 图片大小不符 | ok=False |
| 1001 | 取结果 | 还没算完 | sleep 2s 重试 |
| 1002–1005 | 上传 | 格式/did/class/地区不支持 | ok=False |
| 1008 / 1009 | 取结果 | 未检测到目标 / 认不出 | **ok=True**（合法结果） |

**候选格式化**（真实代码）：

```python
def _format_candidates(targets: list, top: int = _TOP_CANDIDATES) -> str:
    """Each target: {"box":[...], "list":[[conf, "中文名|英文名|拉丁名", id, cls], ...]}
    Confidence is 0~100 (NOT 0~1); take the first pipe segment (Chinese name)."""
    multi = len(targets) > 1
    lines: list[str] = []
    for i, target in enumerate(targets, 1):
        candidates = target.get("list") or []
        parts = []
        for row in candidates[:top]:
            conf = row[0]  # 0~100
            cn = str(row[1]).split("|")[0] or "?"
            parts.append(f"{cn} {conf}%")
        if parts:
            prefix = f"目标{i}：" if multi else ""
            lines.append(prefix + "、".join(parts))
    if not lines:
        return "懂鸟检测到目标但没有给出候选种。"
    return "懂鸟视觉鉴种候选（置信度为 0~100 百分制，已按置信度排序）：\n" + "\n".join(lines)
```

`_TOP_CANDIDATES = 3`。**置信度是 0~100，而 `Observation.confidence` 是 0~1** —— 两个量纲之间**没有任何代码做转换**，全靠 prompt 让模型自己填 0~1。这是 v2 要注意的坑。

**各分支的真实归一化文案**（全部前缀 `⚠ bird_id 暂不可用：`，全部追加 `回退建议：改用外形描述推断 + range_check 核验（裁决第4条），必要时给 species 标 low_confidence。`）：

| 情况 | ok | reason |
| --- | --- | --- |
| 未提供路径 | False | `未提供图片路径 image_path。` |
| 文件不存在 | False | `图片文件不存在：<path>` |
| 文件 > 2MB | False | `图片过大（X.XMB，上限 2MB）：请压缩后再试。` |
| 缺 `HHO_API_KEY` | False | `HHO_API_KEY 未设置：…` |
| 读文件失败 | False | `无法读取图片文件：<e>` |
| 上传超时 | False | `上传图片到懂鸟超时（海外上传较慢，请稍后重试）。` |
| 上传 HTTP 非 2xx | False | `懂鸟上传返回 HTTP <code>。` |
| 上传网络失败 | False | `网络连接懂鸟失败（上传阶段）。` |
| 上传非 1000 码 | False | `懂鸟上传失败：<reason>（code=<n>）。` |
| 取结果超时/HTTP/网络 | False | `取识别结果超时。` / `懂鸟取结果返回 HTTP <n>。` / `网络连接懂鸟失败（取结果阶段）。` |
| 轮询 5 次仍未出 | False | `懂鸟识别超时：轮询 5 次仍未出结果，请稍后重试。` |
| 坏 JSON / 非数组 / code 非整数 | False | `懂鸟返回的不是合法 JSON…` / `懂鸟返回结构非预期数组 [code, payload]：…` |
| **1008 / 1009 未认出** | **True** | `懂鸟未能识别这张图片里的鸟种（未检测到目标或无法判定）；请改用外形描述推断，或让用户人工指定。`（**不套 ⚠ 前缀**） |

**⚠ 资源约束**：懂鸟免费额度约 **50 次调用**。这是整个项目最稀缺的资源，eval 用例集因此全部无图。

---

### 5.4 `append_log`（risk = **`write`**，唯一过闸）

**给模型看的 description 原文**：

```
把你整理好的一条观测记录写入观鸟日志（持久化）。这是唯一会写入的工具，执行前需经用户确认。参数就是这条观测的各字段；不要填 id 和 timestamp，它们由系统自动生成。
```

**input_schema（真实全文）**：

```python
    input_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "地点标准官方名（或省略）"},
            "obs_date": {"type": "string", "description": "观测日期 ISO，如 2026-06-27"},
            "time_of_day": {"type": "string", "description": "时段，如 上午/黄昏"},
            "species": {"type": "string", "description": "鉴定出的鸟种；不确定就省略"},
            "count": {"type": "integer", "description": "数量"},
            "behavior": {"type": "string", "description": "行为描述"},
            "raw_note": {"type": "string", "description": "用户原始笔记原文（务必原样保留）"},
            "confidence": {"type": "number", "description": "把握 0~1；source=user 时省略"},
            "source": {
                "type": "string",
                "description": "物种来源：user | bird_id | inferred | manual",
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标注，如 place_corrected/autoid_conflict/low_confidence",
            },
        },
        "required": ["raw_note", "source"],
    }
```

**pydantic schema（真实）**：

```python
class AppendLogInput(BaseModel):
    """Our-side validation: mirrors Observation MINUS id/timestamp."""
    place: str | None = None
    obs_date: str | None = None
    time_of_day: str | None = None
    species: str | None = None
    count: int | None = None
    behavior: str | None = None
    raw_note: str          # required
    confidence: float | None = None
    source: str            # required
    flags: list[str] = Field(default_factory=list)
```

只有 `raw_note` 和 `source` 是必填。`id` / `timestamp` **不暴露给模型**。

**`run()` 真实行为**：

```python
    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        data = dict(input)  # copy so we never mutate the caller's dict
        data["id"] = uuid.uuid4().hex[:8]
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        obs = Observation.model_validate(data)
        self._log.append(obs)
        return ToolResult(ok=True, output=f"已写入日志：{_summary(obs)}")
```

- `id` = `uuid4().hex[:8]` —— **8 位十六进制，截断的 UUID**。碰撞概率不为零（生日问题下约 ~10 万条时到 1e-3 量级），且**无唯一性校验**。v2 上 PostgreSQL 时这是要换掉的东西。
- `timestamp` = **UTC 带时区**（`datetime.now(timezone.utc).isoformat()`），而 `obs_date` 是模型填的**本地日期字符串**。两者时区口径不一致。

**失败分支**：**无工具级 ok=False**，全部在 registry 层：

| 情况 | 输出 |
| --- | --- |
| 缺 `raw_note` 或 `source` / 类型不符 | `invalid input for append_log: <pydantic ValidationError 全文>` |
| 用户拒绝（approver 返回 deny） | `permission denied: append_log` |
| 写盘 I/O 异常 | `tool error in append_log: <e>` |

---

## 6. Prompt 实际内容

### `vibirding/agent/prompt.py` 全文

```python
"""System prompt for the agent.

Encodes the agent's job for the real model (DeepSeek): the role, when to use
read_log, the place-name correction, the species-source-priority arbitration
(architecture section 8: user-specified > photo ID > description inference via
range_check), and — since S5 — writing the structured Observation by CALLING the
append_log tool (architecture section 8 round 3), whose arguments are exactly the
fields below. id/timestamp are machine-supplied by the tool, not by the model.

Still just a string constant (no signature/structure change). Note: Observation.
source is a plain str, so the "user" value needs no schema change. S6 adds a
tool-failure handling strategy section (strategy text only — arbitration priority
and JSON fields unchanged) plus a today_hint() runtime date anchor.
"""

from __future__ import annotations

from datetime import datetime

SYSTEM_PROMPT = """你是一个观鸟速记助手。用户会给你一段随手记的、可能很乱的观鸟笔记。

你的工作：
1. 读懂笔记，把它整理成一条结构化的观测记录。
2. 可调用下列只读工具辅助判断（是否调用、调用顺序由你判断）：
   - read_log：查“你自己的历史观测记录”（如“我以前在这儿/这季节记录过什么”），只是个人弱先验，不是权威依据。
   - range_check(place, date)：查该地点近期 eBird 实际记录的物种清单，作为“当季合理出现的物种”的权威分布依据；判断某种在某地某季是否合理时优先参考它，其次才是你自身的鸟类学知识。调用时 place 用你纠正后的标准官方名、date 用观测日期（笔记没写就用今天）。
   - bird_id(image_path)：当用户消息里【提供了图片本地路径】（形如“（附图，本地路径：…）”）时，用它对照片做视觉鉴种，得到候选鸟种（中文名 + 置信度）。image_path 就填用户消息里给的那个路径。
3. 完成后，调用 append_log 工具把这条记录写入日志（见下方“写入日志”）；写入成功后再用一两句话给用户总结。

== 物种来源优先级（裁决规则，决定 species / source / confidence / flags）==
优先级：用户指定 > 图片鉴定 > 描述推断（经 range_check 核验）。按下列四种输入分支裁决：
1) 笔记里【直接指定了物种名】 → species = 用户给的名字；source = "user"；confidence = null。无论有没有图片/描述都如此。
2) 在第1条基础上，若【同时有图片或外形描述】且自动鉴定（图片或描述推断）得到的种与用户指定【不一致】 → species 仍用用户指定、source 仍 "user"，但在 flags 加入 "autoid_conflict"（与自动鉴定有分歧）。
3) 用户【没指定种名但有图片】 → 以图片鉴定（bird_id）结果为准；source = "bird_id"。
4) 用户【既没指定种名也没有图片】 → 走“描述 → 你推断 → range_check 季节核验”；source = "inferred"。

兜底：任何分支里只要你对“种”没有把握 → species = null，并在 flags 加入 "low_confidence"，绝不编造种名。

【当前能力说明】bird_id（图片鉴种）与 range_check（季节/分布核验）均已接入、可调用：
- 第3条（无种名但有图片）：调用 bird_id(image_path) 做视觉鉴种，以其候选结果定种、source="bird_id"；若 bird_id 返回“未能识别”或调用失败，退回第4条的“描述推断 + range_check 核验”。
- 第2条（用户已给种名、又有图片/描述）：可调 bird_id 或描述推断做交叉核对，与用户指定不一致时按规则加 "autoid_conflict"（species 仍用用户指定、source 仍 "user"）。
- 第4条（无种名也无图片）：调用 range_check(place, date) 取当地当季物种清单，在清单内挑选与外形描述匹配的种；range_check 不可用时（未知地点、网络失败、空清单）再退回纯鸟类学知识推断。

== 工具失败 / 超时 / 未识别的处理 ==
工具失败、超时、未识别是常态，不要卡死、不要因单个工具失败就放弃整条笔记、也不要硬编瞎答：
- 任一工具返回“⚠ …暂不可用” → 不要盲目重试同一调用；按来源优先级回退。
- bird_id 失败/未识别 → 转用外形描述推断 + range_check 核验（第4条），并酌情给 species 标 "low_confidence"。
- range_check 失败/空清单/未知地点 → 靠你自身的鸟类学知识判断，并酌情标 "low_confidence"。
- 始终给出可写入的结论（哪怕 species=null）；绝不因工具失败而编造种名或停摆。

== 写入日志（重要）==
整理好后，调用 append_log 工具把这条记录写入日志。append_log 的参数就是下列字段（不要填 id 和 timestamp，它们由系统自动生成）：
- place: 地点的【标准官方名称】（字符串或 null）。若笔记里的地点是明显的拼写/音近错误，请用你的知识纠正成规范名再填入（例：把 "卡西临海公园"、"割席临海公园" 纠正为 "葛西临海公园"），以免后续按地点查记录时查不到；只在较有把握时纠正，拿不准就保留原文，切勿臆造地名。
- obs_date: 观测日期（ISO 格式如 2026-06-24；笔记没提就 null）
- time_of_day: 时段（如 "上午"、"黄昏"；没有就 null）
- species: 鉴定出的鸟种（按上面“物种来源优先级”裁决；不确定就 null）
- count: 数量（整数或 null）。注意识别隐含的单只：量词“一只/一头/一羽”表示 count=1；并容忍音近误写（如“一直”=“一只”、“两只”=2）。只有当笔记完全没提及数量时才填 null。
- behavior: 行为描述（字符串或 null）
- raw_note: 原始笔记原文（务必原样保留）
- confidence: 你对鉴定的把握，0~1 的小数（或 null；source="user" 时按规则填 null）
- source: 物种来源，取值 "user" | "bird_id" | "inferred"（按上面裁决规则决定）
- flags: 字符串数组，标注情况；没有就 []。规则：纠正了地点拼写加 "place_corrected"；与自动鉴定分歧加 "autoid_conflict"；对种没把握加 "low_confidence"；季节/分布异常加 "season_unusual"。

规则：
- 拿不准的字段一律省略（不传该参数），不要编造。
- 地点纠错：place 填纠正后的标准名；若用 read_log 查历史，也用这个标准名去查，以提高命中率。
- raw_note 必须是用户的原话（即使你纠正了 place，raw_note 也保留原始错字，不要改）。
- append_log 返回写入成功后，再用一两句话向用户总结这条记录，不必把所有字段逐个念一遍。"""


def today_hint(now: datetime | None = None) -> str:
    """A runtime date anchor injected at message-assembly time (the entry layer).

    SYSTEM_PROMPT is a static constant and cannot know "today", so the prompt's
    "use today if the note omits a date" rules need this anchor. The entry script
    appends it to the system message content; the constant itself stays unchanged.
    `now` is injectable so tests are deterministic.
    """
    d = (now or datetime.now()).strftime("%Y-%m-%d")
    return (
        f"（运行时信息：今天是 {d}。笔记未注明日期时，obs_date 与 range_check 的 date "
        f"用这个“今天”。）"
    )
```

### 对「当前实际行为」的关键解读

**物种来源裁决** —— 四分支，优先级 `用户指定 > 图片鉴定 > 描述推断`：

- 分支 1（有种名）：**无条件采信用户**，`source="user"`，`confidence=null`。
- 分支 2（有种名 + 有图/描述且冲突）：仍用用户的，只加 `autoid_conflict` flag。
- 分支 3（无种名 + 有图）：`bird_id` 定种，`source="bird_id"`。
- 分支 4（无种名无图）：描述推断 + `range_check` 核验，`source="inferred"`。

**⚠ 已量化的边界**：分支 1 **不强制做季节核验**。只有分支 4 才必然走 `range_check`。这正是 eval t04（7 月的红嘴鸥）FAIL 的直接成因——模型直接采信用户种名写盘，不调 `range_check`、不标 `season_unusual`。但同类的 t05（斑鸫）却 PASS，说明是**模型行为不稳定**而非完全不会。

**不确定处理**：兜底规则明确——`species = null` + `flags` 加 `low_confidence`，「绝不编造种名」。另有全局规则「拿不准的字段一律省略（不传该参数）」。

**`count` 的实际教法**：prompt 只教了「一只/一头/一羽 → 1」和音近误写容错，**完全没有覆盖「十几只 / 几只」这类模糊量词**。所以模型遇到「十几只」倾向留空 —— 这是 eval t02 FAIL 的直接成因。

**`place` 的实际教法**：要求填**标准官方名**，并**主动纠正音近错字**（prompt 里直接举了「卡西临海公园 / 割席临海公园 → 葛西临海公园」的例子），纠正后加 `place_corrected` flag，同时 `raw_note` 必须保留原错字。这个纠正**完全靠模型的世界知识**，代码侧没有任何地名别名表——`tools/locations.py` 那 8 个条目是**纠正之后**用来查坐标的，不参与纠正。

**`obs_date` 的实际教法**：笔记没写日期就填 `today_hint()` 注入的今天；否则 null。这个「今天」是**入口层运行时拼进 system 消息**的，不是常量。

**工具失败回退**：prompt 专门有一节教模型识别 `⚠ …暂不可用` 前缀，并规定「不要盲目重试同一调用」「按来源优先级回退」「始终给出可写入的结论」。这与 `tools/failures.py` 的统一文案格式是配套设计的。

---

## 7. 存储现状

### `memory/log.py` 真实实现

```python
class Log:
    """An append-only JSONL log of Observations, backed by a single file."""

    def __init__(self, path: Path | None = None) -> None:
        # Default to the project log; callers (tests) may inject a temp path.
        self.path = path or config.OBSERVATIONS_PATH

    def append(self, obs: Observation) -> None:
        """Append ONE Observation as a single JSON line. Strictly append-only."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(obs.model_dump(), ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def query(
        self,
        place: str | None = None,
        species: str | None = None,
        date_range: str | None = None,
    ) -> list[Observation]:
        """Read-only sequential scan, returning the Observations that match."""
        if not self.path.exists():
            return []
        results: list[Observation] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue  # tolerate blank lines
                try:
                    obs = Observation.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    # bad JSON or schema-invalid row: skip it
                    continue
                if _matches(obs, place, species, date_range):
                    results.append(obs)
        return results


def _matches(obs, place, species, date_range) -> bool:
    """place / species use SUBSTRING containment. If a filter is set but the
    field is None, it cannot match -> False."""
    if place is not None and (obs.place is None or place not in obs.place):
        return False
    if species is not None and (obs.species is None or species not in obs.species):
        return False
    return _in_date_range(obs.obs_date, date_range)


def _in_date_range(obs_date: str | None, date_range: str | None) -> bool:
    """Minimal "start..end" range check over ISO date strings — lexicographic."""
    if date_range is None or ".." not in date_range:
        return True  # no / unsupported filter -> do not exclude
    start, _, end = date_range.partition("..")
    start, end = start.strip(), end.strip()
    if obs_date is None:
        return False
    if start and obs_date < start:
        return False
    if end and obs_date > end:
        return False
    return True
```

**对 v2 迁移 PostgreSQL 最相关的行为事实**：

| 事实 | 后果 |
| --- | --- |
| 只有 `append` 和 `query`，**没有 update / delete** | 现有代码零处依赖可变性，迁库不会踩到隐式改写 |
| `open(path, "a")` **无锁、无 fsync、无事务** | 并发写会交错；单进程 CLI 下不成问题，v2 上 Web 后必须解决 |
| `query()` **全文件顺序扫描 + 全量 pydantic 反序列化** | O(n)，无索引、无分页、无 LIMIT |
| `place` / `species` 是**子串匹配** | 迁 SQL 时对应 `LIKE '%x%'`，不是等值；语义要显式决定是否保留 |
| `date_range` 是 **`"start..end"` 自由字符串 + 字典序比较** | 依赖 `obs_date` 严格为 `YYYY-MM-DD`；**格式没有任何校验**，非法日期会静默错配 |
| **坏行静默跳过**（不报错、不计数、不告警） | 数据损坏时会无声丢数据 |
| `obs_date` 为 None 的行，在有日期过滤时**被排除** | 迁 SQL 时对应 NULL 语义，需显式处理 |

### `observations.jsonl` 真实格式

一行一条，`ensure_ascii=False`，字段顺序即 `Observation` 的声明顺序：

```json
{"id": "93952e87", "timestamp": "2026-08-28T06:26:53.788977+00:00", "place": "葛西临海公园", "obs_date": "2026-08-28", "time_of_day": "傍晚", "species": "家燕", "count": null, "behavior": "在低空来回飞", "raw_note": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞", "confidence": null, "source": "user", "flags": []}
```

> 上面这行是**用真实代码路径现场生成的**（`AppendLogTool.run` → `Log.append`，日志指向临时文件）。它是真实格式，但不是历史使用数据。

### 现有数据量

**零条。** 实测：

```
$ ls -la data/
ls: data/: No such file or directory
```

`data/` 整个目录都不存在（`.gitignore` 排除了它，且 S8 提交记录写明「演示数据已清理，`data/observations.jsonl` 回到初始空态」）。

**所以：没有任何真实使用数据，也没有测试数据留存。** v2 不存在数据迁移问题——只有 schema 迁移问题。同理 `data/traces/` 也不存在，历史 trace 全部已清空。

---

## 8. 入口与调用方式

### `cli.py` 的参数定义（真实代码）

```python
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="vibirding",
        description="观鸟速记 agent：把一句自然语言笔记整理成结构化观测并写入日志；也能查历史。",
    )
    ap.add_argument("note", nargs="+",
                    help="观鸟笔记，或对历史记录的提问（多词会自动拼接；建议加引号）")
    ap.add_argument("--image", metavar="PATH", default=None,
                    help="可选：本地鸟类图片路径，交给 bird_id 做视觉鉴种")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="自动同意写入，跳过 y/n 确认（演示 / 脚本化）")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="打印完整分步 trace（默认只打简洁结果）")
    ap.add_argument("--max-steps", type=int, default=6,
                    help="单回合步数预算（默认 6）")
    return ap.parse_args(argv)
```

实测 `python -m vibirding --help`：

```
usage: vibirding [-h] [--image PATH] [-y] [-v] [--max-steps MAX_STEPS]
                 note [note ...]
```

### 记录 / 查询两种用法怎么区分

**没有子命令**。区分完全交给模型，靠**入口层拼进 system 消息的意图前言**：

```python
# Model-facing routing note, appended AFTER SYSTEM_PROMPT + today_hint(). It only
# routes intent; it does not change any recording rule in SYSTEM_PROMPT.
INTENT_PREAMBLE = """== 先判断本次输入的意图 ==
用户这次给你的，可能是两类之一，请先判断属于哪类：
1) 【记录】一次新的观鸟观测（一句具体的见闻描述）——按上面的流程整理，并调用 append_log 写入日志。
2) 【查询】对历史记录的提问（如“我在某地记录过哪些鸟”“我见过某种鸟吗”“上个月都记了什么”）——
   这时【只调用 read_log 查询，并直接用自然语言回答】；【不要调用 append_log、不要写入任何新记录】。
拿不准时：输入是一次具体观测就按【记录】；输入是一个问句/检索请求就按【查询】。"""
```

组装处（`cli.py:171`）：

```python
    # Entry-layer message assembly: SYSTEM_PROMPT constant stays unchanged.
    system = SYSTEM_PROMPT + "\n\n" + today_hint() + "\n\n" + INTENT_PREAMBLE
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
```

**这条路由没有任何硬约束** —— 没有关键词匹配、没有 `--query` 开关、没有对 `append_log` 的额外禁止。误判时的唯一兜底是写前的 y/n 摘要（`--yes` 时摘要仍打印但自动放行）。

> **未核实**：本次核查环境无 `DEEPSEEK_API_KEY`，**无法实测真实模型下的路由准确率**。STATUS.md 与 S8 commit message 声称两条路径均已端到端冒烟通过，但那是历史记录，不是本次观测。

### 图片怎么传给模型

```python
    if args.image:
        if not Path(args.image).exists():
            print(f"✗ 图片文件不存在：{args.image}")
            return 2
        user_content = note + f"\n（附图，本地路径：{args.image}）"
    else:
        user_content = note
```

**图片是拼成一行自然语言塞进 user 消息的**，不是结构化字段。模型需要自己从这行文本里把路径抠出来填进 `bird_id(image_path)`。**一次只支持一张图**。v2 的图文配对要从这里重做。

### 权限确认的真实交互

```python
def _cli_approver(tool_name: str, risk: str, inp: dict) -> str:
    """Real terminal write-approval prompt, injected into Permissions."""
    print()
    print("⚠  即将写入日志（append_log）：")
    print(f"     地点   : {inp.get('place')}")
    print(f"     日期   : {inp.get('obs_date')}")
    print(f"     时段   : {inp.get('time_of_day')}")
    print(f"     种     : {inp.get('species')}")
    print(f"     数量   : {inp.get('count')}")
    print(f"     source : {inp.get('source')}")
    print(f"     flags  : {inp.get('flags')}")
    print(f"     原文   : {inp.get('raw_note')}")
    ans = input("   写入日志？[y]允许 / [n]拒绝 / [a]本回合都允许: ").strip().lower()
    if ans == "a":
        return "always"
    if ans == "y":
        return "allow"
    return "deny"


def _auto_approver(tool_name: str, risk: str, inp: dict) -> str:
    """--yes: approve every write automatically (demo / scripted use)."""
    return "always"
```

注入处：

```python
    permissions = Permissions(approver=_auto_approver if args.yes else _cli_approver)
```

**`--yes` 改的是闸的答案，不是绕过闸** —— 仍然走 `Permissions.check` → `risk=="write"` → approver。`input()` 只存在于 `_cli_approver`，从不进执行路径。

**注意**：除 `y` / `a` 外的任何输入（含直接回车、EOF 前的空串）一律 fail-closed 判为 `deny`。

### 一次真实运行的完整输出

> **说明**：本次核查环境**没有 `DEEPSEEK_API_KEY`**，因此下面这次运行用 `MockClient` 顶替模型，**其余全部是真实代码路径**：真 `ToolManager`、真 `range_check`（真的去查了 key，因缺 key 走了真实失败分支）、真 `Permissions` + 真 `_cli_approver`（stdin 喂 `y`）、真 `AppendLogTool` → 真 `Log.append`、真 `TraceWriter`。Log 与 trace 指向临时目录，未污染仓库。

**控制台输出（真实）**：

```
================================================================
输入 : 傍晚 葛西临海公园 家燕 十几只 在低空来回飞
----------------------------------------------------------------
step  1 | model_call   | 模型响应 stop_reason=tool_use，请求 1 个工具
step  2 | tool_call    | 调用工具 range_check
step  3 | tool_result  | 工具 range_check 返回 ok=False
step  4 | model_call   | 模型响应 stop_reason=tool_use，请求 1 个工具
step  5 | tool_call    | 调用工具 append_log

⚠  即将写入日志（append_log）：
     地点   : 葛西临海公园
     日期   : 2026-08-28
     时段   : 傍晚
     种     : 家燕
     数量   : None
     source : user
     flags  : []
     原文   : 傍晚 葛西临海公园 家燕 十几只 在低空来回飞
   写入日志？[y]允许 / [n]拒绝 / [a]本回合都允许: step  6 | tool_result  | 工具 append_log 返回 ok=True
step  7 | model_call   | 模型响应 stop_reason=end_turn，请求 0 个工具
step  8 | final        | 最终答复：已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。
----------------------------------------------------------------
结果： 已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。
已写入: 2026-08-28 葛西临海公园 家燕 ×?  (source=user, id=93952e87)
```

**落盘的 `observations.jsonl`（真实）**：

```json
{"id": "93952e87", "timestamp": "2026-08-28T06:26:53.788977+00:00", "place": "葛西临海公园", "obs_date": "2026-08-28", "time_of_day": "傍晚", "species": "家燕", "count": null, "behavior": "在低空来回飞", "raw_note": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞", "confidence": null, "source": "user", "flags": []}
```

**trace JSONL 全文（真实，8 行）**：

```json
{"step": 1, "timestamp": "2026-08-28T15:26:53.788399", "kind": "model_call", "summary": "模型响应 stop_reason=tool_use，请求 1 个工具", "detail": {"stop_reason": "tool_use", "n_tool_calls": 1, "usage": {"input_tokens": 1210, "output_tokens": 38}, "text_preview": ""}}
{"step": 2, "timestamp": "2026-08-28T15:26:53.788624", "kind": "tool_call", "summary": "调用工具 range_check", "detail": {"name": "range_check", "input": {"place": "葛西临海公园", "date": "2026-08-28"}}}
{"step": 3, "timestamp": "2026-08-28T15:26:53.788836", "kind": "tool_result", "summary": "工具 range_check 返回 ok=False", "detail": {"name": "range_check", "ok": false, "output_preview": "⚠ range_check 暂不可用：EBIRD_API_KEY 未设置：请在项目根 .env 写入 EBIRD_API_KEY=<your-key>。\n回退建议：靠你自身的鸟类学知识判断该种是否合理，并酌情给 species 标 low_…"}}
{"step": 4, "timestamp": "2026-08-28T15:26:53.788873", "kind": "model_call", "summary": "模型响应 stop_reason=tool_use，请求 1 个工具", "detail": {"stop_reason": "tool_use", "n_tool_calls": 1, "usage": {"input_tokens": 1360, "output_tokens": 145}, "text_preview": ""}}
{"step": 5, "timestamp": "2026-08-28T15:26:53.788909", "kind": "tool_call", "summary": "调用工具 append_log", "detail": {"name": "append_log", "input": {"place": "葛西临海公园", "obs_date": "2026-08-28", "time_of_day": "傍晚", "species": "家燕", "behavior": "在低空来回飞", "raw_note": "傍晚 葛西临海公园 家燕 十几只 在低空来回飞", "source": "user", "flags": []}}}
{"step": 6, "timestamp": "2026-08-28T15:26:53.789402", "kind": "tool_result", "summary": "工具 append_log 返回 ok=True", "detail": {"name": "append_log", "ok": true, "output_preview": "已写入日志：葛西临海公园 2026-08-28 家燕 ×? （source=user, id=93952e87）"}}
{"step": 7, "timestamp": "2026-08-28T15:26:53.789457", "kind": "model_call", "summary": "模型响应 stop_reason=end_turn，请求 0 个工具", "detail": {"stop_reason": "end_turn", "n_tool_calls": 0, "usage": {"input_tokens": 1520, "output_tokens": 42}, "text_preview": "已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。"}}
{"step": 8, "timestamp": "2026-08-28T15:26:53.789500", "kind": "final", "summary": "最终答复：已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。", "detail": {"stop_reason": "end_turn", "text_preview": "已记录：2026-08-28 傍晚在葛西临海公园观察到家燕，低空来回飞。数量“十几只”未折算成整数，count 留空。"}}
```

注意 `trace.timestamp` 是**本地时间无时区**（`datetime.now().isoformat()`），而 `Observation.timestamp` 是 **UTC 带时区**——两者口径不同。

### 错误处理的真实覆盖

```python
    try:
        llm = DeepSeekClient()  # raises DeepSeekError if DEEPSEEK_API_KEY is missing
    except DeepSeekError as e:
        print("✗ 初始化 DeepSeek 失败：", e)
        print("  提示：把项目根的 .env.example 复制为 .env，并填入 DEEPSEEK_API_KEY。")
        return 2
    ...
    try:
        _, final_text = run_agent_turn(...)
    except DeepSeekError as e:
        print("✗ 调用 DeepSeek 失败（可能是网络或额度问题）：", e)
        return 1
```

实测缺 key（退出码 2）：

```
✗ 初始化 DeepSeek 失败： DEEPSEEK_API_KEY 未设置：请在项目根 .env 写入 DEEPSEEK_API_KEY=<your-key>。
  提示：把项目根的 .env.example 复制为 .env，并填入 DEEPSEEK_API_KEY。
```

**未覆盖的裸栈路径**：CLI 只捕 `DeepSeekError`。`KeyboardInterrupt`（在 `_cli_approver` 的 `input()` 上很容易撞到）和任何非 `DeepSeekError` 的意外异常仍会打出原始 traceback。

---

## 9. 测试与已知问题

### eval 的真实结构

**题目/答案分两个文件，按 `id` 配对**（防泄题）：

`evals/tasks.yaml` —— 只有输入，13 条，**全部无图**：

```yaml
- id: t00
  input_note: "7月12日上午 葛西临海公园 大嘴乌鸦 3只"
  image_path: null

- id: t04
  input_note: "葛西临海公园 红嘴鸥 20只"
  image_path: null

- id: t11
  input_note: "路边一只灰褐色的小鸟，很快就飞走了没看清"
  image_path: null
```

`evals/answers.yaml` —— 只有断言：

```yaml
- id: t04
  expected:
    species_in: ["红嘴鸥"]       # 优先级：仍取用户指定，不许"纠正"成别的鸟
    source: "user"
    flags_contains_any: ["season_unusual", "季节", "分布"]  # 7月东京红嘴鸥属反常
    must_call_tools: ["range_check", "append_log"]

- id: t11
  expected:
    species_in: [null]          # 期望就是"拿不准"
    flags_contains_any: ["low_confidence"]
    source: "inferred"
```

配对逻辑（真实代码）：

```python
def load_cases(tasks_path: Path, answers_path: Path) -> list[dict]:
    """Join the questions file and the answers file by id."""
    tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8")) or []
    answers = {a["id"]: a["expected"] for a in
               (yaml.safe_load(answers_path.read_text(encoding="utf-8")) or [])}
    cases: list[dict] = []
    for t in tasks:
        tid = t["id"]
        if tid not in answers:
            raise SystemExit(f"答案缺失：{tid} 在 {answers_path.name} 里没有对应 expected")
        cases.append({**t, "expected": answers[tid]})
    return cases
```

**比对规则**（`grade()`，11 类断言键，全部可选，**全过才 PASS**）：

```python
def grade(exp: dict, obs, called_tools: set, rc_ok: bool) -> list[tuple[str, bool, str]]:
    """Return [(key, passed, detail), ...]; the case PASSes iff all passed."""
    out: list[tuple[str, bool, str]] = []
    wrote = obs is not None
    ...
    if "place" in exp:
        add("place", wrote and obs.place == exp["place"], ...)          # 精确相等
    if "count_around" in exp:
        n = exp["count_around"]; tol = exp.get("count_tol", _DEFAULT_COUNT_TOL)  # 默认 ±5
        ok = wrote and actual is not None and abs(actual - n) <= tol
    if "species_in" in exp:
        add("species_in", wrote and obs.species in exp["species_in"], ...)  # 清单可含 null
    if "flags_contains_any" in exp:
        tokens = exp["flags_contains_any"]; flags = obs.flags if wrote else []
        ok = any(tok in fl for tok in tokens for fl in flags)           # 子串 + or 语义
    if "must_call_tools" in exp:
        add("must_call_tools", all(t in called_tools for t in exp["must_call_tools"]), ...)  # 子集，多调不算错
    ...
```

**`actual` 的来源**：跑完 agent 后从**该用例专属的临时 Log** 读回最后一条 Observation；工具调用情况取自 trace 的 `tool_call` 事件。

**两档的真实差异**（`run_case`）：

| | 离线档（默认） | 在线档（`--online`） |
| --- | --- | --- |
| 模型 | `MockClient`，剧本**据 answers 合成** | 真 DeepSeek（temperature=0） |
| `range_check` / `bird_id` | `StubRangeCheck` / `StubBirdId` 桩，固定 ok=True 文本 | 真工具，真 HTTP |
| `read_log` / `append_log` | 真工具 | 真工具 |
| `Budget` | `max_steps=len(script)+2` | `max_steps=args.max_steps`（默认 6） |
| system 消息 | 仅 `SYSTEM_PROMPT` | `SYSTEM_PROMPT + today_hint()`（**不含 INTENT_PREAMBLE**） |
| 带图用例 | 跑 | **默认跳过**，需 `--online-images`（保护懂鸟额度） |

**隔离机制**：每条用例一个 `tempfile.mkdtemp()`，临时 `Log`、临时 trace 目录、注入 `lambda *a, **k: "always"` 的自动 approver（不走 stdin）。另有真日志污染守卫：

```python
    real_log_after = _real_log_lines()
    if real_log_before != real_log_after:
        print(f"⚠ 警告：真日志行数变化 {real_log_before} -> {real_log_after}（本应不变！）")
        return 3
    return 0 if passed == total else 1
```

退出码：`0` 全过｜`1` 有 FAIL｜`2` 缺 key｜`3` 真日志被污染。

> **注意**：离线档的「理想模型」剧本是**据答案合成**的，所以 100% 是**构造出来的**——它守护的是「循环→registry→权限闸→Log→读回」这条管线和比对器本身没被改坏，**测不出模型智能**。这一点 eval 自己的注释和 DECISIONS 都写明了。

### 最近一次通过率

**离线档：13/13 = 100%（本次实测复现）**

```
$ python evals/run_evals.py
========================================================================
S7 Evals（offline）— 用例 13 条｜MockClient + 桩工具，离线
========================================================================
PASS  t00
PASS  t01
PASS  t02
PASS  t03
PASS  t04
PASS  t05
PASS  t06
PASS  t07
PASS  t08
PASS  t09
PASS  t10
PASS  t11
PASS  t12

------------------------------------------------------------------------
通过率 13/13 (100.0%)
------------------------------------------------------------------------
```

**在线档：11/13 = 84.6%** —— 来自 `evals/REPORT.md`，记录的运行日期是 2026-08-18。

> **未核实**：本次核查无 `DEEPSEEK_API_KEY`，**在线档未复现**。这个数字有 REPORT.md 的逐条表格支撑（含两条 FAIL 的逐条归因），但不是本次观测。

**`scripts/check_s*.py` 声称合计 132/132** —— **本次未重跑，未核实**。

### 两条在线 FAIL 的归因（引自 `evals/REPORT.md`）

**t04 红嘴鸥 20 只 —— 用户已给种名时漏做季节核验**
期望调 `range_check` 并标 `season_unusual`；实际只调了 `append_log`，`flags=[]`。根因是 prompt 裁决**分支 1 不强制季节核验**（只有分支 4 才必然走 `range_check`）——是**能力边界不是 bug**。对照 t05 斑鸫（同为冬候鸟、同样要求）却 PASS，说明是**模型行为不稳定**。处置：**不改 prompt**（S7 硬约束：只观测不改被测对象）。

**t02 家燕「十几只」—— 模糊量词未抽取为估值**
期望 `count_around: 15`（容差 ±5）；实际 `count=None`。根因是模型对「十几/几只」不给估值，宁可置空；prompt 只教了「一只/一头/一羽」。处置：不改 prompt。

### STATUS.md 里所有未解决项（逐条）

**已知边界 / 技术债：**

1. **⚠ 最重要的资源约束：懂鸟(hholove) API 只有约 50 次免费调用。** 它是 `bird_id` 的后端；每跑一次 `run_s4.py` 或一条带图 eval 就消耗一次。eval 用例集因此全为无图。
2. **在线两条 FAIL（已知、非阻塞）**：t04 用户指定种名时漏季节核验；t02 模糊量词未估值。均忠实量化、未改 prompt 迎合。
3. **S6 端到端 `run_s6.py` 真模型触发未实测**：离线 `check_s6` 24/24 已绿；live 三种触发（`--max-steps 1` / `--max-tokens 50` / `--break-ebird`）从未手动跑过。
4. **`scripts/run_s4.py` 的 `TESTIMGS_DIR` 硬编码**到 `C:\Users\Takko\Desktop\testimgs`（个人图片集，非交付目录）。
5. **`scripts/run_s2.py`（Gemini 入口）** 暂留作备用 provider 参考，「最终可能删」。
6. **DeepSeek 账户额度**：曾遇 `429` / `503`。用户判断 DeepSeek 便宜、额度不担心（瓶颈在懂鸟）。
7. **range_check 名单收窄仍只按 `back` 天 + 展示截断**（未按目标科过滤）；坐标表仅 8 个点、exact-match。
8. **用例集 13 条全无图** —— 带图路径（裁决分支 3）因额度限制只能薄测；`--online-images` 开关已备好但没用过。
9. **README 的 mermaid 图**若在某些渲染器不显示，需退化为文字图。
10. **CLI 记录/查询路由靠模型**，极端问法可能误判，**无硬保证**。
11. **无 `pyproject.toml` / console_scripts**，入口只有 `python -m vibirding`。

**已登记未实现：**

- **S9 批量笔记**：一篇含多条记录、各带各自 `image_path` → 多条 Observation。待解点：多次/批量 `append_log` 的**权限确认粒度**、**图文配对**、**部分失败处理**、**预算放大**、**多记录 eval**。
- **§11 进阶**：核验子 agent（多 agent）／本地模型 `--local`／大工具结果移出 prompt／**SQLite 替代 JSONL**。

> 注意最后一条：架构文档登记的存储演进方向是 **SQLite**，v2 的 PostgreSQL 方向属于**超出现有规划的新决定**。

---

## 10. 文档与代码的偏差

> 这一节是外部顾问最容易踩空的地方。以下每条均已逐条核实。

### A. 文档写了但代码没有

| # | 文档说法 | 代码实际 | 影响 |
| --- | --- | --- | --- |
| **A1** | 架构 §3 与 §9 均写 `run_evals.py（--offline 默认 / --online）` | **`--offline` 参数不存在**。实测 `python evals/run_evals.py --offline` → `error: unrecognized arguments: --offline`。只有 `--online` 一个 flag，不传即离线 | 照文档敲命令**直接报错** |
| **A2** | README「功能亮点」写「预算与容错：**步数 + token 双上限**」；架构 §6 也列了 token 预算 | `Budget` 的 token 逻辑**实现完整**，但 **`cli.py` 与 `run_evals.py` 都不传 `max_tokens`**（默认 `None` = 无上限）。唯一会设的是 `scripts/run_s6.py`（开发脚手架） | **交付路径上 token 上限是惰性的**，实际只有 `max_steps=6` 在兜底 |
| **A3** | `ToolContext` docstring：「Later slices grow it (e.g. the append-only log handle in **S4**)」 | `ToolContext` **至今只有 `permissions` 一个字段**；`Log` 走的是**工具构造函数注入**（`ReadLogTool(log)`），从未进 ctx | 顾问若按 docstring 找 ctx 里的 log 会找不到 |
| **A4** | `Observation` docstring：「there is no append_log until **S4**」 | `append_log` 实际在 **S5** 落地（架构 §10 的切片表也是 S5） | 纯注释过时 |
| **A5** | `harness/__init__.py`：「Full write-approval is **S4**; token budget and tool error-tolerance are **S5**」 | 实际是 **S5** 写入审批、**S6** token 预算与容错 | 纯注释过时，切片编号全错位一格 |

### B. 代码做了但文档没写

| # | 代码实际 | 文档状态 | 影响 |
| --- | --- | --- | --- |
| **B1** | `Permissions` 的 approver 是**三值** `"allow" \| "deny" \| "always"`，`"always"` 会置 `_allow_all_writes` 记住整个回合 | 架构 §6 权限闸契约只写 `-> "allow" \| "deny"`；「本回合一直允许」只在 §5 表格和 §9 隔离说明里一笔带过，**契约块没写** | 顾问按契约实现 approver 会漏掉 `always` |
| **B2** | `Log._matches` 的 `place` / `species` 是**子串包含**匹配 | 架构 §6 只写 `log.query(place=None, species=None, date_range=None)`，**没说匹配语义** | 迁 SQL 时会默认写成等值，改变行为 |
| **B3** | `date_range` 只支持 `"start..end"` 且靠**字典序**比较 ISO 字符串；不含 `..` 一律**不过滤**（不是报错） | 文档只给了 `"2025-01..2025-12"` 的例子，没写「不含 `..` = 不过滤」这个静默降级 | 非法日期格式会**静默错配**，不报错 |
| **B4** | `tools/failures.py`、`tools/locations.py` 两个真实模块 | 架构 §3 的目录树**没列这两个文件**（虽然 §7 的注释里提到了功能） | 目录树不完整 |
| **B5** | `bird_id` 置信度是 **0~100**，`Observation.confidence` 是 **0~1**，**代码不做转换** | 架构 §7 提了「置信度 0~100」，但**没有任何地方点出这个量纲不一致**由模型负责换算 | 数据质量隐患：模型可能直接写 88 进 `confidence` |
| **B6** | `Observation.id` = `uuid4().hex[:8]`（8 位截断），**无唯一性校验** | 架构 §4 只写 `id: str` | 迁 PostgreSQL 做主键时必须换 |
| **B7** | `Observation.timestamp` 是 **UTC 带时区**，`TraceEvent.timestamp` 是**本地时间无时区** | 文档两处都只写「ISO 时间」 | 时区口径不一致 |
| **B8** | `read_log` 结果**无条数上限、无分页**，全量渲染进 prompt | 文档未提 | 日志变大后会撑爆上下文 |
| **B9** | `ToolManager.execute` 中 `schema.model_validate(input)` 的**结果被丢弃**，传给 `run()` 的仍是原始 dict | 架构 §6 只写「schema 校验」 | pydantic 的类型 coercion **不生效**，`run()` 拿到的是模型原样填的值 |

### C. 两者描述不一致

| # | 不一致点 | 详情 |
| --- | --- | --- |
| **C1** | **`source` 的合法取值** | `schemas.py` 注释 / `input_schema` description 都写四值含 `"manual"`；**`SYSTEM_PROMPT` 只给模型三值**（无 `manual`）。且**三处都无校验**——`source: str` 能写任何字符串。`"manual"` 从无代码路径产生 |
| **C2** | **架构 §8 数据流写权限闸是 `y/n`** | 实际 `_cli_approver` 是 **`y/n/a` 三选**，`a` = 本回合都允许 |
| **C3** | **README「已知边界」措辞** | README 写「用户指定种名时**不必然**做季节核验」，读起来像有时会做；REPORT.md 的根因分析更准确：prompt 分支 1 **不强制**，t04 没做、t05 做了，是**模型不稳定** |
| **C4** | **`scripts/` 的定位** | 架构 §3 注为「开发期临时冒烟测试脚本，不属于最终交付结构」，但 `scripts/` 里**同时住着 5 个 `check_s*.py` 离线自检套件**（声称 132 条断言），它们实际承担了回归测试职责，性质与「临时冒烟」不同 |
| **C5** | **在线 eval 的 system 消息** | `cli.py` 拼三段（`SYSTEM_PROMPT + today_hint() + INTENT_PREAMBLE`），**在线 eval 只拼两段**（无 `INTENT_PREAMBLE`）。所以 **eval 测的 prompt 与用户实际跑的 prompt 不完全相同** —— 文档未提及这个差异 |

### D. 本次无法核实的项

| 项 | 状态 |
| --- | --- |
| 在线 eval 11/13 = 84.6% | **未核实**（无 `DEEPSEEK_API_KEY`）。有 `evals/REPORT.md` 逐条记录支撑 |
| CLI 记录/查询路由的真实准确率 | **未核实**（需真模型）。机制已确认存在 |
| `scripts/check_s*.py` 的 132/132 | **未核实**（本次未重跑） |
| `bird_id` 对真实图片的端到端行为 | **未核实**（无 `HHO_API_KEY`，且额度稀缺） |
| `range_check` 对真实 eBird 的返回 | **未核实**（无 `EBIRD_API_KEY`）。失败分支已实测触发 |
| README 声称的 Python 3.10 兼容 | **未核实**。本次实测在 **Python 3.12** 上全部通过 |

---

## 11. 环境与依赖

### `requirements.txt` 真实内容（全文）

```
pydantic
google-genai
python-dotenv
openai
httpx
pyyaml
```

六个包，**全部无版本 pin**，文件末尾无换行。

**完整性已硬验证**：本次在一个全新 venv 里 `pip install -r requirements.txt`，然后 `import pydantic, yaml, openai, httpx, dotenv` 全部通过，离线 eval 一次跑通。全仓 import 扫描出的第三方只有 `pydantic / openai / httpx / yaml / dotenv / google`，六个全覆盖。**别人 clone 能装齐。**

`google-genai` 只被 `llm/client.py`（GeminiClient，备用 provider）和 `scripts/run_s2.py` 使用，**交付路径不需要它** —— 但它仍在 requirements 里，是一个可以砍掉的依赖。

### Python 版本

README 声称 **3.10+**。代码用 `from __future__ import annotations` + `X | None` 语法，理论上 3.10 起可行。**本次实测环境是 Python 3.12**，全部通过；**3.10 未实测**。

### 环境变量 / key

来源统一走 `config.py` 的三个加载器，全部用 `load_dotenv(ROOT_DIR / ".env")` 显式路径（不用 `find_dotenv()`，因为它会走调用栈、从 stdin/REPL 启动时会挂）。**真实环境变量优先于 `.env`**。

| 变量 | 必需性 | 用途 | 缺失时行为 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | **必需** | 运行时大模型 | `DeepSeekClient()` 抛 `DeepSeekError`，CLI 打人类可读提示，退出码 2 |
| `EBIRD_API_KEY` | 调 `range_check` 时 | eBird 分布数据 | 工具返回 ok=False + 统一失败文案，模型按回退建议继续 |
| `HHO_API_KEY` | 仅带 `--image` 时 | 懂鸟视觉鉴种 | 同上 |
| `GEMINI_API_KEY` | 从不需要 | 备用 provider | 只有 `run_s2.py` 用 |

`.env.example` 全文（**只有占位符，无真实 key**，已核实）：

```
# Vibirding — API keys. Copy this file to `.env` and fill in your own values.
# `.env` is gitignored; NEVER commit real keys.

# DeepSeek — the runtime LLM (OpenAI-compatible endpoint). REQUIRED to run the agent.
# Get one at: https://platform.deepseek.com/
DEEPSEEK_API_KEY=

# eBird — authoritative season/distribution data for the range_check tool.
# Only needed when the model calls range_check. Get one at:
# https://ebird.org/api/keygen
EBIRD_API_KEY=

# 懂鸟 / hholove — visual bird-ID backend for the bird_id tool (image cases only).
# Only needed when you pass --image. Free tier is ~50 calls, so use sparingly.
# https://ai.open.hhodata.com/
HHO_API_KEY=

# Optional: legacy Gemini key, only for the retained alternative provider
# (llm/client.py, GeminiClient). Not needed for normal DeepSeek runs.
# GEMINI_API_KEY=
```

**当前仓库里没有 `.env` 文件**，也没有 `.venv`。

### 本机特定假设

| # | 假设 | 位置 | 严重度 |
| --- | --- | --- | --- |
| **1** | **硬编码 Windows 桌面路径**：`TESTIMGS_DIR = Path(r"C:\Users\Takko\Desktop\testimgs")`，配对规则 `<stem>.jpg` + `<stem>_discribe.txt`（注意源文件把 describe 拼错了） | `scripts/run_s4.py:48` | 开发脚本，非交付路径。但**在非该机器上直接不可用** |
| **2** | **坐标表只有 8 个点，且全在东京圈**，exact-match 中文标准名 | `tools/locations.py` | **交付路径**。表外地点 `range_check` 一律降级 |
| **3** | eBird 参数写死 `dist=25km` / `back=14天` / `sppLocale=zh_SIM`（简体中文） | `config.py` | 交付路径，硬编码非配置 |
| **4** | 懂鸟 `did="vibirding01"` 写死 | `config.py` | 交付路径 |
| **5** | eval 素材来源 `testmat/descriptionN.txt` 被 gitignore，**不在仓库里** | `.gitignore` + REPORT.md | 用例已内联进 `tasks.yaml`，不影响跑 eval |
| **6** | STATUS.md 的「运行环境」写死 `.venv\Scripts\python.exe` + PowerShell；README 与 REPORT.md 的命令风格不一致（一个 POSIX 一个 Windows） | 文档 | 项目原开发环境是 Windows；本次核查在 macOS 上跑通无碍 |

**坐标表全文**（v2 若要扩地点，这是唯一的地名→坐标来源）：

```python
PLACE_COORDS: dict[str, tuple[float, float]] = {
    "葛西临海公园": (35.6418, 139.8606),   # Kasai Rinkai Park, Tokyo
    "三宅岛": (34.0833, 139.5167),         # Miyake-jima
    "高尾山": (35.6254, 139.2437),         # Mount Takao, Hachioji, Tokyo
    "东京港野鸟公园": (35.5839, 139.7603), # Tokyo Port Wild Bird Park, Ota, Tokyo
    "明治神宫": (35.6764, 139.6993),       # Meiji Jingu, Shibuya, Tokyo
    "登户": (35.6311, 139.5660),           # Noborito Station, Tama Ward, Kawasaki
    "水元公园": (35.7849, 139.8701),       # Mizumoto Park, Katsushika, Tokyo
    "井之头恩赐公园": (35.6997, 139.5737), # Inokashira Park, Musashino, Tokyo
}
```

---

## 附：给 v2 改造的几个事实要点

这一节不是建议，只是把散在上面各节、**对三个改造方向影响最大的既有事实**汇总一遍。

**关于批量多记录 + 图文配对：**

- `append_log` 一次一条，`AppendLogInput` 是单条形状；循环**支持模型一轮请求多个工具**，所以「一轮里连调 N 次 `append_log`」在循环层是通的，但**权限闸会逐条询问 N 次**（除非用户答 `a`）。
- 图片目前是**拼成一行自然语言塞进 user 消息**的（`\n（附图，本地路径：…）`），一次一张，非结构化。
- `messages` 是**原地修改**的 list，多记录场景下上下文增长没有任何压缩机制（架构 §1 明确「v1 不需要任何压缩，只用 max_steps 兜底」）。
- 预算：交付路径**只有 `max_steps=6`**，token 上限惰性（A2）。批量场景步数会不够。

**关于 PostgreSQL：**

- **没有历史数据要迁**（0 条）。只有 schema 迁移。
- `Log` 的对外契约只有 `append` / `query` 两个方法，**没有 update/delete**，替换面很小。
- 但要注意三个隐性语义：`place`/`species` 是**子串匹配**（B2）、`date_range` 是**字典序字符串比较且非法格式静默不过滤**（B3）、**坏行静默跳过**。
- `id` 是 8 位截断 UUID 无唯一性校验（B6）；`timestamp` 是 UTC 而 `obs_date` 是本地日期字符串（B7）。
- 架构 §11 登记的演进方向是 **SQLite**，PostgreSQL 是超出现有规划的新决定。

**关于 Web 前端：**

- 当前**零 HTTP 服务端代码**，唯一入口是终端 CLI。
- **权限闸依赖 `input()`** —— 但它是**可注入**的（`Permissions(approver=...)`），且 `input()` 只存在于 `cli.py` 的 `_cli_approver`，**从不进执行路径**。这是 v1 花了力气守住的边界，Web 化时可以直接换成一个异步 approver 而不动闸本身。
- `Log` 的 `open(path, "a")` **无锁无事务**，多请求并发会交错。
- trace 一个 run 一个文件写 `data/traces/`，**无轮转无清理**。
- `run_agent_turn` 是**同步阻塞**的，无流式、无中途取消。

---

*快照生成于 2026-08-28，对应 `main` @ `333efef`。所有「实测」标记的输出均为本次现场运行；所有「未核实」标记的项目请勿当作已验证事实。*
