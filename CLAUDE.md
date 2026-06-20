# Vibirding — Claude Code 工作区指引

## 项目是什么

一个个人级"观鸟速记" agent（Python）。
完整架构、目录、数据结构、契约见 @docs/architecture.md —— 唯一事实来源。

## IMPORTANT 必须遵守

- IMPORTANT: 严格按 @docs/architecture.md 的目录结构、数据结构(第4节)、
  契约(第6节)实现，不要自行发明或改动结构。
- IMPORTANT: 一次只实现一个切片(第10节 S1–S7)，不要一次写多个切片。
- 每完成一个能跑的切片，停下等我 review，再 git commit。
- 要改任何接口或数据结构，先改 @docs/architecture.md，再改代码。

## 怎么写代码

- 代码用清晰的英文注释；关键逻辑写完后用中文逐段解释原理。
- 用中文跟我交流。
- 倾向最小实现：跑通当前切片即可，不提前加"可选进阶"里的东西。

## 技术约定

- Python + pydantic 做数据校验。
- 运行时模型用 Google Gemini（google-genai SDK，gemini-3.5-flash），不是 Anthropic。
  GeminiClient 实现规格见 @docs/architecture.md 第6节。
- 手动函数调用：只传 function declarations，自己执行、自己回 functionResponse，
  不用 AutomaticFunctionCalling。
- 数据结构集中在 vibirding/schemas.py，最先定。
- 先用 MockClient 把循环测通，再接真模型和真 API(S1→S2→S3)。
