"""
目标业务数据库元数据扫描器。

从 information_schema 或方言特定来源读取表结构信息，
用于初始化 Chroma ``table_schemas`` 集合以及 SchemaInfoTool。
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings
from app.db.executor import _build_target_async_url


class MetadataScanner:
    """数据库元数据扫描器。

    支持 MySQL / PostgreSQL / SQLite，自动根据
    ``TARGET_DB_TYPE`` 选择对应的查询方言。
    """

    def __init__(self) -> None:
        self._engine: Optional[AsyncEngine] = None
        self._db_type = settings.TARGET_DB_TYPE.lower()

    # ── 引擎（与 TargetDBExecutor 独立以避免状态耦合） ─────────────────────

    def _get_engine(self) -> AsyncEngine:
        if self._engine is None:
            self._engine = create_async_engine(
                _build_target_async_url(),
                echo=False,
                pool_size=2,
            )
        return self._engine

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    # ── 公开接口 ────────────────────────────────────────────────────────────

    async def get_all_tables(self) -> list[dict[str, Any]]:
        """获取当前数据库中所有用户表的基本信息。

        Returns:
            [{"name": "users", "comment": "用户表", "row_count_approx": 120000, "column_count": 15}, ...]
        """
        engine = self._get_engine()
        async with engine.connect() as conn:
            if self._db_type == "mysql":
                rows = await self._mysql_tables(conn)
            elif self._db_type == "postgresql":
                rows = await self._postgres_tables(conn)
            else:  # sqlite
                rows = await self._sqlite_tables(conn)
        return rows

    async def get_table_columns(self, table_name: str) -> list[dict[str, Any]]:
        """获取指定表的所有列信息。

        Args:
            table_name: 表名。

        Returns:
            [{"name": "id", "type": "bigint", "nullable": False,
              "comment": "主键", "is_pk": True}, ...]
        """
        engine = self._get_engine()
        async with engine.connect() as conn:
            if self._db_type == "mysql":
                return await self._mysql_columns(conn, table_name)
            if self._db_type == "postgresql":
                return await self._postgres_columns(conn, table_name)
            return await self._sqlite_columns(conn, table_name)

    async def get_table_schema_text(self, table_name: str) -> str:
        """将一张表的完整结构拼接为文本，用于 Chroma embedding。

        Returns:
            如 ``表 users: id(bigint PK 用户ID), name(varchar 用户名), ...``
        """
        columns = await self.get_table_columns(table_name)
        if not columns:
            return ""

        parts = [f"表 {table_name}:"]
        for col in columns:
            nullable = "NULL" if col["nullable"] else "NOT NULL"
            pk = "PK " if col["is_pk"] else ""
            comment = col.get("comment") or ""
            parts.append(
                f"  {col['name']}({col['type']} {nullable} {pk}{comment})"
            )
        return "\n".join(parts)

    # ── MySQL ────────────────────────────────────────────────────────────────

    async def _mysql_tables(self, conn) -> list[dict[str, Any]]:
        result = await conn.execute(text("""
            SELECT
                TABLE_NAME           AS name,
                TABLE_COMMENT         AS comment,
                TABLE_ROWS            AS row_count_approx,
                (SELECT COUNT(*) FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = t.TABLE_SCHEMA
                   AND TABLE_NAME   = t.TABLE_NAME) AS column_count
            FROM information_schema.TABLES t
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_TYPE   = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """))
        return [dict(r._mapping) for r in result.fetchall()]

    async def _mysql_columns(self, conn, table: str) -> list[dict[str, Any]]:
        result = await conn.execute(
            text("""
                SELECT
                    COLUMN_NAME  AS name,
                    COLUMN_TYPE  AS type,
                    IS_NULLABLE  AS nullable,
                    COLUMN_COMMENT AS comment,
                    COLUMN_KEY   AS column_key
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = :table
                ORDER BY ORDINAL_POSITION
            """),
            {"table": table},
        )
        return [
            {
                "name": r._mapping["name"],
                "type": r._mapping["type"],
                "nullable": r._mapping["nullable"].upper() == "YES",
                "comment": r._mapping["comment"] or "",
                "is_pk": r._mapping["column_key"] == "PRI",
            }
            for r in result.fetchall()
        ]

    # ── PostgreSQL ────────────────────────────────────────────────────────────

    async def _postgres_tables(self, conn) -> list[dict[str, Any]]:
        result = await conn.execute(text("""
            SELECT
                t.table_name                 AS name,
                pgd.description              AS comment,
                (SELECT COUNT(*) FROM information_schema.columns c
                 WHERE c.table_schema = 'public' AND c.table_name = t.table_name)
                                             AS column_count
            FROM information_schema.tables t
            LEFT JOIN pg_catalog.pg_description pgd
                ON pgd.objsubid = 0
                AND pgd.objoid = (
                    SELECT c.oid FROM pg_catalog.pg_class c
                    WHERE c.relname = t.table_name AND c.relnamespace =
                        (SELECT n.oid FROM pg_catalog.pg_namespace n WHERE n.nspname = 'public')
                )
            WHERE t.table_schema = 'public'
              AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """))
        return [dict(r._mapping) for r in result.fetchall()]

    async def _postgres_columns(self, conn, table: str) -> list[dict[str, Any]]:
        result = await conn.execute(
            text("""
                SELECT
                    c.column_name                AS name,
                    c.data_type                  AS type,
                    c.is_nullable                AS nullable,
                    COALESCE(pgd.description, '') AS comment,
                    CASE WHEN pk.column_name IS NOT NULL THEN 'PRI' ELSE '' END AS column_key
                FROM information_schema.columns c
                LEFT JOIN pg_catalog.pg_description pgd
                    ON pgd.objsubid = c.ordinal_position::int
                    AND pgd.objoid = (
                        SELECT cls.oid FROM pg_catalog.pg_class cls
                        WHERE cls.relname = c.table_name
                          AND cls.relnamespace = (
                              SELECT n.oid FROM pg_catalog.pg_namespace n
                              WHERE n.nspname = 'public'
                          )
                    )
                LEFT JOIN (
                    SELECT ku.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage ku
                        ON tc.constraint_name = ku.constraint_name
                        AND tc.table_schema = ku.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = 'public'
                      AND tc.table_name = :table
                ) pk ON pk.column_name = c.column_name
                WHERE c.table_schema = 'public'
                  AND c.table_name  = :table
                ORDER BY c.ordinal_position
            """),
            {"table": table},
        )
        return [
            {
                "name": r._mapping["name"],
                "type": r._mapping["type"],
                "nullable": r._mapping["nullable"].upper() == "YES",
                "comment": r._mapping["comment"] or "",
                "is_pk": r._mapping["column_key"] == "PRI",
            }
            for r in result.fetchall()
        ]

    # ── SQLite ───────────────────────────────────────────────────────────────

    async def _sqlite_tables(self, conn) -> list[dict[str, Any]]:
        # SQLite 使用 sqlite_master 获取表名
        result = await conn.execute(text("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """))
        tables = [r._mapping["name"] for r in result.fetchall()]

        rows = []
        for tbl in tables:
            # PRAGMA table_info 获取列数
            pragma = await conn.execute(text(f"PRAGMA table_info(\"{tbl}\")"))
            cols = pragma.fetchall()
            rows.append({
                "name": tbl,
                "comment": "",
                "row_count_approx": 0,
                "column_count": len(cols),
            })
        return rows

    async def _sqlite_columns(self, conn, table: str) -> list[dict[str, Any]]:
        result = await conn.execute(text(f"PRAGMA table_info(\"{table}\")"))
        return [
            {
                "name": r._mapping["name"],
                "type": r._mapping["type"] or "TEXT",
                "nullable": not bool(r._mapping["notnull"]),
                "comment": "",
                "is_pk": bool(r._mapping["pk"]),
            }
            for r in result.fetchall()
        ]
