"""
目标业务数据库执行器 — 只读 SELECT 查询。

根据 TARGET_DB_* 环境变量创建异步引擎，执行查询并返回结构化结果。
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


_MAX_RESULT_ROWS = 200
"""单次查询返回的最大行数"""


def _json_safe(value: Any) -> Any:
    """将数据库驱动返回的值递归转换为 JSON 可序列化类型。

    MySQL 的 DECIMAL 列返回 ``Decimal``、DATETIME 返回
    ``datetime`` 等类型，无法被 ``json.dumps`` 序列化，
    会导致 API 响应或写入 SQLite JSON 列时 500。
    """
    if value is None or isinstance(value, (bool, int, str, float)):
        return value
    if isinstance(value, Decimal):
        # 金额等 DECIMAL → float（浮点展示足够；超大整数浮点会丢精度，
        # 但业务查询结果展示场景可接受）
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    # 兜底：其他未知类型转为字符串
    return str(value)


def _build_target_async_url() -> str:
    """构造目标业务库的异步连接 URL。"""
    db_type = settings.TARGET_DB_TYPE.lower()

    if db_type == "mysql":
        return (
            f"mysql+aiomysql://{settings.TARGET_DB_USER}:{settings.TARGET_DB_PASS}"
            f"@{settings.TARGET_DB_HOST}:{settings.TARGET_DB_PORT}/{settings.TARGET_DB_NAME}"
        )
    if db_type == "postgresql":
        return (
            f"postgresql+asyncpg://{settings.TARGET_DB_USER}:{settings.TARGET_DB_PASS}"
            f"@{settings.TARGET_DB_HOST}:{settings.TARGET_DB_PORT}/{settings.TARGET_DB_NAME}"
        )
    if db_type == "sqlite":
        # 仅用于开发测试
        return f"sqlite+aiosqlite:///{settings.TARGET_DB_NAME}.db"

    raise ValueError(f"不支持的数据库类型: {db_type!r}")


class TargetDBExecutor:
    """目标业务数据库查询执行器。

    仅支持 ``SELECT`` 查询（安全护栏已在调用前拦截非法 SQL）。
    """

    def __init__(self) -> None:
        self._engine: Optional[AsyncEngine] = None

    # ── 引擎管理 ────────────────────────────────────────────────────────────

    def _get_engine(self) -> AsyncEngine:
        """懒创建异步引擎。"""
        if self._engine is None:
            url = _build_target_async_url()
            self._engine = create_async_engine(
                url,
                echo=(settings.APP_ENV == "development"),
                pool_size=settings.DB_POOL_SIZE,
                pool_recycle=settings.DB_POOL_IDLE_TIMEOUT,
            )
        return self._engine

    async def close(self) -> None:
        """关闭引擎并释放所有连接。"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # ── 查询执行 ────────────────────────────────────────────────────────────

    async def execute(self, sql: str) -> dict[str, Any]:
        """执行 SELECT 查询并返回结构化结果。

        Args:
            sql: 经安全检查和 RLS 注入后的 SQL。

        Returns:
            {
                "columns": ["col1", "col2", ...],
                "rows": [["val1", "val2"], ...],          # 最多 200 行
                "total_count": int,                       # 实际总行数
                "execution_ms": int,                      # 执行耗时
            }

        Raises:
            SQLAlchemyError: 数据库执行异常。
        """
        engine = self._get_engine()
        start = time.perf_counter()

        async with engine.connect() as conn:
            result: CursorResult = await conn.execute(text(sql))
            # 获取列名
            columns = list(result.keys())
            # 获取全部行
            all_rows = result.fetchall()
            total_count = len(all_rows)
            # 截断前 200 行，并规范化 Decimal/datetime 等为 JSON 安全类型
            truncated = all_rows[:_MAX_RESULT_ROWS]
            rows = [_json_safe(list(row)) for row in truncated]

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return {
            "columns": columns,
            "rows": rows,
            "total_count": total_count,
            "execution_ms": elapsed_ms,
        }

    async def execute_raw(self, sql: str) -> list[dict[str, Any]]:
        """执行 SQL 并以 dict 列表形式返回所有结果行。

        主要用于 Schema 信息查询（SELECT FROM information_schema 等）。

        Args:
            sql: 要执行的 SQL。

        Returns:
            [{"col1": val1, "col2": val2}, ...]
        """
        engine = self._get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchall()
            return [
                {col: _json_safe(val) for col, val in zip(columns, row)}
                for row in rows
            ]

    async def test_connection(self) -> bool:
        """测试数据库连接是否正常。

        Returns:
            连接正常返回 ``True``，否则返回 ``False``。
        """
        try:
            engine = self._get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False
