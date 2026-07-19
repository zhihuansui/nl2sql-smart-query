"""
LangChain Tool 定义 — 供 ReAct Agent 调用的工具。

包含:
- ``sql_db_query`` — 执行 SQL SELECT 查询并返回结果表格。
- ``schema_info``  — 按表名返回完整字段列表（模拟 ``/tables/{name}``）。
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.db.executor import TargetDBExecutor
from app.db.metadata import MetadataScanner
from app.security.guard import SQLGuard


# ─── SQL 查询工具 ─────────────────────────────────────────────────────────────

class SQLQueryInput(BaseModel):
    """SQL 查询工具输入参数。"""
    query: str = Field(description="要执行的 SQL SELECT 语句，例如 SELECT COUNT(*) FROM users")


class SQLQueryTool(BaseTool):
    """执行 SQL SELECT 查询并返回结构化结果文本的工具。"""

    name: str = "sql_db_query"
    description: str = (
        "执行一条 SQL SELECT 查询并返回结果表格。"
        "适合用于验证假设、获取数据样本、确认字段值。"
        "输入必须是完整的 SELECT 语句。"
        "返回格式：列名 + 前 200 行数据 + 总行数 + 执行耗时。"
    )
    args_schema: type[BaseModel] = SQLQueryInput
    return_direct: bool = False

    _executor: TargetDBExecutor

    def __init__(self, executor: TargetDBExecutor) -> None:
        super().__init__()
        self._executor = executor

    async def _arun(self, query: str) -> str:
        guard = SQLGuard()
        is_dangerous, reason = guard.inspect(query)
        if is_dangerous:
            return f"[ERROR] 安全拦截: {reason}"

        try:
            result = await self._executor.execute(query)
        except Exception as e:
            return f"[ERROR] SQL 执行失败: {e!s}"

        columns = result["columns"]
        rows = result["rows"]
        total = result["total_count"]
        elapsed = result["execution_ms"]

        if not columns:
            return "[结果] 查询未返回任何列。"

        # 格式化输出
        header = " | ".join(columns)
        separator = "-+-".join("-" * len(c) for c in columns)
        lines = [f"列: {header}", f"     {separator}"]

        for row in rows[:10]:  # Agent 看到前 10 行就够决策了
            lines.append("    " + " | ".join(str(v) if v is not None else "NULL" for v in row))

        if len(rows) > 10:
            lines.append(f"    ...（共 {total} 行，仅展示前 10 行）")
        elif total > 0:
            lines.append(f"    （共 {total} 行）")

        lines.append(f"[耗时] {elapsed} ms")
        return "\n".join(lines)

    def _run(self, query: str) -> str:
        raise NotImplementedError("仅支持异步调用")


# ─── Schema 信息查询工具 ──────────────────────────────────────────────────────

class SchemaInfoInput(BaseModel):
    """Schema 信息查询工具输入参数。"""
    table_name: str = Field(description="要查询的表名，例如 users、orders")


class SchemaInfoTool(BaseTool):
    """按表名返回完整字段定义的工具。"""

    name: str = "schema_info"
    description: str = (
        "查询一张表的完整字段定义：字段名、数据类型、是否可空、主键、注释。"
        "当你拿到一个表名但不确定其字段含义时调用此工具。"
    )
    args_schema: type[BaseModel] = SchemaInfoInput
    return_direct: bool = False

    _scanner: MetadataScanner

    def __init__(self, scanner: MetadataScanner) -> None:
        super().__init__()
        self._scanner = scanner

    async def _arun(self, table_name: str) -> str:
        try:
            columns = await self._scanner.get_table_columns(table_name)
        except Exception as e:
            return f"[ERROR] 查询表结构失败: {e!s}"

        if not columns:
            return f"[INFO] 数据库中不存在表「{table_name}」，请确认表名是否正确。"

        lines = [f"表名: {table_name}", f"字段数: {len(columns)}", ""]
        for col in columns:
            nullable = "NULL" if col["nullable"] else "NOT NULL"
            pk = "🔑 PK" if col["is_pk"] else "   "
            comment = col.get("comment", "") or ""
            lines.append(f"  {pk} {col['name']:20s} {col['type']:15s} {nullable:8s} {comment}")

        return "\n".join(lines)

    def _run(self, table_name: str) -> str:
        raise NotImplementedError("仅支持异步调用")
