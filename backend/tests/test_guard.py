"""
SQL Guard 单元测试 — 覆盖正常 SQL、高危操作、多语句、时间注入等场景。

运行方式::

    cd backend
    pip install -e .  (或 pip install pytest)
    pytest tests/test_guard.py -v
"""

import pytest

from app.security.guard import SQLGuard


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def guard() -> SQLGuard:
    """提供干净 SQLGuard 实例。"""
    return SQLGuard()


# ─── 测试数据 ─────────────────────────────────────────────────────────────────

# (case_name, sql, is_dangerous_expected)
NORMAL_SQL_CASES = [
    ("简单 SELECT",                  "SELECT * FROM users",                          False),
    ("SELECT 带 WHERE",              "SELECT * FROM users WHERE id = 1",             False),
    ("SELECT 聚合",                  "SELECT COUNT(*) FROM orders",                  False),
    ("SELECT 多表 JOIN",             "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id", False),
    ("SELECT 子查询",                "SELECT * FROM (SELECT id FROM users) AS t",    False),
    ("SELECT 带 GROUP BY",           "SELECT region, SUM(amount) FROM orders GROUP BY region", False),
    ("SELECT 带 ORDER BY + LIMIT",   "SELECT * FROM users ORDER BY created_at DESC LIMIT 10", False),
    ("SELECT 带 UNION",              "SELECT name FROM users UNION SELECT name FROM former_users", False),
    ("SELECT 含字段别名",            "SELECT id AS user_id, name FROM users",         False),
    ("SELECT 时间格式化",            "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day FROM orders", False),
    ("SELECT 简单 HAVING",           "SELECT region, SUM(amount) AS s FROM orders GROUP BY region HAVING s > 1000", False),
    ("SELECT DISTINCT",              "SELECT DISTINCT region FROM orders",            False),
    ("SELECT 带注释",                "SELECT * FROM users -- 查询所有用户",             False),
]

DANGEROUS_SQL_CASES = [
    # ── DDL ──
    ("DROP TABLE",                   "DROP TABLE users",                              True),
    ("DROP DATABASE",                "DROP DATABASE business_db",                     True),
    ("ALTER TABLE",                  "ALTER TABLE users ADD COLUMN age INT",           True),
    ("TRUNCATE TABLE",               "TRUNCATE TABLE users",                          True),
    ("CREATE TABLE",                 "CREATE TABLE test (id INT)",                     True),

    # ── DML ──
    ("DELETE 全表",                  "DELETE FROM users",                             True),
    ("DELETE 带条件",                "DELETE FROM users WHERE id = 1",                True),
    ("UPDATE 全表",                  "UPDATE users SET name = 'x'",                   True),
    ("INSERT VALUES",                "INSERT INTO users VALUES (1, 'test')",          True),
    ("INSERT SELECT",                "INSERT INTO users SELECT * FROM temp_users",     True),
    ("REPLACE INTO",                 "REPLACE INTO users VALUES (1, 'new')",           True),

    # ── 权限 ──
    ("GRANT",                        "GRANT SELECT ON users TO 'test'@'localhost'",    True),
    ("REVOKE",                       "REVOKE SELECT ON users FROM 'test'@'localhost'", True),

    # ── 文件写入 ──
    ("SELECT INTO OUTFILE",          "SELECT * INTO OUTFILE '/tmp/data' FROM users",   True),
    ("SELECT INTO DUMPFILE",         "SELECT * INTO DUMPFILE '/tmp/dump' FROM users",  True),

    # ── 执行 ──
    ("EXEC 存储过程",                "EXEC sp_help 'users'",                           True),
    ("EXECUTE 函数",                 "EXECUTE some_function()",                        True),
]

MULTI_STATEMENT_CASES = [
    ("SELECT + DELETE",              "SELECT * FROM users; DELETE FROM orders",        True),
    ("SELECT + DROP",                "SELECT 1; DROP TABLE users",                     True),
    ("SELECT + INSERT",              "SELECT * FROM users; INSERT INTO logs VALUES(1)", True),
    ("多条 SELECT（安全）",           "SELECT 1; SELECT 2; SELECT 3",                    False),
    ("带注释的多条 SELECT",           "SELECT 1; -- separator; SELECT 2",               False),
]

TIME_INJECTION_CASES = [
    ("SLEEP 函数",                   "SELECT * FROM users WHERE id = 1 AND SLEEP(5)",  True),
    ("BENCHMARK 函数",               "SELECT BENCHMARK(1000000, MD5('test'))",         True),
    ("PG_SLEEP 函数",               "SELECT * FROM users WHERE pg_sleep(3)=1",         True),
    ("WAITFOR DELAY (MSSQL)",       "WAITFOR DELAY '0:0:5'",                           True),
    ("WAITFOR TIME (MSSQL)",        "WAITFOR TIME '23:00:00'",                          True),
    ("SLEEP 在子查询",              "SELECT * FROM (SELECT SLEEP(3)) AS t",            True),

    # ── 安全用户场景不应误杀 ──
    ("字段名恰含 sleep（通过）",      "SELECT * FROM users WHERE sleep_time > 10",       False),
]

EDGE_CASES = [
    ("空 SQL",                       "",                                                True),
    ("纯空白",                       "   \n  ",                                        True),
    ("纯注释（通过）",               "-- 这是一条注释",                                  False),
    ("SELECT 中带 DROP 注释（通过）", "SELECT 1 -- DROP TABLE users",                    False),
    ("关键字在字符串内（通过）",       "SELECT * FROM users WHERE name = 'DROP TABLE'",   False),
]


# ─── 参数化测试 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, sql, expected", NORMAL_SQL_CASES)
def test_normal_sql(guard: SQLGuard, name: str, sql: str, expected: bool) -> None:
    """正常 SELECT 查询应被放行。"""
    dangerous, reason = guard.inspect(sql)
    assert dangerous is expected, (
        f"[{name}] 期待危险={expected}，实际危险={dangerous}。\n"
        f"  SQL: {sql}\n  原因: {reason}"
    )


@pytest.mark.parametrize("name, sql, expected", DANGEROUS_SQL_CASES)
def test_dangerous_sql(guard: SQLGuard, name: str, sql: str, expected: bool) -> None:
    """高危 DDL/DML 操作应被拦截。"""
    dangerous, reason = guard.inspect(sql)
    assert dangerous is expected, (
        f"[{name}] 期待危险={expected}，实际危险={dangerous}。\n"
        f"  SQL: {sql}\n  原因: {reason}"
    )


@pytest.mark.parametrize("name, sql, expected", MULTI_STATEMENT_CASES)
def test_multi_statement(guard: SQLGuard, name: str, sql: str, expected: bool) -> None:
    """多语句检测：含任一非 SELECT 语句即拒绝。"""
    dangerous, reason = guard.inspect(sql)
    assert dangerous is expected, (
        f"[{name}] 期待危险={expected}，实际危险={dangerous}。\n"
        f"  SQL: {sql}\n  原因: {reason}"
    )


@pytest.mark.parametrize("name, sql, expected", TIME_INJECTION_CASES)
def test_time_injection(guard: SQLGuard, name: str, sql: str, expected: bool) -> None:
    """时间注入攻击应被拦截。"""
    dangerous, reason = guard.inspect(sql)
    assert dangerous is expected, (
        f"[{name}] 期待危险={expected}，实际危险={dangerous}。\n"
        f"  SQL: {sql}\n  原因: {reason}"
    )


@pytest.mark.parametrize("name, sql, expected", EDGE_CASES)
def test_edge_cases(guard: SQLGuard, name: str, sql: str, expected: bool) -> None:
    """边界情况处理。"""
    dangerous, reason = guard.inspect(sql)
    assert dangerous is expected, (
        f"[{name}] 期待危险={expected}，实际危险={dangerous}。\n"
        f"  SQL: {sql}\n  原因: {reason}"
    )


# ─── 附加测试 ─────────────────────────────────────────────────────────────────

def test_classify_select(guard: SQLGuard) -> None:
    """classify() 对 SELECT 返回 'SELECT'。"""
    assert guard.classify("SELECT * FROM users") == "SELECT"


def test_classify_delete(guard: SQLGuard) -> None:
    """classify() 对 DELETE 返回 'DELETE'。"""
    assert guard.classify("DELETE FROM users") == "DELETE"


def test_classify_unknown(guard: SQLGuard) -> None:
    """classify() 对空字符串返回 'UNKNOWN'。"""
    assert guard.classify("") == "UNKNOWN"


def test_inspect_returns_reason(guard: SQLGuard) -> None:
    """拦截时 reason 应为非空字符串。"""
    _, reason = guard.inspect("DROP TABLE users")
    assert isinstance(reason, str) and len(reason) > 0


def test_inspect_passes_returns_empty_reason(guard: SQLGuard) -> None:
    """放行时 reason 应为空字符串。"""
    _, reason = guard.inspect("SELECT 1")
    assert reason == ""
