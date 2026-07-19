"""
Agent 编排器集成测试 — Mock LLM 返回固定 SQL，验证全链路。

覆盖场景：
1. 正常查询流程（意图识别 → schema linking → 生成 → 执行 → 解释）
2. SQL Guard 拦截（DDL / 危险操作）
3. RLS 权限注入
4. 非数据查询意图拒绝
5. Agent 重试耗尽后报错

运行方式::

    cd backend
    pytest tests/test_agent_loop.py -v --asyncio-mode=auto
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.orchestrator import QueryOrchestrator


# ============================================================
# 1. 正常查询全链路
# ============================================================

@pytest.mark.asyncio
async def test_full_query_success(
    mock_schema_linker,
    mock_few_shot,
    mock_agent_loop,
    mock_executor,
    mock_explainer,
    mock_vector_store,
):
    """
    验证完整查询链路：
    - 意图识别通过
    - Schema Linking 检索到 2 张表
    - Agent 生成 SQL 并通过 Guard / RLS
    - SQL 执行成功返回结果
    - 中文解释生成成功
    """
    orch = QueryOrchestrator()
    events = [e async for e in orch.execute(question="查询7月注册的用户数", user_id="user_north")]

    # 事件序列校验
    event_types = [e["event"] for e in events]
    assert "status" in event_types, "应有 status 事件"
    assert "result" in event_types, "应有 result 事件"

    # 提取 result 事件
    result_event = next(e for e in events if e["event"] == "result")
    data = result_event["data"]

    assert data["status"] == "success"
    assert "SELECT" in data["sql"]
    assert data["explanation"] == "我理解您的需求是：统计2026年7月后注册的用户总数。"
    assert data["columns"] == ["COUNT(*)"]
    assert data["rows"] == [[42]]
    assert data["total_count"] == 1
    assert data["execution_ms"] == 15
    assert "session_id" in data


# ============================================================
# 2. 非数据查询意图拒绝
# ============================================================

@pytest.mark.asyncio
async def test_non_query_intent_rejected(
    mock_agent_loop,
    mock_vector_store,
):
    """验证非数据查询（如问候）被意图识别拦截。"""
    orch = QueryOrchestrator()
    events = [e async for e in orch.execute(question="你好，今天天气不错")]

    # 应当收到 error 事件而非 result
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "未识别到数据查询意图" in error_events[0]["data"]["message"]

    # 不应有 result 事件
    assert not any(e["event"] == "result" for e in events)


# ============================================================
# 3. 短问题（≤2 字）被拒绝
# ============================================================

@pytest.mark.asyncio
async def test_very_short_question_rejected(mock_agent_loop):
    """验证过短的问题被意图识别拦截。"""
    orch = QueryOrchestrator()
    events = [e async for e in orch.execute(question="hi")]

    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "未识别到数据查询意图" in error_events[0]["data"]["message"]


# ============================================================
# 4. SQL Guard 拦截（DML / DDL）
# ============================================================

@pytest.mark.asyncio
async def test_dangerous_sql_blocked_by_guard(
    mock_schema_linker,
    mock_few_shot,
    mock_vector_store,
):
    """
    验证 Agent 生成 DDL/DML 语句时被 SQL Guard 拦截。
    通过 mock Agent 返回 DROP TABLE 来触发。
    """
    with patch("app.agent.orchestrator.AgentLoop") as mock:
        instance = mock.return_value
        instance.run = AsyncMock(return_value={
            "sql": "DROP TABLE users",
            "raw_output": "```sql\nDROP TABLE users\n```",
            "success": True,
            "error": None,
        })

        orch = QueryOrchestrator()
        events = [e async for e in orch.execute(question="删除用户表")]

        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["status"] == "blocked"
        assert any(kw in error_events[0]["data"]["message"] for kw in ["DROP", "不允许", "禁止"])


# ============================================================
# 5. Agent 重试耗尽后返回 failed
# ============================================================

@pytest.mark.asyncio
async def test_agent_retries_exhausted(
    mock_schema_linker,
    mock_few_shot,
    mock_executor,
    mock_vector_store,
):
    """
    验证 Agent 在所有重试（MAX_RETRIES + 1 = 3 次）耗尽后
    返回 failed 事件而非阻塞。
    """
    with patch("app.agent.orchestrator.AgentLoop") as mock:
        instance = mock.return_value
        # Agent 每次都失败（SQL 提取失败）
        instance.run = AsyncMock(return_value={
            "sql": None,
            "raw_output": "I don't know how to do this.",
            "success": False,
            "error": "Agent 未生成有效的 SQL 代码块",
        })

        orch = QueryOrchestrator()
        events = [e async for e in orch.execute(question="非常复杂的数据查询")]

        # 应有 retrying 事件
        status_events = [e for e in events if e["event"] == "status"]
        retry_events = [s for s in status_events if s["data"]["state"] == "retrying"]
        assert len(retry_events) >= 1, f"应有 retry 事件，实际: {len(retry_events)}"

        # 最终应为 error (failed)
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert error_events[0]["data"]["status"] == "failed"


# ============================================================
# 6. SQL 执行失败 + Agent 重试
# ============================================================

@pytest.mark.asyncio
async def test_sql_execution_failure_triggers_retry(
    mock_schema_linker,
    mock_few_shot,
    mock_agent_loop,
    mock_vector_store,
):
    """
    验证 SQL 执行阶段抛出异常时，Orchestrator 触发重试。
    前 2 次执行失败，第 3 次成功。
    """
    call_count = 0

    async def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("数据库连接超时")
        return {
            "columns": ["COUNT(*)"],
            "rows": [[100]],
            "total_count": 1,
            "execution_ms": 20,
        }

    with patch("app.agent.orchestrator.TargetDBExecutor") as mock:
        instance = mock.return_value
        instance.execute = AsyncMock(side_effect=execute_side_effect)

        orch = QueryOrchestrator()
        events = [e async for e in orch.execute(question="查询用户总数")]

        # 第 3 次应成功
        result_events = [e for e in events if e["event"] == "result"]
        assert len(result_events) == 1
        assert result_events[0]["data"]["rows"] == [[100]]
        assert call_count == 3


# ============================================================
# 7. 事件顺序校验
# ============================================================

@pytest.mark.asyncio
async def test_event_order(
    mock_schema_linker,
    mock_few_shot,
    mock_agent_loop,
    mock_executor,
    mock_explainer,
    mock_vector_store,
):
    """验证 SSE 事件按预期顺序发射。"""
    orch = QueryOrchestrator()
    events = [e async for e in orch.execute(question="查询用户数")]

    expected_order = [e["event"] for e in events]

    # status (thinking) → status (schema_linking) → status (executing) → result
    assert expected_order[0:4] == ["status", "status", "status", "result"], (
        f"事件顺序异常: {expected_order}"
    )


# ============================================================
# 8. Session 创建
# ============================================================

@pytest.mark.asyncio
async def test_session_created_when_no_session_id(
    mock_schema_linker,
    mock_few_shot,
    mock_agent_loop,
    mock_executor,
    mock_explainer,
    mock_vector_store,
):
    """验证未传入 session_id 时，Orchestrator 自动创建新会话。"""
    orch = QueryOrchestrator()
    events = [e async for e in orch.execute(
        question="查询7月注册用户数",
        user_id="test_user",
    )]

    result_event = next(e for e in events if e["event"] == "result")
    session_id = result_event["data"].get("session_id")
    assert session_id is not None
    assert len(session_id) > 0, "session_id 不应为空"


# ============================================================
# 9. RLS 策略正常注入（不产生副作用）
# ============================================================

@pytest.mark.asyncio
async def test_rls_policy_applied(
    mock_schema_linker,
    mock_few_shot,
    mock_vector_store,
):
    """
    验证 RLS 用户执行查询时，最终 SQL 中包含权限条件。
    我们 mock Agent 返回一个简单 SELECT，然后校验注入后的 SQL。
    """
    from app.security.rls import RowLevelSecurity

    injected_sql = []

    async def execute_with_tracking(sql: str) -> dict:
        injected_sql.append(sql)
        return {
            "columns": ["COUNT(*)"],
            "rows": [[42]],
            "total_count": 1,
            "execution_ms": 10,
        }

    with (
        patch("app.agent.orchestrator.AgentLoop") as mock_loop,
        patch("app.agent.orchestrator.TargetDBExecutor") as mock_exec,
    ):
        mock_loop_instance = mock_loop.return_value
        mock_loop_instance.run = AsyncMock(return_value={
            "sql": "SELECT COUNT(*) FROM orders",
            "raw_output": "```sql\nSELECT COUNT(*) FROM orders\n```",
            "success": True,
            "error": None,
        })

        mock_exec_instance = mock_exec.return_value
        mock_exec_instance.execute = AsyncMock(side_effect=execute_with_tracking)

        orch = QueryOrchestrator()
        events = [e async for e in orch.execute(
            question="查询订单总数",
            user_id="analyst_beijing",
        )]

        # 确认 result 事件
        assert any(e["event"] == "result" for e in events)

    # 检查 RLS 注入 — 最终执行的 SQL 包含 Beijing 条件
    assert len(injected_sql) == 1
    executed = injected_sql[0].lower()
    assert "beijing" in executed or "city" in executed, (
        f"RLS 注入失效，实际 SQL: {injected_sql[0]}"
    )


# ============================================================
# 10. SQL 提取工具测试
# ============================================================

class TestExtractSQL:
    """测试 ``AgentLoop.extract_sql`` 的正则提取逻辑。"""

    @pytest.mark.parametrize("text, expected", [
        (
            "I will write SQL.\n```sql\nSELECT * FROM users\n```\nDone.",
            "SELECT * FROM users",
        ),
        (
            "```sql\nSELECT COUNT(*) FROM orders WHERE status = 'active'\n```",
            "SELECT COUNT(*) FROM orders WHERE status = 'active'",
        ),
        (
            "No code block here.",
            None,
        ),
        (
            "```sql\nSELECT 1\n``````sql\nSELECT 2\n```",
            "SELECT 1",
        ),
        (
            "```\nSELECT * FROM users\n```",
            None,
        ),
    ])
    def test_extract_sql(self, text, expected):
        """验证各种格式的 SQL 代码块提取。"""
        from app.agent.loop import extract_sql
        assert extract_sql(text) == expected


# ============================================================
# 11. 意图检测工具测试
# ============================================================

class TestIsDataQuery:
    """测试 ``_is_data_query`` 意图检测逻辑。"""

    @pytest.mark.parametrize("question, expected", [
        ("查询用户总数", True),
        ("统计7月销售额", True),
        ("显示订单列表", True),
        ("hello world", False),
        ("你好", False),
        ("hi", False),
        ("", False),
        ("SELECT * FROM users", True),
    ])
    def test_is_data_query(self, question, expected):
        """验证关键词匹配的意图判断。"""
        from app.agent.orchestrator import _is_data_query
        assert _is_data_query(question) == expected
