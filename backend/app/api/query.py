"""
查询接口 — POST /api/v1/query

接收自然语言查询请求，以 SSE (Server-Sent Events) 流式返回
Agent 的推理中间状态和最终结果。
"""

from __future__ import annotations

import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.agent.orchestrator import QueryOrchestrator


router = APIRouter(tags=["query"])


# ─── 请求模型 ─────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """自然语言查询请求体。"""
    question: str = Field(..., min_length=1, max_length=2000, description="用户自然语言问题")
    session_id: Optional[str] = Field(None, description="会话 ID（不传则自动创建新会话）")
    user_id: Optional[str] = Field(None, description="登录用户 ID（用于 RLS）")

    model_config = {"json_schema_extra": {
        "example": {
            "question": "查询7月1日到7月18日注册的用户数量",
            "session_id": None,
            "user_id": "user_north",
        }
    }}


# ─── SSE 事件格式化 ──────────────────────────────────────────────────────────

def _format_sse(event: str, data: object) -> str:
    """将事件名与数据格式化为 SSE 协议文本。

    SSE 格式::

        event: {event}
        data: {json}\n\n
    """
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def _event_stream(
    events: AsyncGenerator[dict, None],
) -> AsyncGenerator[str, None]:
    """将 Orchestrator 的 dict 事件流转换为 SSE 文本流。

    Args:
        events: Orchestrator 输出的异步事件生成器。

    Yields:
        SSE 格式文本行，可直接写入 StreamingResponse。
    """
    try:
        async for event in events:
            yield _format_sse(event["event"], event["data"])
    except Exception as exc:
        # Orchestrator 内部未捕获的异常 → 发送 error 事件后关闭流
        yield _format_sse("error", {
            "status": "failed",
            "message": f"系统内部错误: {exc!s}",
        })


# ─── 路由 ─────────────────────────────────────────────────────────────────────

@router.post("/query")
async def handle_query(body: QueryRequest, request: Request):
    """提交自然语言查询，以 SSE 流式返回结果。

    事件序列::

        event: status       → 中间状态（thinking / schema_linking / executing / retrying）
        event: result       → 查询成功（含 sql / explanation / columns / rows）
        event: error        → 查询失败或拦截（含 status + message）
    """
    orchestrator = QueryOrchestrator()

    events = orchestrator.execute(
        question=body.question,
        session_id=body.session_id,
        user_id=body.user_id,
    )

    return StreamingResponse(
        _event_stream(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",                # 禁用 Nginx 缓冲
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
