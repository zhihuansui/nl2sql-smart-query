"""
表元数据接口 — GET /tables、GET /tables/{name} 和 GET /tables/{name}/rows。

通过 MetadataScanner 从目标业务数据库的 information_schema
反射表结构和列信息。支持 MySQL / PostgreSQL / SQLite。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.executor import TargetDBExecutor
from app.db.metadata import MetadataScanner


router = APIRouter(tags=["tables"])

_MAX_PREVIEW_ROWS = 1000
"""预览数据时单次返回的最大行数"""


# ─── GET /tables — 所有表概览 ────────────────────────────────────────────────

@router.get("/tables")
async def list_tables():
    """获取目标数据库中所有用户表的概览信息。

    返回表名、注释、近似行数、列数。
    """
    scanner = MetadataScanner()
    try:
        tables = await scanner.get_all_tables()
        return {"total": len(tables), "tables": tables}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法读取目标数据库元数据: {e!s}",
        )
    finally:
        await scanner.close()


# ─── GET /tables/{name} — 单表列详情 ─────────────────────────────────────────

@router.get("/tables/{table_name}")
async def get_table_detail(table_name: str):
    """获取指定表的完整列定义。

    返回字段名、数据类型、是否可空、注释、是否为主键。
    """
    scanner = MetadataScanner()
    try:
        columns = await scanner.get_table_columns(table_name)
        if not columns:
            raise HTTPException(
                status_code=404,
                detail=f"表「{table_name}」不存在或无法访问",
            )
        return {
            "table_name": table_name,
            "column_count": len(columns),
            "columns": columns,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法读取表「{table_name}」的元数据: {e!s}",
        )
    finally:
        await scanner.close()


# ─── GET /tables/{name}/rows — 表数据预览 ─────────────────────────────────────

@router.get("/tables/{table_name}/rows")
async def get_table_rows(
    table_name: str,
    limit: int = Query(100, ge=1, le=_MAX_PREVIEW_ROWS, description="返回行数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """预览指定表的数据行。

    先验证表是否存在，再执行只读 SELECT 查询返回数据。
    """
    # 1. 验证表存在
    scanner = MetadataScanner()
    try:
        columns = await scanner.get_table_columns(table_name)
        if not columns:
            raise HTTPException(
                status_code=404,
                detail=f"表「{table_name}」不存在或无法访问",
            )
    finally:
        await scanner.close()

    # 2. 执行只读查询（表名已验证，安全拼接）
    executor = TargetDBExecutor()
    try:
        # MySQL 标识符用反引号，PostgreSQL/SQLite 用双引号
        quote = '`' if settings.TARGET_DB_TYPE.lower() == 'mysql' else '"'
        sql = f'SELECT * FROM {quote}{table_name}{quote} LIMIT {limit} OFFSET {offset}'
        result = await executor.execute(sql)
        return {
            "table_name": table_name,
            "columns": result["columns"],
            "rows": result["rows"],
            "total_count": result["total_count"],
            "execution_ms": result["execution_ms"],
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"读取表数据失败: {e!s}",
        )
    finally:
        await executor.close()
