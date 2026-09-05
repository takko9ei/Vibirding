# Vibirding · S7 Eval 测试报告

> 首次运行：2026-08-18。对应切片 S7（architecture §9 / §10）。
> 复现命令见文末。本报告只记录**这一次**的运行与归因；后续再跑请追加小节或另建报告。
>
> **历史口径说明**：下文提到的临时 JSONL、真日志守卫和 132/132，是 S7 首跑时的
> v1 实际状态。v2 第 1 步已将当前 `run_evals.py` 改为 PostgreSQL 临时 schema 隔离；
> 用例内容和离线 13/13 基线不变。

---

## 1. 这次测了什么

用固定用例集量化 agent「把乱笔记整理成结构化 Observation」的表现，产出**通过率 + 逐条 pass/fail**。
用例集 13 条，全部**纯文本无图**（来源 `testmat/descriptionN.txt`，已被 gitignore，不入库）：

- **有种名（source=user）**：t00 大嘴乌鸦 / t01 栗耳短脚鹎 / t02 家燕 / t03 灰喜鹊 / t04 红嘴鸥 / t05 斑鸫 / t06 山斑鸠
- **无种名靠描述（source=inferred）**：t07 树麻雀 / t08 白鹡鸰 / t09 灰椋鸟 / t10 白额燕鸥 / t11「没看清」/ t12 北红尾鸲

题目与答案**分两份文件**（`evals/tasks.yaml` 只有输入，`evals/answers.yaml` 只有 expected），
喂给模型的只有题目档，杜绝答案漏进 prompt。评分契约（各断言键语义）见 architecture §9。

---

## 2. 两档运行 + 结果

| 档 | 命令 | 结果 | 说明 |
|---|---|---|---|
| **离线** | `python evals/run_evals.py` | **13/13 = 100%** | MockClient + 桩工具，零网络/零 key/不碰真日志；据答案合成「理想模型」驱动真实循环 → 回归保险 |
| **在线** | `python evals/run_evals.py --online` | **11/13 = 84.6%** | 低温真 DeepSeek + 真工具（range_check 走 eBird）；**真实识别质量指标** |
| 回归 | `check_s1/s3/s4/s5/s6` | **132/132 全绿** | 证明 S7 只加测量、未改 agent 任何行为 |

隔离：每条用例用临时 Log + 注入式自动 approver（"always"）+ 临时 trace 目录；
脚本内置「真日志行数前后对比」守卫，本次**未触发**（`data/observations.jsonl` 未被污染）。

退出码约定：离线全过 → exit 0（可当 CI 门禁）；在线 <100% → exit 1（**故意**，在线本就允许非满分，非报错）。

---

## 3. 在线逐条结果

| id | 用例（摘） | 结果 |
|---|---|---|
| t00 | 大嘴乌鸦 3只 | ✅ |
| t01 | 栗耳短脚鹎 5只 在树上一直叫 | ✅ |
| t02 | 家燕 **十几只** 傍晚低空飞 | ❌ count |
| t03 | 灰喜鹊（无数量）| ✅ |
| t04 | **红嘴鸥 20只**（7月，反常）| ❌ 季节核验 |
| t05 | 斑鸫 2只（冬候鸟）| ✅ |
| t06 | 山斑鸠@等等力溪谷（表外地点）| ✅ |
| t07 | 头顶栗色脸颊黑斑 → 树麻雀 | ✅ |
| t08 | 黑白相间抖尾 → 白鹡鸰 | ✅ |
| t09 | 脸颊白嘴橙黄成群 → 灰椋鸟 | ✅ |
| t10 | 白色燕鸥黄嘴黑尖 → 白额燕鸥 | ✅ |
| t11 | 灰褐色「没看清」→ 拿不准(null) | ✅ |
| t12 | 腹橙红抖尾 → 北红尾鸲（冬候鸟）| ✅ |

---

## 4. 两条 FAIL 的归因（"为什么没过"）

### t04 红嘴鸥20只 —— 用户已给种名时漏做季节核验
- **期望**：即便种名由用户指定，7 月东京出现红嘴鸥属反常，应调 `range_check` 核验并标 `season_unusual`（答案：`must_call_tools:[range_check,append_log]` + `flags_contains_any:[season_unusual,季节,分布]`）。
- **实际**：模型只调了 `append_log`，`flags=[]`，直接 `source=user` 写入。
- **根因**：prompt 的裁决**分支1（用户指定种名）不强制再做季节核验**——只有分支4（无种名靠描述）才必然走 range_check。这是 prompt 的**能力边界**，不是 bug。
- **注意对照**：**t05 斑鸫**（同为冬候鸟、同样要求 range_check + 季节 flag）却 PASS——模型对斑鸫核验了、对红嘴鸥没核验，说明这是模型**行为不稳定**，并非完全不会。这类"同类不同命"正是 eval 的价值。
- **处置**：**不改 prompt**（S7 硬约束：只观测不改被测对象）。若日后想让此类稳定通过，是"核验子 agent / 强化 prompt 分支1"的后续课题（architecture §11）。

### t02 家燕"十几只" —— 模糊量词未抽取为估值
- **期望**：`count_around:15`（容差 ±5，即 10~20）。
- **实际**：`count=None`——模型把"十几只"留空了。
- **根因**：模型对"十几/几只"这类**模糊数词**不给估值，宁可置空。纯数量抽取短板，与季节无关。
- **处置**：不改 prompt。属可讨论的 prompt 抽取规则强化（现 prompt 已教它认"一只/两只"等，但未覆盖"十几"）。

---

## 5. 一句话结论
主线（有种名写入、描述推断、拿不准置空、未知地点降级）**稳**；两处短板明确且可解释：
**用户指定种名时不必然做季节核验** + **模糊量词不估值**。二者均为模型/prompt 层面的已知边界，S7 忠实地把它们量化了出来。

---

## 6. 复现

当前版本复现前需启动本地 PostgreSQL，并在 `.env` 中设置 `DATABASE_URL`：

```powershell
docker compose up -d postgres
.venv\Scripts\python.exe -m alembic upgrade head
```

```powershell
# 离线（默认，安全，应 100%）
.venv\Scripts\python.exe evals\run_evals.py

# 在线（真 DeepSeek + 真工具，需 DEEPSEEK_API_KEY / EBIRD_API_KEY）
.venv\Scripts\python.exe evals\run_evals.py --online --max-steps 6

# 只跑某几条 / 限量
.venv\Scripts\python.exe evals\run_evals.py --online --ids t02,t04
.venv\Scripts\python.exe evals\run_evals.py --online --max-cases 5
```

- 带图用例（当前无）在线默认跳过，需 `--online-images` 才放开（保护懂鸟 hholove 约 50 次免费额度）。
- 当前每个用例使用独立 PostgreSQL 临时 schema；不会读写开发 schema，结束后自动删除。
- 失败用例的临时目录 / trace **不删**（路径见运行输出），便于逐步回看循环；通过的用例临时目录自动清理。
