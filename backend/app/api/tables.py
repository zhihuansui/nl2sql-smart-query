"""
表元数据接口 — GET /tables 和 GET /tables/{name}。

通过 MetadataScanner 从目标业务数据库的 information_schema
反射表结构和列信息。支持 MySQL / PostgreSQL / SQLite。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.metadata import MetadataScanner


router = APIRouter(tags=["tables"])


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
