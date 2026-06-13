# AlphaBrief Development Cadence

> 本文档定义 AlphaBrief 的长期开发节奏、每轮 Vibe Coding 工作方式、任务拆分原则、验收标准和复盘流程。  
> 它应该与 `ALPHABRIEF_PRODUCT_BLUEPRINT.md`、`AGENTS.md`、`docs/architecture.md`、`docs/risk_model.md`、`docs/rewrite_policy.md` 一起放在项目中，作为每轮开发前必须读取的指导文件。

---

## 1. 文档目标

AlphaBrief 是一个长期迭代的 AI 原生量化研究与模拟交易系统，不应该用“一次性生成整个项目”的方式开发。

本项目采用 **小步计划、小步实现、小步测试、小步复盘** 的开发节奏。

每一轮开发都必须做到：

1. 先进入 Plan mode。
2. 先阅读项目蓝图和工程规则。
3. 每轮只解决一个明确问题。
4. 不做无关扩展。
5. 不复制参考源码。
6. 新增行为必须有测试。
7. 涉及交易、订单、仓位、模型输出时必须遵守风控边界。
8. 每轮结束都要总结修改内容、测试结果和下一轮建议。

---

## 2. 项目根目录建议

推荐结构：

```text
alphabrief/
├── ALPHABRIEF_PRODUCT_BLUEPRINT.md
├── ALPHABRIEF_DEVELOPMENT_CADENCE.md
├── AGENTS.md
├── README.md
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── risk_model.md
│   ├── agent_protocol.md
│   ├── model_gateway.md
│   ├── rewrite_policy.md
│   └── development_log.md
├── _reference_sources/
│   ├── QuantDinger/
│   ├── TradingGym/
│   └── TradingAgents/
├── apps/
├── packages/
├── strategies/
├── tests/
└── scripts/
```

其中：

- `ALPHABRIEF_PRODUCT_BLUEPRINT.md`：最高级产品蓝图。
- `ALPHABRIEF_DEVELOPMENT_CADENCE.md`：本文件，定义开发节奏。
- `AGENTS.md`：Vibe Coding 工具每轮必须遵守的工程规则。
- `docs/rewrite_policy.md`：约束参考源码的使用方式。
- `_reference_sources/`：仅用于架构参考，不得 import、复制、迁移或改名复用其中代码。

---

## 3. 每轮开发固定流程

每轮开发必须遵守以下流程：

```text
Plan
  ↓
Review Plan
  ↓
Implement
  ↓
Test
  ↓
Self Review
  ↓
Document
  ↓
Commit
  ↓
Next Task Proposal
```

### 3.1 Plan

每轮开始时，先让 Vibe Coding 工具进入 Plan mode。

它必须先阅读：

```text
ALPHABRIEF_PRODUCT_BLUEPRINT.md
ALPHABRIEF_DEVELOPMENT_CADENCE.md
AGENTS.md
docs/architecture.md
docs/roadmap.md
docs/risk_model.md
docs/rewrite_policy.md
当前代码结构
```

然后输出：

1. 本轮目标理解。
2. 当前相关代码概览。
3. 计划新增或修改的文件。
4. 明确不会触碰的模块。
5. 实现步骤。
6. 测试计划。
7. 风险点。
8. 完成标准。

在计划确认前，不允许写代码。

重要添加：加一个文件夹把每轮已经实施的计划用.md的格式记录下来，这样切换到不同的工具都知道上一轮和之前都干了什么

### 3.2 Review Plan

你作为项目 owner 要检查计划是否符合：

1. 是否只做一个小任务。
2. 是否越界实现了未来阶段功能。
3. 是否可能绕过 RiskGate。
4. 是否可能复制 `_reference_sources/` 中的代码。
5. 是否包含测试。
6. 是否包含文档更新。
7. 是否能在一次开发会话内完成。

如果计划过大，必须要求拆小。

### 3.3 Implement

实现阶段只允许做计划中列出的文件变更。

禁止：

1. 顺手重构无关模块。
2. 顺手添加未要求功能。
3. 顺手接入真实交易。
4. 顺手加入复杂依赖。
5. 从 `_reference_sources/` 复制代码。
6. 把参考项目的文件逐行翻译成 AlphaBrief 文件。

允许：

1. 新增必要类型。
2. 新增接口。
3. 新增最小实现。
4. 新增测试。
5. 更新相关文档。
6. 在必要时添加 TODO，但必须说明原因。

### 3.4 Test

每轮都必须运行与本轮相关的测试。

推荐命令：

```bash
pytest
ruff check .
mypy packages apps
```

如果项目初期还没有完整工具链，可以先使用：

```bash
pytest tests/<related_test_file>.py
```

每轮结束时必须报告：

```text
运行了哪些测试
哪些测试通过
哪些测试失败
失败原因是什么
是否有未覆盖风险
```

### 3.5 Self Review

实现完成后，要求 Vibe Coding 工具自查：

1. 是否符合本轮计划。
2. 是否修改了计划外文件。
3. 是否新增了未要求功能。
4. 是否有安全边界问题。
5. 是否有风控绕过风险。
6. 是否有参考源码相似性风险。
7. 是否有未来维护隐患。
8. 是否需要更新文档。

### 3.6 Document

每轮涉及架构、接口、模块边界、风控逻辑、模型调用逻辑时，必须更新文档。

常见文档位置：

```text
docs/architecture.md
docs/risk_model.md
docs/agent_protocol.md
docs/model_gateway.md
docs/roadmap.md
docs/development_log.md
```

### 3.7 Commit

每轮结束后建议提交一次小 commit。

提交信息建议格式：

```text
phase-1-core: add domain models
phase-1-data: add market data provider interface
phase-2-risk: add risk gate approval result
phase-3-models: add model provider interface
phase-3-agents: add AgentBrief schema
```

不要把多个阶段混在一个 commit 中。

### 3.8 Next Task Proposal

每轮结束时，要求工具给出 1 到 3 个下一轮建议。

但下一轮必须仍然由你决定。

---

## 4. 每轮标准 Prompt

每次开始一轮开发，可以使用以下模板：

```text
请进入 Plan mode。

本轮目标：
[在这里填写一个非常小的目标]

请先阅读：
- ALPHABRIEF_PRODUCT_BLUEPRINT.md
- ALPHABRIEF_DEVELOPMENT_CADENCE.md
- AGENTS.md
- docs/architecture.md
- docs/roadmap.md
- docs/risk_model.md
- docs/rewrite_policy.md
- 当前代码结构

重要约束：
- 本轮只做指定目标
- 不要实现未要求的模块
- 不要复制 `_reference_sources/` 中任何代码
- 不要从 `_reference_sources/` import
- 不要逐文件翻译参考项目
- 只能提取行为级 specification
- 所有新增行为必须有测试
- 如果涉及交易意图，必须经过 RiskGate
- 如果涉及模型调用，必须通过 Model Gateway
- 如果涉及订单、仓位、账户、成交、组合状态，必须写审计日志或预留审计接口
- 不允许默认启用 live trading

请先输出计划，包括：
1. 本轮目标理解
2. 当前相关文件
3. 计划新增或修改文件
4. 不会触碰的模块
5. 实现步骤
6. 测试计划
7. 风险点
8. 完成标准

在我确认之前，不要写代码。
```

---

## 5. 每轮实现后的总结 Prompt

实现完成后，使用以下模板要求工具复盘：

```text
请总结本轮开发结果。

请输出：
1. 完成了什么
2. 修改了哪些文件
3. 新增了哪些测试
4. 运行了哪些命令
5. 测试结果
6. 是否有失败测试
7. 是否有未完成 TODO
8. 是否修改了计划外文件
9. 是否存在风控、安全、参考源码相似性风险
10. 下一轮建议
```

---

## 6. 任务拆分原则

AlphaBrief 任务必须拆到足够小。

### 6.1 好任务示例

```text
实现 core domain model：Bar、Signal、OrderIntent、RiskDecision
实现 MarketDataProvider interface
实现 CSV OHLCV loader
实现 Strategy interface
实现 vectorized backtester 的最小版本
实现 backtest metrics：return、max drawdown、Sharpe
实现 RiskGate 的 max order value 检查
实现 PaperBroker 的 market order 模拟成交
实现 AgentBrief Pydantic schema
实现 ModelProvider interface
实现 OpenAI-compatible ProviderAdapter
实现 DailyBriefReport schema
```

### 6.2 坏任务示例

```text
开发完整 AlphaBrief
重写 QuantDinger
重写 TradingGym
重写 TradingAgents
做一个完整 AI 自动交易系统
实现所有 broker 接入
实现完整 dashboard
把参考项目代码改成我们的项目
把这个文件翻译成我们的代码风格
```

坏任务的问题是：范围太大、边界不清、容易复制、容易引入风控漏洞。

---

## 10. 分支与提交策略

建议使用小分支：

```text
feat/core-domain-models
feat/csv-market-data-provider
feat/vectorized-backtester
feat/risk-gate-basic-limits
feat/paper-broker
feat/model-gateway-interface
feat/agent-brief-schema
```

每个分支只做一个目标。

合并前检查：

```text
测试是否通过
lint 是否通过
type check 是否通过
文档是否更新
是否没有计划外文件变更
是否没有参考源码复制风险
是否没有绕过 RiskGate
```

---

## 11. 参考源码使用节奏

当需要参考 `_reference_sources/` 中的项目时，必须使用 clean-room 节奏：

```text
Read Reference
  ↓
Write Behavior Spec
  ↓
Close Reference
  ↓
Implement AlphaBrief Version
  ↓
Write AlphaBrief Tests
  ↓
Similarity Review
```

禁止：

```text
打开参考文件后直接让工具改写
逐函数翻译
保留类名函数名
保留目录结构
复制注释
复制测试用例
复制配置文件
```

允许：

```text
总结它解决了什么问题
总结它有什么用户流程
总结它有什么抽象边界
总结它的测试场景
用 AlphaBrief 自己的模型和命名重新实现
```

---

## 12. 风控相关开发节奏

任何涉及以下内容的任务必须单独成轮：

```text
OrderIntent
Order
Fill
Position
PortfolioState
RiskGate
RiskLimit
PaperBroker
OrderRouter
AuditLog
BrokerAdapter
LiveTradingLock
```

风控相关任务禁止与 UI、模型调用、策略生成混在同一轮。

每个风控任务必须至少包含：

```text
正常通过测试
拒绝测试
边界条件测试
非法输入测试
审计日志测试或审计接口预留
```

---

## 13. 模型接入开发节奏

AlphaBrief 是模型无关系统。

所有模型厂商接入必须通过：

```text
Model Gateway
ModelProvider interface
ProviderAdapter
ModelRegistry
UsageTracker
```

禁止：

```text
在 agent 中直接调用某个厂商 SDK
在策略中直接调用模型 API
在执行模块中直接调用模型 API
让模型输出直接变成 Order
让模型绕过 RiskGate
```

模型接入任务建议顺序：

```text
1. 定义统一 request/response schema
2. 定义 provider interface
3. 定义 registry
4. 实现一个最小 adapter
5. 实现 mock provider
6. 写测试
7. 再接入真实 provider
```

---

## 14. Dashboard 开发节奏

Dashboard 必须最后做，不要一开始沉迷前端。

推荐顺序：

```text
CLI 可用
API 可用
数据结构稳定
报告结构稳定
再做 dashboard
```

Dashboard 初版只需要显示：

```text
策略列表
回测报告
净值曲线
paper portfolio
AgentBrief
风险日志
```

不要一开始做：

```text
复杂拖拽策略编辑器
完整权限系统
多用户 SaaS
真实交易操作台
策略市场
社交功能
```

---

## 15. 每轮验收清单

每轮结束前必须检查：

```text
[ ] 是否只完成了本轮目标
[ ] 是否没有实现无关功能
[ ] 是否没有复制参考源码
[ ] 是否没有 import `_reference_sources/`
[ ] 是否新增或更新测试
[ ] 是否运行了相关测试
[ ] 是否更新了必要文档
[ ] 是否没有绕过 RiskGate
[ ] 是否没有默认启用 live trading
[ ] 是否模型调用都通过 Model Gateway
[ ] 是否提交信息清晰
[ ] 是否记录了下一轮建议
```

---

## 16. 停止条件

如果出现以下情况，必须停止实现，回到 Plan mode：

```text
任务范围变大
需要改动超过预期模块
测试大量失败且原因不明
发现架构冲突
发现风控边界不清
发现参考源码相似性风险
发现需要新增重大依赖
发现需求不明确
```

停止不是失败，而是防止项目失控。

---

## 17. 项目长期原则

AlphaBrief 的长期开发原则：

```text
先研究，后交易
先 paper，后 live
先确定性风控，后 AI 决策辅助
先 CLI，后 dashboard
先单资产，后多资产
先简单策略，后复杂策略
先 mock provider，后真实 provider
先可测试，后智能化
先复盘，后优化
```

---

## 18. 一句话原则

> 每一轮都让系统变得更清晰、更安全、更可测试，而不是更复杂。

