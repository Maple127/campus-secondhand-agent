# 文档索引

> 先看这个目录，再决定读哪一篇。**不需要按顺序全读。**

## 我想……

| 我想… | 读这篇 |
|---|---|
| **30 秒搞清这个项目是什么** | [项目 README](../README.md) |
| **把项目跑起来** | [使用指南](guide.md) · [运维与排错](#运维与排错) |
| **看懂 agent 是怎么工作的** | [Agent 设计](agent-design.md) → [写操作与人工确认](agent-hitl.md) |
| **知道这东西到底有没有用** | [价值评测](evaluation-findings.md) → [消融评测](evaluation-ablation.md) |
| **接 agent 的接口** | [Agent 接口约定](agent-api.md) |
| **看某个具体设计怎么权衡的** | [深入阅读](#深入阅读) |
| **准备面试，看哪里站不住** | [面试自检表](interview-map.md) |
| **看后端业务怎么设计** | [后台管理与业务流程](architecture.md) |
| **找历史改动记录** | [archive/](archive/)（归档，可能已过时） |

---

## 主文档

| 文档 | 讲什么 | 适合谁 |
|---|---|---|
| [guide.md](guide.md) | 零基础使用教程：注册、发布、搜索、下单、管理端操作 | 想跑一遍的人 |
| [architecture.md](architecture.md) | 后台管理与业务流程：审核流、分类管理、账号、测试用例 | 后端 / 产品 |
| [agent-design.md](agent-design.md) | Agent 数据流、13 个工具的设计、幻觉抑制、SSE 协议 | 后端 / AI 应用 |
| [agent-hitl.md](agent-hitl.md) | 写操作为什么必须确认、LangGraph interrupt + 幂等账本 | 后端 / AI 应用 |
| [agent-api.md](agent-api.md) | 双层令牌、scope 一览、响应约定、工具映射 | 要接这个 agent 的人 |
| [evaluation-findings.md](evaluation-findings.md) | 30 任务 × 3 对照的结论：**agent 在哪些场景是负收益** | 所有人（这是本项目的核心判断） |
| [evaluation-ablation.md](evaluation-ablation.md) | 五个单变量消融：每个组件到底贡献多少 | 想看数据的人 |
| [interview-map.md](interview-map.md) | 39 个会被追问的问题 → 答案 → 证据 → 空白 | 要拿它面试的人 |

## 深入阅读

每个文件夹一个主题，都是「一个具体问题怎么权衡」。

| 文档 | 核心结论 |
|---|---|
| [deep-dives/routing.md](deep-dives/routing.md) | 显式三路路由：延迟 −48.6%、输入 token −74.7%；顺带发现 agent 每条请求固定付 ~8k token |
| [deep-dives/injection.md](deep-dives/injection.md) | 两道防线：入口正则拦截 + 不可信内容围栏；22 条测试，9 条专门保证不误杀 |
| [deep-dives/negotiation.md](deep-dives/negotiation.md) | 议价建议：所有金额由 Java 算，模型只负责措辞；价格合理时明确劝你别砍 |
| [deep-dives/product-types.md](deep-dives/product-types.md) | 品类词：把「搜不到」从代码问题变成数据问题，召回 66.7% → 100% |

## 归档

[`archive/`](archive/) 是历史变更记录，**内容可能与当前代码不一致**，只用于追溯。

| 文档 | 原用途 |
|---|---|
| [archive/m1-m2-changelog.md](archive/m1-m2-changelog.md) | 后端加固（正确性缺陷修复、状态机、鉴权） |
| [archive/b2-search-and-pricing.md](archive/b2-search-and-pricing.md) | 搜索强化与比价独立成功能 |
| [archive/ui-fixes.md](archive/ui-fixes.md) | 8 项界面问题修复 |

## 运维与排错

- **启动**：[使用指南 · 快速开始](guide.md)
- **环境变量**：`agent/.env.example`、`backend/src/main/resources/application.properties`
- **脚本**：`infra/start-all.ps1` / `stop-all.ps1` / `smoke-test.ps1`
- **指标**：`GET /api/metrics`（token、重试、压缩、路由计数）
- **健康检查**：`GET /health`（存活，恒 200）· `GET /health/ready`（就绪，依赖挂了返回 503）

## 约定

1. **数字必须可复现**：文档里每个百分比都要能对应到一个脚本或一个实验编号。
2. **失败也要写**：消融实验里失败的、没有结论的，原样保留，不做粉饰。
3. **归档不删除**：过时的文档移到 `archive/`，加横幅说明，不直接删。
