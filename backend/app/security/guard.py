"""
SQL 安全护栏 — 拦截非法 SQL 与危险函数。

按 SPEC 4.4 节设计，执行两层检查：

1.  **多语句检查** — 遍历 sqlparse 解析出的所有 Statement，任一非 SELECT 即拒绝。
2.  **危险函数检查** — 在文本中检测 SLEEP / BENCHMARK / WAITFOR / PG_SLEEP 等
    时间注入函数，防止基于时间的盲注攻击。

使用方式::

    guard = SQLGuard()
    is_dangerous, reason = guard.inspect(sql)

    # 仅检查 SELECT 类型
    sql_type = guard.classify(sql)
"""

from __future__ import annotations

import re
from typing import Optional

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import DML, Keyword


# ─── 配置 ─────────────────────────────────────────────────────────────────────

# 高危 DML/DDL 关键字（正则第一层匹配）
DANGEROUS_KEYWORDS: list[str] = [
    "DELETE",
    "DROP",
    "ALTER",
    "INSERT",
    "UPDATE",
    "TRUNCATE",
    "REPLACE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
]

# 文件写入类操作（出现在 SELECT 中也危险）
DANGEROUS_FILE_OPS: list[str] = [
    "INTO OUTFILE",
    "INTO DUMPFILE",
]

# 时间/延时注入函数
TIME_INJECTION_FUNCTIONS: list[str] = [
    "SLEEP",
    "BENCHMARK",
    "PG_SLEEP",
    "WAITFOR",
    "DELAY",
]

# 所有危险模式合并（用于第一层正则扫描）
ALL_DANGEROUS_PATTERNS: list[str] = (
    DANGEROUS_KEYWORDS + DANGEROUS_FILE_OPS + TIME_INJECTION_FUNCTIONS
)

# 安全绕过检测：当危险关键字出现在注释/字符串中时不算
COMMENT_PATTERN = re.compile(r"--.*$|#.*$|/\*.*?\*/", re.MULTILINE | re.DOTALL)
STRING_PATTERN = re.compile(r"'[^']*'|\"[^\"]*\"")


# ─── Guard ────────────────────────────────────────────────────────────────────

class SQLGuard:
    """SQL 安全护栏。

    负责在 SQL **执行前** 进行安全拦截，确保仅 ``SELECT`` 类查询
    可以通过系统执行。
    """

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def inspect(self, sql: str) -> tuple[bool, str]:
        """完整安全检查入口。

        Args:
            sql: 用户或 Agent 产生的原始 SQL 字符串。

        Returns:
            (is_dangerous, reason) 元组。
            当 ``is_dangerous`` 为 ``True`` 时，``reason`` 描述拦截原因。
        """
        # 0. 空 SQL
        stripped = sql.strip()
        if not stripped:
            return True, "SQL 为空，不执行任何操作"

        # 1. 第一层：正则快速扫描（剥离注释和字符串后再匹配）
        cleaned = self._strip_literals(stripped)
        upper = cleaned.upper()

        for pattern in ALL_DANGEROUS_PATTERNS:
            if re.search(rf"\b{re.escape(pattern)}\b", upper):
                return True, f"检测到 {pattern} 操作，该操作已被拦截。本系统仅支持 SELECT 数据查询。"

        # 2. 第二层：sqlparse AST 精确验证
        parsed = sqlparse.parse(stripped)
        if not parsed:
            return True, "无法解析 SQL 语句，已拦截"

        # 多语句检测
        if len(parsed) > 1:
            for stmt in parsed:
                stmt_type = self.classify(stmt)
                if stmt_type != "SELECT":
                    return True, f"检测到多条 SQL 语句，其中包含 {stmt_type} 操作，已拦截"
            return False, ""  # 全是 SELECT → 通过

        # 单语句类型校验
        stmt = parsed[0]
        stmt_type = self.classify(stmt)

        if stmt_type == "UNKNOWN":
            # UNKNOWN 可能是纯注释或空语句，保守放行让后续流程处理
            return False, ""

        if stmt_type != "SELECT":
            return True, (
                f"检测到 {stmt_type} 语句，本系统仅支持 SELECT 查询。"
            )

        return False, ""

    def classify(self, stmt: str | Statement) -> str:
        """判断 SQL 语句类型。

        Args:
            stmt: SQL 字符串或已解析的 Statement 对象。

        Returns:
            大写类型字符串，如 ``"SELECT"``, ``"DELETE"``, ``"UNKNOWN"`` 等。
        """
        if isinstance(stmt, str):
            parsed = sqlparse.parse(stmt)
            if not parsed:
                return "UNKNOWN"
            stmt = parsed[0]

        return stmt.get_type()  # 类型: SELECT, INSERT, DELETE, UNKNOWN 等

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_literals(sql: str) -> str:
        """剥离注释和字符串字面量，防止关键字伪装。

        Args:
            sql: 原始 SQL。

        Returns:
            移除了注释和字符串内容后的 SQL 骨架。
        """
        result = COMMENT_PATTERN.sub(" ", sql)
        result = STRING_PATTERN.sub("''", result)
        return result
