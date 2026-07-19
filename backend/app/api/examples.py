"""
黄金示例管理接口 — 列表 / 创建 / 删除。

管理 ``golden_examples`` 表中的高质量问题-SQL 对，
同时保持 Chroma 向量库中的 embedding 同步。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import GoldenExample
from app.vector_store.chroma_client import (
    GOLDEN_EXAMPLES,
    add_document,
    delete_document,
    get_golden_examples_collection,
)
from app.vector_store.embedder import embed_text


router = APIRouter(tags=["examples"])


# ─── 请求 / 响应模型 ───────────────────────────────────────────────────────────

class CreateExampleRequest(BaseModel):
    """创建黄金示例的请求体。"""
    question: str = Field(..., min_length=1, max_length=2000, description="自然语言问题")
    sql: str = Field(..., min_length=1, description="标准 SQL 答案")
    tables_used: list[str] = Field(default=[], description="涉及的表名列表")
    tags: list[str] = Field(default=[], description="标签列表")
    reviewed_by: Optional[str] = Field(None, description="审核人")

    model_config = {"json_schema_extra": {
        "example": {
            "question": "查询过去7天注册的用户数",
            "sql": "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL 7 DAY",
            "tables_used": ["users"],
            "tags": ["聚合", "时间范围"],
            "reviewed_by": "dba_li",
        }
    }}


class ExampleResponse(BaseModel):
    """黄金示例的响应模型。"""
    id: str
    question: str
    sql: str
    tables_used: list[str]
    tags: list[str]
    reviewed_by: Optional[str] = None
    usage_count: int = 0
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── 辅助 ───────────────────────────────────────────────────────────────────────

def _example_to_dict(ex: GoldenExample) -> dict[str, Any]:
    """将 ORM 模型转为响应字典。"""
    return {
        "id": ex.id,
        "question": ex.question,
        "sql": ex.sql,
        "tables_used": ex.tables_used or [],
        "tags": ex.tags or [],
        "reviewed_by": ex.reviewed_by,
        "usage_count": ex.usage_count,
        "created_at": ex.created_at.isoformat() if ex.created_at else None,
    }


# ─── GET /examples — 列表 ─────────────────────────────────────────────────────

@router.get("/examples", response_model=None)
async def list_examples(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    tag: Optional[str] = Query(None, description="按标签筛选"),
    db: AsyncSession = Depends(get_db_session),
):
    """获取黄金示例列表，支持分页和按标签筛选。"""
    # 构建查询
    base_query = select(GoldenExample)

    if tag:
        # 使用 JSON_CONTAINS 或简单 LIKE 匹配
        base_query = base_query.where(
            GoldenExample.tags.astext.contains(tag)
        )

    # 总数
    count_q = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # 分页
    stmt = (
        base_query
        .order_by(GoldenExample.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    examples = result.scalars().all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "examples": [_example_to_dict(ex) for ex in examples],
    }


# ─── POST /examples — 创建 ───────────────────────────────────────────────────

@router.post("/examples", status_code=201, response_model=None)
async def create_example(
    body: CreateExampleRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """创建一条新的黄金示例，并同步写入 Chroma 向量库。"""
    # 1. 计算 embedding
    try:
        embedding = await embed_text(body.question)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Embedding 计算失败: {e!s}",
        )

    # 2. 写入 meta DB
    example = GoldenExample(
        question=body.question,
        sql=body.sql,
        tables_used=body.tables_used or [],
        tags=body.tags or [],
        reviewed_by=body.reviewed_by,
    )
    db.add(example)
    await db.flush()  # 获得 ID 但不 commit

    # 3. 写入 Chroma
    try:
        collection = get_golden_examples_collection()
        await add_document(
            collection=collection,
            document=body.question,  # 仅存问题文本（FewShotRetriever 以此作为 question 字段）
            embedding=embedding,
            doc_id=str(example.id),
            metadata={
                "sql": body.sql,                   # FewShotRetriever 从 metadata 取 sql
                "tables": ",".join(body.tables_used or []),
                "tags": ",".join(body.tags or []),
            },
        )
        example.embedding_id = str(example.id)
    except Exception as e:
        # Chroma 写入失败不阻止入库，仅打日志
        print(f"[WARN] Chroma 写入失败: {e!s}")

    await db.commit()
    await db.refresh(example)

    return _example_to_dict(example)


# ─── DELETE /examples/{id} — 删除 ────────────────────────────────────────────

@router.delete("/examples/{example_id}")
async def delete_example(
    example_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """删除指定黄金示例，同时清理 Chroma 中的对应向量。"""
    example = await db.get(GoldenExample, example_id)
    if not example:
        raise HTTPException(status_code=404, detail=f"示例 {example_id} 不存在")

    # 1. 删除 Chroma 向量
    if example.embedding_id:
        try:
            collection = get_golden_examples_collection()
            await delete_document(collection, example.embedding_id)
        except Exception as e:
            print(f"[WARN] Chroma 删除失败: {e!s}")

    # 2. 删除数据库记录
    await db.delete(example)
    await db.commit()

    return {"message": f"示例 {example_id} 已删除", "example_id": example_id}
