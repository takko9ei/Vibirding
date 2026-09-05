# Vibirding — Codex 工作区指引

## 项目是什么

一个个人级"观鸟速记" agent（Python）。
v1 真实代码现状见 @docs/SNAPSHOT-v1.md；v2 需求与已拍板决策见
@docs/V2-REQUIREMENTS.md；完整的当前架构、目录、数据结构与契约以
@docs/architecture.md 为唯一事实来源。

## IMPORTANT 必须遵守

- IMPORTANT: 严格按 @docs/architecture.md 的目录结构、数据结构、契约与
  当前实施阶段实现，不要自行发明或改动结构。
- IMPORTANT: 一次只实现 @docs/architecture.md 当前实施计划中的一个切片，
  不要一次写多个切片。
- 每完成一个能跑的切片，停下等我 review，再 git commit。
- 要改任何接口或数据结构，先改 @docs/architecture.md，再改代码。

## 怎么写代码

- 代码用清晰的英文注释；关键逻辑写完后用中文逐段解释原理。
- 用中文跟我交流。
- 倾向最小实现：跑通当前切片即可，不提前加"可选进阶"里的东西。

## 技术约定

- Python + pydantic 做数据校验。
- 运行时模型用 DeepSeek（OpenAI 兼容端点，openai SDK，deepseek-v4-flash），不是 Anthropic。
  DeepSeekClient 实现规格见 @docs/architecture.md 第6节；GeminiClient 作为备用 provider 保留。
- 手动函数调用：只声明 tools，自己执行、自己把结果作为 tool 消息回填，
  不用任何 SDK 的自动函数执行。
- v1 兼容的数据结构仍集中在 `vibirding/schemas.py`；v2 新增的数据库/API
  模型以架构文档为准，先定契约和迁移，再写实现。
- 延续 MockClient 和离线 eval 的回归纪律；v2 的每个切片都必须保住既有 v1
  离线 eval 基线，除非架构文档明确调整了验收标准。
