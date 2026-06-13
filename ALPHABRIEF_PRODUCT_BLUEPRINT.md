# AlphaBrief 产品最终蓝图

> **文件用途**：本文件是 AlphaBrief 项目的长期产品、架构、模型接入、开发、风控和复盘指导文档。  
> **放置位置建议**：项目根目录：`ALPHABRIEF_PRODUCT_BLUEPRINT.md`。  
> **最高原则**：AlphaBrief 是一个自有架构、自有代码、自有风控的 AI 原生量化研究与模拟交易系统。外部开源项目只能作为需求与架构参考，不能成为实现来源。  
> **构建方式说明**：vibe coding 工具只是开发系统时使用的工程辅助工具，不是 AlphaBrief 的产品能力、运行依赖或用户卖点。本蓝图只定义 AlphaBrief 产品本身。

---

## 0. 项目一句话定义

**AlphaBrief 是一个模型无关、本地优先、以研究、回测、仿真、模拟交易、风控审计和复盘为核心的 AI 量化研究工作台。**

它帮助用户完成：

```text
市场数据接入 → 多模型研究分析 → 交易假设生成 → 策略规格化 → 回测验证 → 仿真训练 → paper trading → 风险审计 → 复盘改进
```

AlphaBrief 的核心价值不是“让 AI 自动替用户赚钱”，而是：

> **让个人交易者像一个小型量化研究团队一样，系统地产生、验证、执行、审计和复盘交易想法。**

AlphaBrief 的 AI 能力来自统一的 **Model Gateway**，可接入不同厂商、不同模型、不同推理能力的 API。系统不绑定任何单一模型厂商，也不把某个开发工具当作产品能力。

---

## 1. 产品北极星

### 1.1 AlphaBrief 要成为用户的什么

AlphaBrief 要成为用户的：

```text
AI 市场研究员
多模型研究委员会
策略实验室
回测实验室
交易仿真环境
paper trading 沙盒
风险官
审计系统
复盘日志系统
个人交易知识库
```

最终产品形态：

> **AI-Native Quant Research & Paper-Trading Workbench**  
> **AI 原生量化研究与模拟交易工作台**

### 1.2 用户每天如何使用 AlphaBrief

用户每天打开 AlphaBrief 后，应当看到：

```text
1. 今日市场摘要
2. 关注标的的技术结构
3. 新闻 / 宏观 / 情绪变化
4. 多模型研究结论
5. 多空论证摘要
6. 策略信号和候选观察清单
7. 风险官提醒
8. paper trading 仓位、订单、成交、净值
9. 历史决策复盘
10. 下一步研究任务
```

用户可以输入自然语言：

```text
研究 NVDA 未来 5 个交易日的多空机会。
把这个交易想法整理成可回测的 StrategySpec。
检查这个策略假设是否存在未来函数风险。
比较多个模型对 BTC 本周走势的判断差异。
生成今天的 AlphaBrief 日报。
解释昨天 paper trading 亏损的主要来源。
```

系统输出的不是“盲目交易指令”，而是：

```text
结构化研究报告
多模型观点对比
可审计策略规格
回测报告
风险审查结果
模拟交易记录
复盘总结
```

---

## 2. 产品边界：AlphaBrief 是什么，不是什么

### 2.1 AlphaBrief 是什么

AlphaBrief 是：

```text
1. 个人量化研究系统
2. 多模型金融研究工作台
3. 策略假设验证平台
4. 回测与仿真系统
5. paper trading 系统
6. 风控审计系统
7. 交易复盘系统
8. 个人研究知识库
```

### 2.2 AlphaBrief 不是什么

AlphaBrief 不是：

```text
1. AI 自动炒股机器人
2. 高频交易系统
3. 一键暴富策略生成器
4. 三个 GitHub 项目的代码拼接
5. 某个模型厂商的壳应用
6. 某个开发工具的产品化包装
7. 默认接入真实资金的自动下单系统
8. 不经审计就让模型修改交易逻辑的系统
```

### 2.3 MVP 明确不做

MVP 不做：

```text
1. 默认 live trading
2. 杠杆自动交易
3. 高频交易
4. 模型直接下单
5. 模型自主加仓
6. 自动策略直接上实盘
7. 未审计 broker adapter
8. 无交易成本的虚假回测
9. 不可复现的研究流程
10. 不可追溯的模型输出
```

---

## 3. 三个参考项目在 AlphaBrief 中的角色

本项目会把三个 GitHub 项目的源码放入项目文件夹中作为**参考资料**。它们只用于理解产品形态、模块边界、交互模式、测试场景和架构思想。

AlphaBrief 不复制、不改名重用、不直接迁移其源码，也不使用其代码作为实现基础。

| 参考项目 | 在 AlphaBrief 中的参考价值 | 不允许做的事 |
|---|---|---|
| QuantDinger | 本地优先量化平台、策略开发、回测、执行、产品外壳、审计日志 | 不复制后端、前端、broker adapter、UI、命名和业务代码 |
| TradingGym | Gym/Gymnasium 风格交易仿真环境、reward、episode、action/observation 设计 | 不复制 env 实现、reward 实现、训练脚本 |
| TradingAgents | 多智能体研究流程、分析师 / 研究员 / 风控 / 交易员角色分工 | 不复制 agent prompt、工作流实现、类结构、工具调用代码 |

### 3.1 参考源码目录规则

推荐目录：

```text
alphabrief/
├── _reference_sources/
│   ├── QuantDinger/        # 只读参考源码
│   ├── TradingGym/         # 只读参考源码
│   └── TradingAgents/      # 只读参考源码
├── docs/
├── packages/
├── apps/
└── PROJECT_RULES.md
```

`_reference_sources/` 必须遵守以下规则：

```text
1. 不纳入 AlphaBrief package import path。
2. 不允许 AlphaBrief 代码 import 其中任何模块。
3. 不允许从参考源码复制函数、类、文件、注释、prompt、配置或测试。
4. 不允许把参考源码中的文件改名后放入 AlphaBrief。
5. 不允许在开发任务中要求“迁移这个文件”“照这个类改写”“按这个实现重构”。
6. 只允许提取：产品需求、模块边界、行为描述、测试场景、交互模式。
7. 任何从参考项目得到的灵感必须先转化为自然语言 spec，再从 spec 实现。
8. 如果参考项目许可证与 AlphaBrief 目标冲突，以 AlphaBrief 自有实现为准。
```

### 3.2 最安全的重写流程

推荐采用“规格提取 → 隔离实现 → 相似性审查”的流程：

```text
Phase A: 参考分析
1. AI 工程辅助工具阅读 _reference_sources。
2. 只输出 docs/reference_notes/*.md。
3. reference_notes 只能写自然语言需求、接口想法、行为约束、测试场景。
4. 不允许包含原项目代码片段。
5. 不允许保留原项目的类名、函数名、prompt 文案或文件结构。

Phase B: 实现隔离
1. 关闭、移出或忽略 _reference_sources。
2. 只基于 blueprint、PROJECT_RULES.md、reference_notes、issues 实现 AlphaBrief。
3. 每个模块必须有自有接口、自有命名、自有测试。
4. 实现时禁止打开参考项目文件逐行对照。

Phase C: 相似性审查
1. 检查是否存在大段相似代码。
2. 检查是否存在同名类 / 同名函数 / 同结构文件。
3. 检查是否存在复制的 prompt、注释、README 文案。
4. 检查许可证和 NOTICE。
5. 审查通过后才允许合并到主干。
```

如果 vibe coding 工具不支持忽略目录，建议在真正实现阶段把 `_reference_sources/` 暂时移动到 repo 外。

---

## 4. 产品核心原则

### 4.1 Research-first

AlphaBrief 的第一性原则是研究，而不是交易。

所有交易动作都必须可追溯到：

```text
研究假设
数据证据
策略逻辑
回测结果
风险审查
用户授权
```

### 4.2 Paper-first

MVP 只允许 paper trading。

真实交易必须满足：

```text
1. 显式配置打开
2. 明确 broker adapter 解锁
3. 用户二次确认
4. 风控阈值完整
5. 审计日志开启
6. kill switch 可用
7. paper trading 稳定运行至少 30-60 天
```

### 4.3 Model-as-researcher, not trader

模型只能生成：

```text
研究报告
多空观点
证据摘要
风险解释
策略规格草案
OrderIntent
复盘总结
```

模型不能直接执行：

```text
真实下单
绕过风控
修改 broker adapter
关闭审计日志
改变 live trading 开关
自动提高杠杆
自动提高仓位上限
```

### 4.4 Deterministic risk before execution

任何交易意图必须经过：

```text
OrderIntent → RiskGate → RiskDecision → PaperBroker / BrokerAdapter
```

没有 RiskDecision，不得生成 Order。

### 4.5 Model-agnostic

AlphaBrief 必须模型无关。

```text
1. 不绑定任何单一模型厂商。
2. 不把模型名字写死在业务逻辑里。
3. 所有模型调用必须经过 Model Gateway。
4. 不同模型可以承担不同角色。
5. 模型输出必须结构化、可验证、可审计。
6. 模型失败时系统必须可降级运行。
```

### 4.6 Audit everything

必须记录：

```text
模型输入
模型输出
模型版本 / provider / 参数
研究结论
策略信号
OrderIntent
RiskDecision
订单
成交
仓位变化
用户操作
配置变化
```

---

## 5. 总体系统架构

### 5.1 分层架构

```text
AlphaBrief
├── Product Layer
│   ├── Web Dashboard
│   ├── CLI
│   ├── API
│   └── Report Viewer
│
├── AI Research Layer
│   ├── Model Gateway
│   ├── Provider Adapters
│   ├── Model Registry
│   ├── Prompt / Task Templates
│   ├── Structured Output Parser
│   ├── Research Agents
│   ├── Debate / Committee Flow
│   └── Brief Generator
│
├── Strategy Layer
│   ├── StrategySpec
│   ├── Strategy Interface
│   ├── Signal Engine
│   ├── Strategy Registry
│   └── Strategy Evaluation
│
├── Simulation Layer
│   ├── Vectorized Backtester
│   ├── Event-driven Backtester
│   ├── Trading Environment
│   ├── Reward Functions
│   └── Walk-forward Evaluator
│
├── Risk Layer
│   ├── RiskGate
│   ├── Position Limits
│   ├── Order Sanity Checks
│   ├── Exposure Rules
│   ├── Drawdown Guard
│   └── Kill Switch
│
├── Execution Layer
│   ├── PaperBroker
│   ├── BrokerAdapter Interface
│   ├── OrderRouter
│   ├── Fill Simulator
│   └── Execution Audit Log
│
├── Data Layer
│   ├── Market Data Providers
│   ├── News / Macro / Sentiment Providers
│   ├── Feature Store
│   ├── Data Quality Checks
│   └── Storage
│
└── Observability Layer
    ├── Logs
    ├── Metrics
    ├── Traces
    ├── Cost Tracking
    ├── Model Evaluation
    └── Decision Archive
```

### 5.2 核心数据流

```text
Market Data / News / Macro
        ↓
Data Quality + Feature Store
        ↓
AI Research Layer + Strategy Layer
        ↓
ResearchBrief / StrategySpec / Signal
        ↓
Backtest / Simulation / Evaluation
        ↓
OrderIntent
        ↓
RiskGate
        ↓
RiskDecision
        ↓
PaperBroker / BrokerAdapter
        ↓
Fill / PortfolioState / AuditLog
        ↓
Review / Daily AlphaBrief / Knowledge Base
```

---

## 6. 多模型接入蓝图：Model Gateway

AlphaBrief 的 AI 能力必须由统一的 **Model Gateway** 提供。业务模块不得直接调用任何模型厂商 API。

### 6.1 Model Gateway 的职责

```text
1. 统一不同厂商 API 的调用方式
2. 管理 provider、model、capability、价格、上下文窗口、限流
3. 支持文本、结构化输出、工具调用、长上下文、视觉、多模态等能力标记
4. 根据任务类型选择模型
5. 支持 fallback 和 retry
6. 记录输入、输出、成本、延迟、错误
7. 校验模型输出是否符合 schema
8. 管理 prompt template 和版本
9. 支持模型评测和 A/B 对比
```

### 6.2 Provider Adapter

每个模型厂商都必须通过 Provider Adapter 接入：

```text
ModelGateway
    ├── OpenAIAdapter
    ├── AnthropicAdapter
    ├── GoogleAdapter
    ├── DeepSeekAdapter
    ├── AlibabaQwenAdapter
    ├── MoonshotAdapter
    ├── ZhipuAdapter
    ├── MistralAdapter
    ├── XAIAdapter
    ├── LocalOllamaAdapter
    └── LocalVLLMAdapter
```

注意：以上只是可选接入方向，不代表 MVP 必须全部实现。

### 6.3 模型能力抽象

模型不能只用名字管理，必须用 capability 管理。

```text
ModelCapability
├── text_generation
├── structured_output
├── tool_calling
├── json_mode
├── long_context
├── low_latency
├── low_cost
├── strong_reasoning
├── multilingual
├── code_generation
├── vision
├── embeddings
└── reranking
```

业务模块只能声明需求：

```text
我需要：strong_reasoning + structured_output + long_context
我需要：low_cost + summarization
我需要：json_mode + tool_calling
```

不能写死：

```text
必须用某个具体模型
必须用某个具体厂商
```

### 6.4 推荐的模型任务路由

```text
市场摘要：低成本长上下文模型
新闻整理：低成本摘要模型
复杂推理：强推理模型
多空辩论：不同模型交叉验证
结构化输出：JSON 稳定模型
代码解释：代码能力强的模型
风险审查：强推理 + 结构化输出模型
复盘总结：长上下文 + 中文表达强的模型
```

### 6.5 多模型研究委员会

AlphaBrief 应支持多个模型对同一问题给出独立判断。

```text
Question: 未来 5 个交易日 NVDA 是否值得进入观察清单？

Model A: 技术面分析
Model B: 新闻与财报摘要
Model C: 风险反方观点
Model D: 综合裁判

输出：
1. 共识观点
2. 分歧点
3. 关键证据
4. 不确定性
5. 建议观察条件
6. 禁止执行的条件
```

### 6.6 模型输出必须结构化

所有关键模型输出必须符合 schema。

禁止：

```text
模型返回一段自由文本，然后系统直接相信。
```

必须：

```text
模型返回 JSON / Pydantic 可验证结构。
验证失败则拒绝进入下一阶段。
```

示例：

```json
{
  "symbol": "NVDA",
  "time_horizon": "5 trading days",
  "view": "bullish_watchlist",
  "confidence": 0.62,
  "bullish_evidence": ["..."],
  "bearish_evidence": ["..."],
  "key_risks": ["..."],
  "suggested_action": "watch",
  "order_intent": null,
  "needs_human_review": true
}
```

---

## 7. 核心模块定义

## 7.1 Data Layer

Data Layer 负责所有数据接入、清洗、存储和质量检查。

### 目标

```text
1. 接入 OHLCV 数据
2. 接入新闻 / 宏观 / 情绪数据
3. 标准化 symbol、timezone、calendar
4. 生成特征
5. 检查数据缺失、重复、异常值
6. 保存可复现数据快照
```

### MVP 数据源

```text
1. CSV / Parquet
2. 手动上传数据
3. 开放 API 数据源
4. 模拟新闻输入
```

### 后续数据源

```text
1. 股票行情
2. 加密货币行情
3. ETF 数据
4. 财报 / filings
5. 新闻 API
6. 社交情绪
7. 宏观数据
8. 链上数据
```

### 不可妥协要求

```text
1. 所有回测必须记录数据版本。
2. 所有特征必须避免未来函数。
3. 所有时间戳必须带 timezone 或明确 calendar。
4. 数据质量不通过，策略不得进入 backtest。
```

---

## 7.2 Research Layer

Research Layer 负责生成 AlphaBrief 的研究内容。

### 输出对象

```text
MarketBrief
SymbolBrief
SectorBrief
RiskBrief
ModelDebateReport
DailyAlphaBrief
```

### 核心功能

```text
1. 总结市场环境
2. 总结新闻和宏观变化
3. 解释价格结构
4. 发现异常波动
5. 生成多空假设
6. 组织多个模型进行交叉评估
7. 形成可追溯研究报告
```

### 研究结论不得直接变成订单

Research Layer 最多输出：

```text
watchlist
research_thesis
strategy_hypothesis
order_intent_candidate
```

不得输出：

```text
approved_order
broker_order
live_order
```

---

## 7.3 Strategy Layer

Strategy Layer 负责把交易想法变成可验证的策略规格。

### StrategySpec

AlphaBrief 中的策略首先应该是 spec，而不是代码。

```yaml
strategy_id: ema_trend_v1
name: EMA Trend Following
universe:
  symbols: [BTC-USD]
timeframe: 4h
entry:
  condition: close > ema_50
exit:
  condition: close < ema_50
risk:
  max_position_pct: 0.2
  stop_loss: atr_2x
costs:
  fee_bps: 5
  slippage_bps: 10
evaluation:
  train_period: 2020-01-01:2023-12-31
  test_period: 2024-01-01:2025-12-31
```

### 策略实现原则

```text
1. 策略必须先有 StrategySpec。
2. 策略实现必须可测试。
3. 策略不得直接访问 broker。
4. 策略只能输出 Signal 或 OrderIntent。
5. 策略不得绕过 RiskGate。
6. 策略必须记录参数和版本。
```

### 策略代码生成边界

AlphaBrief 可以使用模型辅助生成：

```text
1. 策略规格草案
2. 策略逻辑解释
3. 测试用例建议
4. 伪代码
5. 风险检查清单
```

但生产级策略实现必须满足：

```text
1. 通过单元测试
2. 通过回测一致性测试
3. 通过未来函数检查
4. 通过人工 review
5. 通过风控 review
6. 明确版本号
```

模型输出不能自动进入实盘路径。

---

## 7.4 Backtest Layer

Backtest Layer 是 AlphaBrief 可信度的核心。

### 必须支持

```text
1. 手续费
2. 滑点
3. 资金曲线
4. benchmark 对比
5. CAGR
6. Sharpe
7. Sortino
8. max drawdown
9. win rate
10. turnover
11. exposure
12. trade list
13. strategy parameter snapshot
14. data version snapshot
```

### 回测报告必须包含

```text
1. 策略 ID
2. 策略参数
3. 数据范围
4. 数据来源
5. 交易成本假设
6. 样本内表现
7. 样本外表现
8. 最大回撤
9. 最差交易
10. 是否可能过拟合
11. 是否通过未来函数检查
12. 是否允许进入 paper trading
```

### 禁止接受的回测

```text
1. 没有手续费
2. 没有滑点
3. 没有样本外
4. 没有 benchmark
5. 没有数据版本
6. 没有策略参数
7. 没有未来函数检查
8. 只展示收益不展示风险
```

---

## 7.5 Simulation / Trading Environment Layer

Simulation Layer 负责交易环境、强化学习接口和策略仿真。

### 目标

```text
1. 提供 Gymnasium 风格交易环境
2. 支持 action / observation / reward 抽象
3. 支持手续费和滑点
4. 支持多种 reward function
5. 支持随机策略、规则策略、RL 策略对比
6. 支持 episode 级别评估
```

### MVP 环境

```text
AlphaBriefTradingEnv
├── 单资产
├── OHLCV 输入
├── Discrete action
│   ├── 0 hold
│   ├── 1 half long
│   └── 2 full long
├── transaction cost
├── slippage
├── portfolio value
└── episode metrics
```

### 后续扩展

```text
1. 多资产 allocation
2. continuous action
3. shorting
4. leverage simulation
5. liquidity constraints
6. borrow cost
7. market impact
8. regime-aware rewards
```

### 注意事项

仿真环境的目标不是证明策略赚钱，而是证明：

```text
1. 环境定义正确
2. 交易成本真实
3. reward 没有泄漏未来
4. 训练 / 测试分离
5. 策略可以公平比较
```

---

## 7.6 Risk Layer

Risk Layer 是 AlphaBrief 的核心安全边界。

### RiskGate 必须检查

```text
1. trading_enabled
2. live_trading_enabled
3. strategy_enabled
4. symbol_allowed
5. max_position_pct
6. max_order_value
7. max_daily_loss
8. max_drawdown
9. max_leverage
10. concentration risk
11. duplicate order
12. stale signal
13. data quality status
14. model confidence threshold
15. user approval requirement
```

### RiskDecision

RiskGate 输出：

```json
{
  "approved": false,
  "reason": "Daily loss limit breached",
  "max_quantity": null,
  "risk_tags": ["daily_loss", "blocked"],
  "requires_human_review": true
}
```

### 硬规则

```text
1. 没有 RiskDecision，不得生成 Order。
2. RiskDecision 必须写入 audit log。
3. 模型不能覆盖 RiskDecision。
4. 用户不能通过自然语言绕过 RiskGate。
5. live trading 必须有独立开关。
6. kill switch 触发后所有策略停止。
```

---

## 7.7 Execution Layer

Execution Layer 负责 paper trading 和未来真实 broker 接入。

### MVP 只实现 PaperBroker

```text
PaperBroker
├── submit_order
├── cancel_order
├── get_positions
├── get_cash
├── get_fills
├── get_portfolio_state
└── audit_log
```

### BrokerAdapter Interface

未来可扩展真实 broker，但必须遵守统一接口：

```text
BrokerAdapter
├── capabilities
├── connection_status
├── submit_order
├── cancel_order
├── get_order
├── list_positions
├── list_balances
├── get_fills
└── health_check
```

### Live trading 禁止默认开启

```text
1. 默认没有任何 live broker adapter 被启用。
2. 配置文件中 live_trading_enabled 默认 false。
3. 环境变量中 live trading 默认 false。
4. UI 必须显示 live trading 状态。
5. 第一次启用必须二次确认。
6. 所有 live order 必须独立审计。
```

---

## 7.8 Audit & Review Layer

AlphaBrief 的长期价值来自复盘。

### 必须记录

```text
1. 每次研究任务
2. 每次模型调用
3. 每次策略参数变更
4. 每次回测
5. 每次信号
6. 每次 OrderIntent
7. 每次 RiskDecision
8. 每次 paper order
9. 每次成交
10. 每次仓位变化
11. 每次用户确认
12. 每次异常和失败
```

### 复盘输出

```text
DailyReview
WeeklyReview
StrategyReview
ModelPerformanceReview
RiskReview
PostTradeReview
```

### 长期知识库

所有研究、回测、交易和复盘都应该沉淀为：

```text
1. 策略知识库
2. 失败案例库
3. 风险案例库
4. 模型表现库
5. 市场 regime 记录
6. 用户交易偏差记录
```

---

## 8. 核心领域模型

### 8.1 Market Data

```python
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    source: str
    data_version: str
```

### 8.2 Research

```python
class ResearchBrief:
    brief_id: str
    symbol: str
    created_at: datetime
    time_horizon: str
    market_context: str
    bullish_evidence: list[str]
    bearish_evidence: list[str]
    key_risks: list[str]
    model_votes: list[ModelVote]
    confidence: float
    suggested_next_steps: list[str]
```

### 8.3 Model Call

```python
class ModelCallRecord:
    call_id: str
    provider: str
    model: str
    task_type: str
    prompt_version: str
    input_hash: str
    output_hash: str
    latency_ms: int
    cost_estimate: Decimal | None
    status: str
    created_at: datetime
```

### 8.4 Signal

```python
class Signal:
    signal_id: str
    strategy_id: str
    symbol: str
    timestamp: datetime
    direction: Literal["long", "short", "flat"]
    confidence: float
    horizon: str
    rationale: str
```

### 8.5 OrderIntent

```python
class OrderIntent:
    intent_id: str
    source: Literal["strategy", "model", "manual"]
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: Decimal | None
    target_position_pct: Decimal | None
    limit_price: Decimal | None
    rationale: str
    created_at: datetime
```

### 8.6 RiskDecision

```python
class RiskDecision:
    decision_id: str
    intent_id: str
    approved: bool
    reason: str
    max_quantity: Decimal | None
    risk_tags: list[str]
    requires_human_review: bool
    created_at: datetime
```

### 8.7 Order

```python
class Order:
    order_id: str
    intent_id: str
    risk_decision_id: str
    broker: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: Decimal
    status: str
    created_at: datetime
```

---

## 9. 推荐仓库结构

```text
alphabrief/
├── README.md
├── ALPHABRIEF_PRODUCT_BLUEPRINT.md
├── PROJECT_RULES.md
├── LICENSE
├── NOTICE.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
│
├── _reference_sources/
│   ├── QuantDinger/
│   ├── TradingGym/
│   └── TradingAgents/
│
├── docs/
│   ├── architecture.md
│   ├── model_gateway.md
│   ├── risk_model.md
│   ├── agent_protocol.md
│   ├── strategy_spec.md
│   ├── backtest_standard.md
│   ├── paper_trading.md
│   ├── reference_notes/
│   └── roadmap.md
│
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
│
├── packages/
│   ├── alphabrief-core/
│   ├── alphabrief-data/
│   ├── alphabrief-models/
│   ├── alphabrief-research/
│   ├── alphabrief-strategy/
│   ├── alphabrief-backtest/
│   ├── alphabrief-gym/
│   ├── alphabrief-risk/
│   ├── alphabrief-execution/
│   └── alphabrief-audit/
│
├── strategies/
│   ├── examples/
│   ├── experiments/
│   └── paper_enabled/
│
├── reports/
├── notebooks/
├── scripts/
└── tests/
```

---

## 10. 模块职责边界

### 10.1 alphabrief-core

负责：

```text
domain models
events
errors
config
time utilities
symbol utilities
```

不得负责：

```text
模型调用
broker 调用
UI
外部数据抓取
```

### 10.2 alphabrief-models

负责：

```text
Model Gateway
provider adapters
model registry
prompt templates
structured output parsing
model call logging
model evaluation
```

不得负责：

```text
交易执行
仓位修改
风控绕过
策略直接启停
```

### 10.3 alphabrief-research

负责：

```text
market brief
symbol brief
multi-model debate
risk narrative
daily AlphaBrief report
```

不得负责：

```text
生成 Order
调用 broker
修改 portfolio
```

### 10.4 alphabrief-strategy

负责：

```text
StrategySpec
strategy interface
signal generation
strategy registry
parameter management
```

不得负责：

```text
直接下单
读取 live broker 状态后偷偷调整订单
关闭风控
```

### 10.5 alphabrief-backtest

负责：

```text
vectorized backtest
event-driven backtest
metrics
backtest reports
walk-forward validation
```

不得负责：

```text
live execution
模型调用
用户界面
```

### 10.6 alphabrief-risk

负责：

```text
RiskGate
limits
pre-trade checks
post-trade checks
kill switch
risk reports
```

不得被任何模块绕过。

### 10.7 alphabrief-execution

负责：

```text
PaperBroker
BrokerAdapter
OrderRouter
FillSimulator
execution logs
```

必须依赖：

```text
RiskDecision
```

没有 RiskDecision，不允许提交订单。

---

## 11. 技术栈建议

### 11.1 MVP 技术栈

```text
Language: Python 3.12+
API: FastAPI
Validation: Pydantic
DataFrame: pandas / polars
Storage: DuckDB + Parquet
Testing: pytest
Property Testing: hypothesis
Lint: ruff
Type Check: mypy / pyright
CLI: typer
Scheduler: APScheduler / Celery / RQ / Arq
Frontend MVP: Streamlit 或 Next.js
Charts: Plotly / lightweight-charts
```

### 11.2 后续技术栈

```text
DB: PostgreSQL
Cache: Redis
Queue: Celery / Dramatiq / Arq
Frontend: Next.js
Auth: Auth.js / custom JWT
Observability: OpenTelemetry
Deployment: Docker Compose → Kubernetes
Model Serving: Ollama / vLLM / hosted API
```

### 11.3 配置原则

```text
1. 所有密钥通过环境变量或 secret manager 管理。
2. 不允许把 API key 写入代码。
3. 不允许把 API key 写入 prompt。
4. 不允许把 API key 写入日志。
5. provider 配置与业务逻辑分离。
6. live trading 配置与 research 配置分离。
```

---

## 12. 开发方式：vibe coding 作为工程辅助工具

vibe coding 工具用于加速工程开发，但 AlphaBrief 的质量标准必须由测试、架构边界、风控规则和审查流程决定。

### 12.1 工具定位

vibe coding 工具可以辅助：

```text
1. 生成模块草案
2. 重构代码
3. 补充测试
4. 总结参考源码行为
5. 生成文档
6. 检查类型错误
7. 修复测试失败
8. 生成迁移脚本
9. 写接口适配器
```

vibe coding 工具不可以：

```text
1. 复制参考源码实现
2. 绕过项目架构
3. 跳过测试
4. 跳过风控
5. 自动合并高风险代码
6. 直接生成 live trading 默认开启逻辑
7. 在没有 spec 的情况下随意写交易逻辑
```

### 12.2 每个开发任务的标准格式

每个任务必须包含：

```text
Goal: 要实现什么
Context: 相关模块和文档
Inputs: 输入数据 / schema / config
Outputs: 输出对象 / 文件 / API
Constraints: 禁止事项和边界
Tests: 必须新增或通过的测试
Done When: 完成标准
```

### 12.3 开发任务示例

```text
Goal:
实现 alphabrief-models 的 ModelGateway MVP。

Context:
阅读 ALPHABRIEF_PRODUCT_BLUEPRINT.md 和 docs/model_gateway.md。
不要读取或复制 _reference_sources 里的实现代码。

Inputs:
ModelRequest, ModelTaskType, ModelCapability, ProviderConfig。

Outputs:
ModelResponse, ModelCallRecord, ProviderAdapter interface。

Constraints:
- 不允许业务模块直接调用 provider SDK。
- 不允许把 provider 名字写死在 research 模块。
- 不实现真实交易相关能力。
- 不记录 API key。

Tests:
- fake provider 可返回结构化结果。
- provider 失败时 fallback 生效。
- schema 校验失败时返回 rejected 状态。
- model call record 不包含敏感信息。

Done When:
pytest 通过，类型检查通过，docs/model_gateway.md 更新。
```

### 12.4 开发审查清单

每个 PR / commit 必须检查：

```text
1. 是否复制参考项目代码？
2. 是否引入同名类、同名函数、同结构文件？
3. 是否绕过 RiskGate？
4. 是否让模型可以直接下单？
5. 是否写入或泄露 API key？
6. 是否缺少测试？
7. 是否缺少审计日志？
8. 是否引入未来函数风险？
9. 是否默认启用 live trading？
10. 是否破坏模型无关原则？
```

---

## 13. PROJECT_RULES.md 应包含的内容

项目根目录应创建 `PROJECT_RULES.md`，作为所有开发工具和贡献者必须遵守的规则。

建议内容：

```text
# AlphaBrief Project Rules

1. AlphaBrief is research-first and paper-trading-first.
2. The system is model-agnostic. All model calls go through ModelGateway.
3. No provider SDK may be called directly from business modules.
4. Models cannot place orders.
5. Models can only produce structured research outputs, StrategySpec drafts, or OrderIntent.
6. Every OrderIntent must pass RiskGate.
7. No RiskDecision means no Order.
8. Live trading is disabled by default.
9. Every strategy must include tests.
10. Every backtest must include transaction costs.
11. Every backtest must include data version and parameter snapshot.
12. No strategy result is accepted without out-of-sample evaluation.
13. _reference_sources is read-only reference material.
14. Do not copy, rename, translate, or migrate code from _reference_sources.
15. Any reference-derived idea must first become a natural language spec.
16. API keys and secrets must never appear in code, logs, prompts, tests, or docs.
17. All important decisions must be audit-logged.
18. If implementation conflicts with risk rules, risk rules win.
```

---

## 14. MVP 路线图

## Phase 1: AlphaBrief Core

目标：完成最小可运行研究与回测内核。

实现：

```text
1. repo scaffold
2. core domain models
3. config system
4. CSV / Parquet market data loader
5. data quality checks
6. feature generation
7. StrategySpec schema
8. simple strategy interface
9. vectorized backtester
10. basic metrics
```

完成标准：

```text
1. 可以导入 OHLCV 数据。
2. 可以运行一个均线策略。
3. 可以输出 backtest_report.json。
4. 回测包含手续费和滑点。
5. 测试和类型检查通过。
```

---

## Phase 2: Model Gateway + Research Brief

目标：完成模型无关 AI 研究层。

实现：

```text
1. ModelGateway
2. ProviderAdapter interface
3. FakeProvider for tests
4. 至少一个真实 provider adapter
5. ModelRegistry
6. PromptTemplate versioning
7. Structured output parser
8. MarketBrief
9. SymbolBrief
10. DailyAlphaBrief
```

完成标准：

```text
1. research 模块不直接调用任何 provider SDK。
2. 可通过配置切换模型。
3. 模型输出失败时可被拒绝。
4. 每次模型调用都有 ModelCallRecord。
5. 可以生成每日 AlphaBrief 日报。
```

---

## Phase 3: Risk + Paper Trading

目标：完成安全模拟交易闭环。

实现：

```text
1. OrderIntent
2. RiskGate
3. RiskDecision
4. PaperBroker
5. OrderRouter
6. FillSimulator
7. PortfolioState
8. ExecutionAuditLog
9. KillSwitch
```

完成标准：

```text
1. OrderIntent 必须经过 RiskGate。
2. RiskDecision 被完整记录。
3. PaperBroker 可以模拟订单和成交。
4. kill switch 可阻止所有订单。
5. live trading 完全关闭。
```

---

## Phase 4: Trading Environment

目标：完成仿真环境。

实现：

```text
1. AlphaBriefTradingEnv
2. action / observation space
3. reward functions
4. transaction cost
5. slippage
6. random policy evaluation
7. buy-and-hold baseline
8. strategy comparison report
```

完成标准：

```text
1. 环境 reset / step 正常。
2. episode metrics 正常。
3. reward 没有未来函数。
4. 成本和滑点生效。
5. baseline 可比较。
```

---

## Phase 5: Dashboard + Review

目标：完成用户日常使用界面。

实现：

```text
1. strategy list
2. backtest report viewer
3. daily AlphaBrief viewer
4. model call history
5. paper portfolio
6. order audit log
7. risk dashboard
8. review journal
```

完成标准：

```text
1. 用户可以查看研究报告。
2. 用户可以查看回测报告。
3. 用户可以查看 paper trading 状态。
4. 用户可以查看每次风险决策。
5. 用户可以生成日/周复盘。
```

---

## 15. 第一批 GitHub Issues

```text
Issue 1: Create repository scaffold and PROJECT_RULES.md
Issue 2: Implement core domain models
Issue 3: Implement market data loader for CSV and Parquet
Issue 4: Implement data quality checks
Issue 5: Implement StrategySpec schema
Issue 6: Implement simple strategy interface
Issue 7: Implement vectorized backtester MVP
Issue 8: Implement backtest metrics and report schema
Issue 9: Implement ModelGateway interface and FakeProvider
Issue 10: Implement provider adapter configuration system
Issue 11: Implement structured output parser
Issue 12: Implement MarketBrief and SymbolBrief schemas
Issue 13: Implement DailyAlphaBrief generator
Issue 14: Implement OrderIntent and RiskDecision schemas
Issue 15: Implement RiskGate MVP
Issue 16: Implement PaperBroker MVP
Issue 17: Implement ExecutionAuditLog
Issue 18: Implement KillSwitch
Issue 19: Implement AlphaBriefTradingEnv MVP
Issue 20: Implement CLI commands for data, backtest, brief, paper
```

---

## 16. CLI 设计

MVP 应优先支持 CLI，因为 CLI 更适合快速验证系统内核。

```text
alphabrief data import --file data/btc.csv --symbol BTC-USD
alphabrief data check --symbol BTC-USD
alphabrief backtest run --strategy ema_trend_v1 --symbol BTC-USD
alphabrief brief daily --symbols BTC-USD ETH-USD NVDA
alphabrief model test --provider openai --task market_summary
alphabrief paper run --strategy ema_trend_v1
alphabrief paper status
alphabrief risk check --intent order_intent.json
alphabrief audit list --date today
alphabrief review daily
```

---

## 17. API 设计

### 17.1 Research API

```text
POST /research/briefs/daily
GET  /research/briefs/{brief_id}
POST /research/symbols/{symbol}/analyze
POST /research/debate
```

### 17.2 Model API

```text
GET  /models/providers
GET  /models/registry
POST /models/call
GET  /models/calls/{call_id}
GET  /models/evaluations
```

### 17.3 Strategy API

```text
POST /strategies/specs
GET  /strategies
GET  /strategies/{strategy_id}
POST /strategies/{strategy_id}/signals
```

### 17.4 Backtest API

```text
POST /backtests
GET  /backtests/{backtest_id}
GET  /backtests/{backtest_id}/report
```

### 17.5 Paper Trading API

```text
POST /paper/order-intents
POST /paper/risk-check
POST /paper/orders
GET  /paper/portfolio
GET  /paper/fills
```

### 17.6 Audit API

```text
GET /audit/events
GET /audit/model-calls
GET /audit/orders
GET /audit/risk-decisions
```

---

## 18. 数据存储设计

### 18.1 MVP 存储

```text
DuckDB
Parquet
JSONL audit logs
local filesystem
```

### 18.2 推荐表

```text
bars
features
strategies
strategy_specs
backtests
backtest_metrics
model_calls
research_briefs
signals
order_intents
risk_decisions
paper_orders
paper_fills
portfolio_snapshots
audit_events
```

### 18.3 Audit Log 格式

```json
{
  "event_id": "evt_...",
  "event_type": "risk_decision.created",
  "timestamp": "2026-01-01T12:00:00Z",
  "actor": "system",
  "source_module": "alphabrief-risk",
  "object_type": "RiskDecision",
  "object_id": "rd_...",
  "payload_hash": "...",
  "metadata": {
    "strategy_id": "ema_trend_v1",
    "symbol": "BTC-USD"
  }
}
```

---

## 19. 测试标准

### 19.1 必须测试

```text
1. domain model validation
2. data loading
3. data quality checks
4. feature no-lookahead
5. strategy signal generation
6. backtest accounting
7. transaction cost
8. slippage
9. metrics correctness
10. model gateway fallback
11. structured output validation
12. risk gate rejection
13. paper broker fills
14. audit log creation
15. kill switch
```

### 19.2 高风险测试

```text
1. 模型返回恶意 JSON，不得下单。
2. 模型要求提高仓位，不得绕过限额。
3. 用户自然语言要求“忽略风控”，不得执行。
4. 数据缺失时不得回测。
5. 信号过期时不得下单。
6. kill switch 开启时不得下单。
7. live trading 未启用时不得连接真实 broker。
8. provider API key 不得进入日志。
```

### 19.3 未来函数检查

必须测试：

```text
1. 特征只使用当前及过去数据。
2. 信号生成不得使用未来 bar。
3. 回测成交价格不能使用不可获得价格。
4. train / test period 严格分离。
5. rolling features 不得 center 对齐。
```

---

## 20. 风险与合规边界

### 20.1 产品声明

AlphaBrief 应明确声明：

```text
1. 本系统用于研究、模拟交易和个人决策辅助。
2. 系统不提供投资建议。
3. 模型输出可能错误、过时或不完整。
4. 回测结果不代表未来收益。
5. 用户必须自行承担交易风险。
6. 真实交易能力如果未来启用，必须单独授权和审计。
```

### 20.2 模型风险

模型可能：

```text
1. 编造事实
2. 忽略重要风险
3. 对近期新闻理解错误
4. 过度自信
5. 生成不稳定 JSON
6. 对同一问题前后不一致
7. 受 prompt 注入影响
```

系统必须通过以下方式降低风险：

```text
1. 结构化输出校验
2. 多模型交叉验证
3. 引用和数据来源记录
4. 风险反方角色
5. 人工确认
6. 风控硬规则
7. 审计日志
```

### 20.3 Prompt 注入防护

外部新闻、网页、报告、社交内容中可能包含恶意指令。

系统规则：

```text
1. 外部内容一律视为 untrusted data。
2. 外部内容不得改变系统规则。
3. 外部内容不得请求 API key。
4. 外部内容不得触发交易执行。
5. 模型读取外部内容时必须使用安全模板。
6. 任何外部内容生成的 OrderIntent 都必须经过 RiskGate。
```

---

## 21. 模型评测体系

AlphaBrief 不只是接入模型，还要评估模型。

### 21.1 评测维度

```text
1. JSON 有效率
2. schema 通过率
3. 幻觉率
4. 引用准确率
5. 风险识别能力
6. 推理一致性
7. 延迟
8. 成本
9. 中文表达质量
10. 对交易结果的后验贡献
```

### 21.2 模型表现库

每个模型的任务表现应该被记录：

```text
model_id
provider
capability
任务类型
成功率
失败率
平均延迟
平均成本
schema 失败率
人工评分
后验表现
```

### 21.3 模型选择策略

模型路由不应只看“哪个最强”，而应看：

```text
1. 这个任务需要什么能力？
2. 这个任务是否高风险？
3. 是否需要低延迟？
4. 是否需要低成本？
5. 是否需要长上下文？
6. 是否需要中文表达？
7. 是否需要结构化输出稳定？
```

---

## 22. Dashboard 蓝图

Dashboard 应包含：

```text
1. Home
   - 今日 AlphaBrief
   - 关注标的
   - 策略状态
   - 风险提醒

2. Research
   - 市场摘要
   - 标的详情
   - 多模型观点
   - 多空辩论
   - 引用和证据

3. Strategies
   - StrategySpec 列表
   - 策略参数
   - 信号历史
   - 回测入口

4. Backtests
   - 净值曲线
   - 指标
   - 交易列表
   - 样本内 / 样本外
   - 成本分析

5. Paper Trading
   - 仓位
   - 订单
   - 成交
   - 现金
   - 净值

6. Risk
   - RiskDecision
   - limits
   - kill switch
   - blocked orders

7. Models
   - provider 状态
   - 模型调用历史
   - 成本
   - schema 失败率
   - 模型表现对比

8. Review
   - 每日复盘
   - 每周复盘
   - 策略复盘
   - 失败案例
```

---

## 23. AlphaBrief 日报格式

```markdown
# AlphaBrief Daily Report

Date: 2026-01-01
Universe: BTC-USD, ETH-USD, SPY, QQQ, NVDA

## 1. Market Regime
- Trend:
- Volatility:
- Liquidity:
- Risk appetite:

## 2. Watchlist
| Symbol | View | Confidence | Reason | Risk |
|---|---|---:|---|---|

## 3. Multi-Model Consensus
- Agreement:
- Disagreement:
- Key uncertainty:

## 4. Strategy Signals
| Strategy | Symbol | Signal | Confidence | Backtest Status |
|---|---|---|---:|---|

## 5. Risk Officer Notes
- Blocked ideas:
- Position concerns:
- Data quality concerns:

## 6. Paper Trading Summary
- Portfolio value:
- Daily PnL:
- Open positions:
- New orders:

## 7. Review Questions
- What changed today?
- Which thesis was invalidated?
- What should be tested next?
```

---

## 24. AlphaBrief 的长期护城河

AlphaBrief 的长期价值不在于接入了多少模型，而在于：

```text
1. 自有研究流程
2. 自有策略规格体系
3. 自有回测标准
4. 自有风险体系
5. 自有审计日志
6. 自有模型评测数据
7. 自有交易复盘知识库
8. 自有 paper trading 后验表现
```

模型是可替换的，数据和复盘体系才是资产。

---

## 25. 最终验收标准

AlphaBrief MVP 完成时，必须做到：

```text
1. 可以导入市场数据。
2. 可以运行至少一个策略回测。
3. 回测包含成本、滑点、风险指标。
4. 可以通过 ModelGateway 调用至少一个模型 provider。
5. 模型输出必须结构化并可验证。
6. 可以生成 Daily AlphaBrief。
7. 可以生成 OrderIntent。
8. OrderIntent 必须经过 RiskGate。
9. 可以完成 paper trading 模拟订单和成交。
10. 所有关键行为都有 audit log。
11. live trading 默认关闭。
12. 没有任何模块直接复制参考项目代码。
13. 测试通过。
14. 类型检查通过。
15. README 和项目规则完整。
```

---

## 26. 贯穿整个项目的最终原则

```text
研究优先，不是交易优先。
模拟优先，不是真实资金优先。
风控优先，不是收益曲线优先。
结构化输出优先，不是自由文本优先。
多模型可替换，不绑定单一厂商。
审计优先，不是黑箱自动化优先。
自有实现优先，不复制参考项目代码。
长期复盘优先，不追求短期 demo。
```

AlphaBrief 的最终目标是成为一个可长期迭代的个人 AI 量化研究系统：

> **它不替用户赌博，而是帮助用户把交易研究变成一套可验证、可审计、可复盘、可持续优化的工程系统。**
