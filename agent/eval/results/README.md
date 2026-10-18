# 评测结果文件

这两份文件是 `python -m eval.run_eval` 的产物，**生成于 2026-10-18 16:08**。

| 文件 | 内容 |
|---|---|
| `report.md` | 可读报告：三组对照的成功率、分类拆解、成本 |
| `report.json` | 逐条原始数据（用于复核，不要只信聚合值） |

## 注意：这两份数据早于后来的一批改动

生成之后，agent 侧又做了这些改动：

- 显式策略路由（REFUSE / FAST / AGENT）
- 提示词注入防护
- 上下文压缩（按 token 预算）
- token 用量指标与重试策略

这意味着：**当前代码跑出来的数字会与这里不同**（尤其延迟与 token）。
它们仍然是有效的"那次测量"的存档，但不要当作"当前性能"来引用。

要更新，先起后端与 agent，然后：

```powershell
cd agent
python -m eval.run_eval --conditions search,single_llm,agent
```

更近期的实验数据在仓库根目录 `infra/results/`（消融 E1~E5）。
