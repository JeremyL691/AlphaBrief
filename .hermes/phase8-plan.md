# Phase 8: Multi-Model Research Committee

## 目标
实现多模型研究委员会（Multi-Model Research Committee）——允许用户提一个研究问题，系统自动路由到多个 AI 模型（不同视角），各自独立分析后汇总为结构化共识报告。

## 新增文件

### 1. `packages/alphabrief-research/src/alphabrief_research/schemas.py`
辩论相关 Pydantic 模型：

```python
DebatePerspective = Literal["technical", "fundamental", "risk", "judge"]
ActionType = Literal["buy", "sell", "hold", "watch", "skip"]
ViewType = Literal["bullish", "bearish", "neutral", "uncertain"]

class DebateQuestion(BaseModel):
    question: str
    symbol: str | None = None
    time_horizon: str | None = None
    perspectives: list[str] = ["technical", "fundamental", "risk", "judge"]
    context: str | None = None

class ModelDebateResponse(BaseModel):
    model_name: str
    perspective: str
    analysis: str              # full analysis text
    view: ViewType
    confidence: float           # 0-1
    evidence: list[str]         # key evidence
    risks: list[str]            # key risks
    suggested_action: ActionType
    needs_human_review: bool

class DebateConsensus(BaseModel):
    num_models: int
    agreement_level: Literal["high", "medium", "low", "mixed"]
    consensus_view: ViewType | None
    avg_confidence: float
    view_distribution: dict[str, int]  # {"bullish": 1, "bearish": 2, ...}
    key_evidence: list[str]
    key_risks: list[str]
    disagreements: list[str]
    suggested_action: str
    needs_human_review: bool

class DebateRecord(BaseModel):
    debate_id: str
    question: DebateQuestion
    responses: list[ModelDebateResponse]
    consensus: DebateConsensus
    created_at: datetime
```

### 2. `packages/alphabrief-research/src/alphabrief_research/orchestrator.py`
`DebateOrchestrator` 类，接收 `(gateway: ModelGateway, question: DebateQuestion, registry: ModelRegistry)`：
- 为每个 perspective 生成对应 prompt
- 调用 gateway.invoke()（用 FakeProviderAdapter 可在测试中使用）
- 用 `parse_structured_output()` 解析为 `ModelDebateResponse`
- 汇总所有 response 生成 `DebateConsensus`
- 返回 `DebateRecord`

Prompt 设计：每个 perspective 的 prompt 应引导模型输出可解析的 JSON。

### 3. `apps/api/src/alphabrief_api/db/debates.py`
`DebateStore` 类，模式与 `PaperStore` / `ReviewStore` 相同：
- `save_debate(record: DebateRecord) -> str`
- `get_debate(debate_id: str) -> dict | None`
- `list_debates(limit: int = 10) -> list[dict]`
- `clear()` → `close()`

### 4. `apps/api/src/alphabrief_api/routes/research.py`
API 端点：
- `POST /api/v1/research/debate` — 接收 DebateQuestion，返回 DebateRecord
- `GET /api/v1/research/debate/{debate_id}` — 获取指定辩论记录
- `GET /api/v1/research/debate` — 列出最近的辩论记录

### 5. `apps/cli/src/alphabrief_cli/research_commands.py`
CLI 命令：`alphabrief research debate "question" --symbol NVDA --perspectives technical,fundamental,risk,judge`

## 修改文件

### 6. `apps/api/src/alphabrief_api/db/schema.py`
新增 DDL：
```sql
CREATE TABLE IF NOT EXISTS debate_records (
    id              TEXT PRIMARY KEY,
    question_json   JSON NOT NULL,
    responses_json  JSON NOT NULL,
    consensus_json  JSON NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
```
注册到 `_SCHEMA_STATEMENTS` 和 `drop_schema()`，更新 `__all__`。

### 7. `apps/api/src/alphabrief_api/db/__init__.py`
导出 `DebateStore`。

### 8. `apps/api/src/alphabrief_api/main.py`
注册 research router。

### 9. `apps/cli/src/alphabrief_cli/main.py`
注册 research_app。

### 10. `pyproject.toml`
在 `pythonpath` 和 `packages.find.where` 中添加 `packages/alphabrief-research/src`。

## 测试

### 11. 新测试文件 `tests/test_research.py` 或追加到 `tests/test_db.py`
- Debate schemas 验证测试
- DebateOrchestrator 与 FakeProviderAdapter 的集成测试
- DebateStore DB 测试
- API 端点测试（追加到 `tests/test_api_server.py`）
- CLI 测试（验证命令注册，可暂不测试完整路径）

## 质量门
- `pytest` 全通过
- `ruff check .` 通过
- `mypy apps/api/src tests` 全通过（如果有 mypy 问题，可用 `type: ignore` 加注释解决）
