"""
健康检查接口 — 深度检测各组件连通性。

通过探测元数据库、目标数据库、Chroma 向量库和 LLM 提供商的
连接状态，返回全面的系统健康报告。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db.engine import engine
from app.db.executor import TargetDBExecutor
from app.vector_store.chroma_client import count_documents, get_golden_examples_collection, get_table_schemas_collection


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """系统深度健康检查。

    返回各组件的连通性、延迟和简要统计信息。
    """
    # ── 1. 系统信息 ──
    result = {
        "status": "healthy",
        "version": "1.0.0",
        "app_env": settings.APP_ENV,
        "components": {},
    }

    have_error = False

    # ── 2. 元数据库 ──
    try:
        start = asyncio.get_running_loop().time()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        meta_db_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        result["components"]["meta_db"] = {
            "status": "connected",
            "latency_ms": meta_db_ms,
        }
    except Exception as e:
        have_error = True
        result["components"]["meta_db"] = {
            "status": "disconnected",
            "error": str(e),
        }

    # ── 3. 目标数据库 ──
    executor = TargetDBExecutor()
    try:
        start = asyncio.get_running_loop().time()
        ok = await executor.test_connection()
        target_db_ms = int((asyncio.get_running_loop().time() - start) * 1000)
        result["components"]["target_db"] = {
            "status": "connected" if ok else "unreachable",
            "latency_ms": target_db_ms,
            "type": settings.TARGET_DB_TYPE,
            "host": settings.TARGET_DB_HOST,
            "database": settings.TARGET_DB_NAME,
        }
        if not ok:
            have_error = True
    except Exception as e:
        have_error = True
        result["components"]["target_db"] = {
            "status": "disconnected",
            "error": str(e),
        }
    finally:
        await executor.close()

    # ── 4. Chroma 向量存储 ──
    try:
        schemas_col = get_table_schemas_collection()
        examples_col = get_golden_examples_collection()
        schemas_cnt = await count_documents(schemas_col)
        examples_cnt = await count_documents(examples_col)
        result["components"]["chroma"] = {
            "status": "connected",
            "mode": "http" if settings.CHROMA_HOST else "local",
            "table_schemas_count": schemas_cnt,
            "golden_examples_count": examples_cnt,
        }
    except Exception as e:
        have_error = True
        result["components"]["chroma"] = {
            "status": "disconnected",
            "error": str(e),
        }

    # ── 5. LLM 提供商 ──
    if settings.LLM_API_KEY:
        result["components"]["llm"] = {
            "status": "configured",
            "provider": settings.LLM_PROVIDER,
            "model": settings.LLM_MODEL,
        }
    else:
        have_error = True
        result["components"]["llm"] = {
            "status": "not_configured",
            "provider": settings.LLM_PROVIDER,
            "hint": "请设置 LLM_API_KEY 环境变量",
        }

    # ── 汇总 ──
    if have_error:
        result["status"] = "degraded"

    return result
