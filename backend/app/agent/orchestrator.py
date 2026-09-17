"""
Agent 编排器 — 按 SPEC 4.2 节流程协调完整的数据查询链路。

流程:
  意图识别 → Schema Linking → Few-Shot 检索 → Prompt 组装
    → LLM 生成 SQL → 安全护栏 → RLS 注入 → SQL 执行
    → 白话解释 → 结果持久化 → SSE 事件流输出

暴露 ``execute()`` 异步生成器，每步 yield SSE 兼容事件字典。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.few_shot import FewShotRetriever
from app.agent.loop import AgentLoop
from app.agent.prompt_builder import PromptBuilder
from app.agent.schema_link import SchemaLinker
from app.db.engine import async_session_factory
from app.db.executor import TargetDBExecutor
from app.db.models import QueryHistory, QueryStatus, Session
from app.llm.explainer import Explainer
from app.security.guard import SQLGuard
from app.security.rls import RowLevelSecurity


# ─── SSE 事件辅助 ─────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> dict:
    """构造 SSE 事件字典（兼容 sse-starlette EventSourceResponse）。"""
    return {"event": event, "data": data}


# ─── 意图检查 ─────────────────────────────────────────────────────────────────

# 简单启发式：检测是否包含数据查询相关关键词
_QUERY_INTENT_KEYWORDS = [
    # ── 已有关键词 ──
    "查询", "统计", "多少", "几个", "列表", "数据", "总数", "合计",
    "平均", "最大", "最小", "哪个", "哪些", "排名", "占比", "分布",
    "比", "率", "趋势", "增长", "减少", "变化",
    "select", "count", "sum", "avg", "group", "order", "where",
    "how many", "how much", "what is", "list", "show", "get",
    "total", "average", "top", "汇总", "明细",
    # ── 补充中文自然查询 ──
    "最多", "最少", "最好", "最差",     # 最高级（排名/Top-N）
    "消费", "金额", "花费", "花钱",     # 金额相关（隐含数据查询）
    "用户", "客户", "订单", "商品",     # 业务实体（常见查询对象）
    "挑选", "找出", "列出", "显示",     # 查询动作
    "看看", "告诉我", "给我",           # 口语查询
    "每个", "各个", "按", "分",        # 分组/聚合
    "销售额", "利润", "收入",           # 业务指标
    "上个月", "本月", "今年", "昨天",   # 时间相关
    "对比", "比较", "不同",             # 对比分析
    # ── 简短查询 / 中英混合 ──
    "查", "帮我查", "查一下",           # "查" 的常见变体
    "表", "table",                     # 数据表相关
    "user", "users", "order", "orders",# 常见英文实体
    "帮我", "帮我查", "我想",          # 常见口语前缀
    "有几", "有没有", "是否存在",       # 存在性查询
    "最近", "最新", "最后",             # 时序查询
]


def _is_data_query(question: str) -> bool:
    """快速判断用户问题是否为数据查询意图。

    使用关键词匹配做轻量级分类，准确率不足时可由 LLM 替代。
    """
    q = question.strip()
    if not q:
        return False

    # 长度 > 50 字的问题几乎不可能是非数据查询
    if len(q) <= 2:
        return False

    q_lower = q.lower()
    return any(kw in q_lower for kw in _QUERY_INTENT_KEYWORDS)


# ─── 编排器 ───────────────────────────────────────────────────────────────────

class QueryOrchestrator:
    """智能查询编排器。

    协调 Schema Linking → Agent 推理 → 安全检查 → SQL 执行
    → 结果解释的全流程，以 SSE 事件流形式返回。
    """

    MAX_RETRIES: int = 1          # 重试 1 次（共 2 次尝试）
    AGENT_TIMEOUT_SECONDS: int = 30

    def __init__(self) -> None:
        # ── 核心组件 ──
        self.schema_linker = SchemaLinker()
        self.few_shot = FewShotRetriever()
        self.prompt_builder = PromptBuilder()
        self.sql_executor = TargetDBExecutor()
        self.explainer = Explainer()
        self.guard = SQLGuard()
        self.rls = RowLevelSecurity()

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def execute(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行完整的数据查询链路，逐个 yield SSE 事件。

        Args:
            question:   用户自然语言问题。
            session_id: 当前对话会话 ID（为 ``None`` 时自动创建）。
            user_id:    登录用户 ID（用于 RLS 策略匹配）。

        Yields:
            SSE 事件字典，包含 ``event`` 和 ``data`` 键。
        """
        # ==================================================================
        # 0. 初始化会话
        # ==================================================================
        async with async_session_factory() as meta_session:
            try:
                sid = await self._ensure_session(meta_session, session_id, question, user_id)

                # ==========================================================
                # 1. 意图识别
                # ==========================================================
                yield _sse("status", {"state": "thinking", "message": "正在理解语义..."})

                if not _is_data_query(question):
                    yield _sse("error", {
                        "status": "rejected",
                        "message": "未识别到数据查询意图，请指定您要分析的数据指标（如销售额、用户数等）。",
                        "session_id": sid,
                    })
                    return

                # ==========================================================
                # 2. Schema Linking
                # ==========================================================
                yield _sse("status", {
                    "state": "schema_linking",
                    "message": "正在检索表结构...",
                })
                schemas = await self.schema_linker.retrieve(question, top_k=5)

                # ==========================================================
                # 3. Few-Shot 检索
                # ==========================================================
                few_shots = await self.few_shot.retrieve(question, top_k=2)

                # ==========================================================
                # 4. 获取对话历史（最近 2 轮）
                # ==========================================================
                history = await self._get_recent_history(meta_session, sid, last=2)

                # ==========================================================
                # 5. 组装 Prompt
                # ==========================================================
                rls_policy = self.rls.policies.get(user_id) if user_id else None
                system_prompt = self.prompt_builder.build(
                    schemas=schemas,
                    few_shots=few_shots,
                    history=history,
                    rls_policy=rls_policy,
                )

                # ==========================================================
                # 6. 创建 SQL 生成循环
                # ==========================================================
                agent_loop = AgentLoop(
                    max_execution_time=self.AGENT_TIMEOUT_SECONDS,
                )

                # ==========================================================
                # 7. 生成 → 校验 → 执行（失败则回灌错误重试）
                # ==========================================================
                last_error: Optional[str] = None
                final_sql: Optional[str] = None
                final_raw_output: str = ""

                for attempt in range(self.MAX_RETRIES + 1):
                    if attempt > 0:
                        yield _sse("status", {
                            "state": "retrying",
                            "message": f"正在重新尝试...（第 {attempt + 1}/{self.MAX_RETRIES + 1} 次）",
                        })
                        # 将上次的错误追加到 system_prompt 尾部
                        system_prompt += (
                            f"\n\n[上次执行错误]\n{last_error}\n"
                            "请根据错误信息修正 SQL 后重新生成。"
                        )
                    else:
                        yield _sse("status", {
                            "state": "executing",
                            "message": "正在执行查询...",
                        })

                    # ── 7a. 执行 Agent ──
                    agent_result = await agent_loop.run(
                        system_prompt=system_prompt,
                        question=question,
                    )

                    if not agent_result["success"]:
                        last_error = agent_result.get("error", "未知错误")
                        final_raw_output = agent_result.get("raw_output", "")
                        # 还有重试次数时继续循环
                        if attempt < self.MAX_RETRIES:
                            continue
                        # 所有重试耗尽
                        yield _sse("error", {
                            "status": "failed",
                            "message": f"查询失败：{last_error}。建议简化条件或联系 DBA 协助。",
                            "session_id": sid,
                        })
                        await self._save_history_failed(
                            meta_session, sid, question,
                            final_sql or "", last_error,
                            retry_count=attempt,
                        )
                        return

                    final_sql = agent_result["sql"]
                    final_raw_output = agent_result.get("raw_output", "")

                    # ── 7b. 安全护栏 ──
                    dangerous, reason = self.guard.inspect(final_sql)
                    if dangerous:
                        yield _sse("error", {
                            "status": "blocked",
                            "message": reason,
                            "session_id": sid,
                        })
                        await self._save_history_blocked(
                            meta_session, sid, question, final_sql, reason,
                            retry_count=attempt,
                        )
                        return

                    # ── 7c. RLS 注入 ──
                    safe_sql = self.rls.inject(final_sql, user_id)

                    # ── 7d. SQL 执行 ──
                    try:
                        result = await self.sql_executor.execute(safe_sql)
                    except Exception as e:
                        last_error = f"SQL 执行错误: {e!s}"
                        if attempt < self.MAX_RETRIES:
                            continue
                        # 最后一次尝试也失败
                        yield _sse("error", {
                            "status": "failed",
                            "message": f"当前查询较复杂，建议简化条件或联系 DBA 协助。",
                            "session_id": sid,
                        })
                        await self._save_history_failed(
                            meta_session, sid, question, safe_sql,
                            last_error, retry_count=attempt,
                        )
                        return

                    # ── 成功 ──
                    # 8. 白话解释
                    try:
                        explanation = await self.explainer.generate(question, safe_sql)
                    except Exception:
                        explanation = f"我理解您的需求是：查询 {question} 相关数据。"

                    # 9. 保存历史
                    await self._save_history_success(
                        meta_session, sid, question, final_sql, safe_sql,
                        explanation, result, retry_count=attempt,
                    )

                    # 10. 返回结果
                    yield _sse("result", {
                        "status": "success",
                        "session_id": sid,
                        "sql": final_sql,
                        "explanation": explanation,
                        "columns": result["columns"],
                        "rows": result["rows"],
                        "total_count": result["total_count"],
                        "execution_ms": result["execution_ms"],
                    })
                    return

            finally:
                # 确保会话关闭
                await meta_session.close()

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _ensure_session(
        session: AsyncSession,
        sid: Optional[str],
        question: str,
        user_id: Optional[str],
    ) -> str:
        """获取或创建会话记录。

        Args:
            session:  元数据库会话。
            sid:      现有会话 ID（可空）。
            question: 当前问题（用于自动命名新会话）。
            user_id:  用户 ID。

        Returns:
            最终使用的会话 ID。
        """
        if sid:
            # 验证会话存在
            existing = await session.get(Session, sid)
            if existing:
                return sid

        # 创建新会话
        new_session = Session(
            id=str(uuid.uuid4()),
            title=question[:50] + ("…" if len(question) > 50 else ""),
            user_id=user_id or "anonymous",
        )
        session.add(new_session)
        await session.commit()
        return str(new_session.id)

    @staticmethod
    async def _get_recent_history(
        session: AsyncSession,
        session_id: str,
        last: int = 2,
    ) -> list[dict]:
        """获取某会话最近 N 条成功的历史记录。

        Returns:
            [{"user_question": "...", "generated_sql": "..."}, ...]
        """
        stmt = (
            select(QueryHistory)
            .where(
                QueryHistory.session_id == session_id,
                QueryHistory.status == QueryStatus.SUCCESS,
            )
            .order_by(QueryHistory.created_at.desc())
            .limit(last)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        return [
            {"user_question": h.user_question, "generated_sql": h.generated_sql}
            for h in reversed(rows)
        ]

    # ── 历史记录持久化 ─────────────────────────────────────────────────────

    @staticmethod
    async def _save_history_success(
        session: AsyncSession,
        session_id: str,
        question: str,
        generated_sql: str,
        executed_sql: str,
        explanation: str,
        result: dict,
        retry_count: int = 0,
    ) -> None:
        """保存成功的查询历史。"""
        record = QueryHistory(
            session_id=session_id,
            user_question=question,
            generated_sql=generated_sql,
            executed_sql=executed_sql,
            explanation=explanation,
            result_columns=result.get("columns", []),
            result_rows=result.get("rows", []),
            total_count=result.get("total_count", 0),
            status=QueryStatus.SUCCESS,
            execution_ms=result.get("execution_ms", 0),
            retry_count=retry_count,
        )
        session.add(record)
        await session.commit()

    @staticmethod
    async def _save_history_failed(
        session: AsyncSession,
        session_id: str,
        question: str,
        sql: str,
        error_msg: str,
        retry_count: int = 0,
    ) -> None:
        """保存失败的查询历史。"""
        record = QueryHistory(
            session_id=session_id,
            user_question=question,
            generated_sql=sql,
            executed_sql=sql,
            status=QueryStatus.FAILED,
            error_message=error_msg,
            retry_count=retry_count,
        )
        session.add(record)
        await session.commit()

    @staticmethod
    async def _save_history_blocked(
        session: AsyncSession,
        session_id: str,
        question: str,
        sql: str,
        reason: str,
        retry_count: int = 0,
    ) -> None:
        """保存被安全护栏拦截的查询历史。"""
        record = QueryHistory(
            session_id=session_id,
            user_question=question,
            generated_sql=sql,
            executed_sql=sql,
            status=QueryStatus.BLOCKED,
            error_message=reason,
            retry_count=retry_count,
        )
        session.add(record)
        await session.commit()
