"""
行级权限（RLS）过滤器 — 基于 sqlparse AST 注入权限条件。

按 SPEC 4.5 节设计，在 SQL 执行前自动追加行级权限条件，
确保用户只能看到自己管辖范围的数据。

工作原理::

    1. 解析 SQL 为 AST（sqlparse）。
    2. 在 FROM / JOIN 子句中提取引用的表名。
    3. 若表名匹配当前用户的权限策略：
       - 已有 ``WHERE`` → 追加 ``AND {condition}``。
       - 无 ``WHERE``   → 在 ``GROUP BY`` / ``ORDER BY`` / ``LIMIT``
                         等子句前插入 ``WHERE {condition}``。

使用方式::

    rls = RowLevelSecurity()
    safe_sql = rls.inject("SELECT * FROM orders WHERE id > 10", "user_north")
    # → "SELECT * FROM orders WHERE id > 10 AND region = 'North'"
"""

from __future__ import annotations

from typing import Any, Optional

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Statement, TokenList, Where
from sqlparse.tokens import Keyword, Punctuation, Whitespace


# ─── 策略配置 ─────────────────────────────────────────────────────────────────

# 默认 RLS 策略（企业版下通常从数据库动态加载）
DEFAULT_POLICIES: dict[str, dict[str, str]] = {
    "user_north": {"table": "orders", "clause": "region = 'North'"},
    "user_east":  {"table": "orders", "clause": "region = 'East'"},
    "user_south": {"table": "orders", "clause": "region = 'South'"},
    "user_west":  {"table": "orders", "clause": "region = 'West'"},
}

# WHERE 之后的子句关键字（按 SQL 语法顺序）
# 注：sqlparse 将 ORDER BY / GROUP BY 作为一个 Token（值为 'ORDER BY' / 'GROUP BY'）
_CLAUSE_BOUNDARIES = frozenset({
    "ORDER BY", "GROUP BY", "LIMIT", "HAVING", "UNION",
    "OFFSET", "FETCH",
})

# JOIN 类型修饰符（出现在 ``JOIN`` 关键字之前）
_JOIN_MODIFIERS = frozenset({
    "INNER", "LEFT", "RIGHT", "CROSS", "FULL", "OUTER",
    "NATURAL", "LATERAL", "STRAIGHT_JOIN",
})


# ─── RLS ──────────────────────────────────────────────────────────────────────

class RowLevelSecurity:
    """行级权限过滤器。

    Attributes:
        policies: 用户 ID → {table, clause} 的映射字典。
    """

    def __init__(
        self,
        policies: Optional[dict[str, dict[str, str]]] = None,
    ) -> None:
        """
        Args:
            policies: 自定义策略字典，未提供时使用 ``DEFAULT_POLICIES``。
        """
        self.policies = policies or DEFAULT_POLICIES

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def inject(self, sql: str, user_id: Optional[str] = None) -> str:
        """在 SQL 中注入行级权限条件。

        Args:
            sql:      原始 SQL 字符串。
            user_id:  当前登录用户 ID。为 ``None`` 或不匹配任何策略时
                      返回原 SQL。

        Returns:
            注入 RLS 条件后的 SQL 字符串。
        """
        if not user_id or user_id not in self.policies:
            return sql

        policy = self.policies[user_id]
        parsed = sqlparse.parse(sql)

        modified_statements: list[str] = []
        for stmt in parsed:
            stmt_str = str(stmt).strip()
            if not stmt_str:
                continue

            # 仅对 SELECT 语句注入（guard 已在执行前拦截了非 SELECT）
            tables = self._extract_from_tables(stmt)
            if policy["table"] not in tables:
                modified_statements.append(stmt_str)
                continue

            modified = self._inject_condition(stmt, policy["clause"])
            modified_statements.append(modified)

        return " ".join(modified_statements)

    # ------------------------------------------------------------------
    # 表名提取
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_from_tables(stmt: Statement) -> list[str]:
        """从 FROM / JOIN 子句中提取表名。

        遍历顶层 Token 列表，定位 ``FROM`` 和 ``JOIN`` 关键字，
        收集紧跟其后的 Identifier/IdentifierList。

        Args:
            stmt: 已解析的 Statement。

        Returns:
            表名列表，不包含别名。
        """
        tables: list[str] = []
        tokens = stmt.tokens
        i = 0

        while i < len(tokens):
            token = tokens[i]

            # 定位 FROM/JOIN 关键字
            if token.ttype is Keyword and token.value.upper() in ("FROM", "JOIN"):
                # 向前跳过空白和（仅对 JOIN 后的）连接类型修饰符
                j = i + 1
                while j < len(tokens):
                    t = tokens[j]
                    if t.ttype is Whitespace:
                        j += 1
                        continue
                    # 跳过 JOIN 修饰符（INNER, LEFT, NATURAL, …）
                    if (
                        t.ttype is Keyword
                        and t.value.upper() in _JOIN_MODIFIERS
                    ):
                        j += 1
                        continue
                    # 跳过 ON 子句（JOIN 的配对条件）
                    if t.ttype is Keyword and t.value.upper() == "ON":
                        break
                    # 碰到 Identifier → 这就是表名
                    if isinstance(t, Identifier):
                        tables.append(t.get_real_name() or t.value)
                        break
                    # IdentifierList → "t1, t2"
                    if isinstance(t, IdentifierList):
                        for ident in t.get_identifiers():
                            tables.append(ident.get_real_name() or ident.value)
                        break
                    # 其他（子查询、括号等）→ 不是简单标识符，跳过
                    break
            i += 1

        return tables

    # ------------------------------------------------------------------
    # WHERE 注入
    # ------------------------------------------------------------------

    @classmethod
    def _inject_condition(cls, stmt: Statement, condition: str) -> str:
        """向语句中注入 ``WHERE condition``。

        策略:
        - 若已有 ``WHERE`` 子句 → 末尾追加 ``AND {condition}``。
        - 若无 ``WHERE``       → 在 ``GROUP BY`` / ``ORDER BY`` /
          ``LIMIT`` 等子句之前插入；若这些子句也不存在，追加至末尾。

        Args:
            stmt:      已解析的 Statement。
            condition: 权限条件字符串，如 ``"region = 'North'"``。

        Returns:
            注入后的完整 SQL 字符串。
        """
        stmt_str = str(stmt)

        # ── 情况 A: 已有 WHERE 子句 ──────────────────────────────────
        where_token: Optional[Where] = None
        for token in stmt.tokens:
            if isinstance(token, Where):
                where_token = token
                break

        if where_token is not None:
            where_end = cls._token_end_offset(stmt, where_token)
            before = stmt_str[:where_end].rstrip()
            after = stmt_str[where_end:].lstrip()
            return f"{before} AND {condition}{' ' + after if after else ''}"

        # ── 情况 B: 无 WHERE 子句 ────────────────────────────────────
        insert_pos = cls._find_clause_insert_point(stmt)

        # 提取前后文并规范化空白
        prefix = stmt_str[:insert_pos].rstrip()
        suffix = stmt_str[insert_pos:].lstrip()

        # 构造 WHERE 子句
        where_clause = f"WHERE {condition}"

        if not suffix:
            # 末尾
            return f"{prefix} {where_clause};" if stmt_str.rstrip().endswith(";") else f"{prefix} {where_clause}"
        if suffix == ";":
            return f"{prefix} {where_clause};"
        return f"{prefix} {where_clause} {suffix}"

    @staticmethod
    def _token_end_offset(stmt: Statement, target: TokenList) -> int:
        """计算目标 Token 在 Statement 字符串中的结束偏移。

        通过顺序累计 Statement 顶层 Token 的字符串长度来确定位置。
        """
        offset = 0
        for token in stmt.tokens:
            token_str = str(token)
            if token is target:
                return offset + len(token_str)
            offset += len(token_str)
        # fallback（不应到达）
        return len(str(stmt))

    @staticmethod
    def _find_clause_insert_point(stmt: Statement) -> int:
        """找到应在何处插入 WHERE 子句（字符偏移）。

        遍历顶层 Token，遇到以下子句关键字时返回其位置:
        ``GROUP BY``, ``ORDER BY``, ``LIMIT``, ``HAVING``,
        ``UNION``, ``OFFSET``, ``FETCH``。

        若均不存在，返回末尾（语句字符串长度）。
        """
        offset = 0
        for token in stmt.tokens:
            token_str = str(token)

            # 检测子句边界关键字
            if token.ttype is Keyword:
                upper = token.value.upper()
                if upper in _CLAUSE_BOUNDARIES:
                    return offset
                # 处理 FOR UPDATE / FOR SHARE
                if upper == "FOR":
                    # 确认是 FOR UPDATE/SHARE（后面紧跟着这些关键字）
                    next_text = token_str[len(token.value):].lstrip().upper()
                    if next_text.startswith("UPDATE") or next_text.startswith("SHARE"):
                        return offset

            # 分号 → 在该位置前插入 WHERE
            if token.ttype is Punctuation and token.value == ";":
                return offset

            offset += len(token_str)

        # 无边界关键字 → 返回末尾
        return offset
