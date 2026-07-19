"""
会话管理接口 — 会话列表 / 详情 / 删除。

从系统元数据库（meta DB）中读写 ``sessions`` 和 ``query_history`` 表。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import QueryHistory, Session


router = APIRouter(tags=["sessions"])


# ─── 辅助工具 ─────────────────────────────────────────────────────────────────

async def _get_session_or_404(
    session_id: str,
    db: AsyncSession,
) -> Session:
    """按 ID 查找会话，不存在时抛出 404。"""
    sess = await db.get(Session, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    return sess


# ─── GET /sessions — 会话列表 ────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db_session),
):
    """获取所有会话的列表，按更新时间倒序。

    每条会话包含其名称、时间戳和查询次数。
    """
    # 获取总数
    count_result = await db.execute(select(func.count(Session.id)))
    total = count_result.scalar_one()

    # 分页查询
    stmt = (
        select(Session)
        .order_by(Session.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "user_id": s.user_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ],
    }


# ─── GET /sessions/{id} — 会话详情（含查询历史）──────────────────────────────

@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """获取单个会话的详情，包括其所有查询历史。"""
    session = await _get_session_or_404(session_id, db)

    # 查询该会话下的历史记录
    history_stmt = (
        select(QueryHistory)
        .where(QueryHistory.session_id == session_id)
        .order_by(QueryHistory.created_at.desc())
        .limit(50)
    )
    result = await db.execute(history_stmt)
    records = result.scalars().all()

    return {
        "id": session.id,
        "title": session.title,
        "user_id": session.user_id,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "history_count": len(records),
        "history": [
            {
                "id": r.id,
                "question": r.user_question,
                "sql": r.generated_sql,
                "executed_sql": r.executed_sql,
                "explanation": r.explanation,
                "status": r.status.value if r.status else None,
                "error_message": r.error_message,
                "execution_ms": r.execution_ms,
                "retry_count": r.retry_count,
                "result_columns": (r.result_columns or [])[:10],
                "result_rows": (r.result_rows or [])[:10],
                "total_count": r.total_count,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ],
    }


# ─── DELETE /sessions/{id} — 删除会话 ────────────────────────────────────────

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """删除指定会话及其所有查询历史（CASCADE）。"""
    session = await _get_session_or_404(session_id, db)
    await db.delete(session)
    await db.commit()
    return {"message": f"会话 {session_id} 已删除", "session_id": session_id}
