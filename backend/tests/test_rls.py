"""
RLS 单元测试 — 覆盖单表、JOIN、无匹配、多语句、子句顺序等场景。

运行方式::

    cd backend
    pip install -e .  (或 pip install pytest)
    pytest tests/test_rls.py -v
"""

import pytest

from app.security.rls import RowLevelSecurity


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def rls() -> RowLevelSecurity:
    """使用默认策略的 RLS 实例。"""
    return RowLevelSecurity()


@pytest.fixture
def rls_custom() -> RowLevelSecurity:
    """使用自定义策略的 RLS 实例。"""
    policies = {
        "analyst_beijing": {"table": "sales", "clause": "city = 'Beijing'"},
        "analyst_shanghai": {"table": "sales", "clause": "city = 'Shanghai'"},
    }
    return RowLevelSecurity(policies)


# ─── 测试数据 ─────────────────────────────────────────────────────────────────

# 每条测试用例: (name, input_sql, user_id, expected_sql_or_substring)

SIMPLE_CASES = [
    (
        "匹配表·无 WHERE",
        "SELECT * FROM orders",
        "user_north",
        "SELECT * FROM orders WHERE region = 'North'",
    ),
    (
        "匹配表·已含 WHERE",
        "SELECT * FROM orders WHERE id > 10",
        "user_north",
        "SELECT * FROM orders WHERE id > 10 AND region = 'North'",
    ),
    (
        "不匹配表·无变化",
        "SELECT * FROM users",
        "user_north",
        "SELECT * FROM users",
    ),
    (
        "user_id 为 None·无变化",
        "SELECT * FROM orders",
        None,
        "SELECT * FROM orders",
    ),
    (
        "不存在的 user_id·无变化",
        "SELECT * FROM orders",
        "unknown_user",
        "SELECT * FROM orders",
    ),
]

CLAUSE_ORDER_CASES = [
    (
        "ORDER BY 前插入",
        "SELECT * FROM orders ORDER BY id",
        "user_north",
        "SELECT * FROM orders WHERE region = 'North' ORDER BY id",
    ),
    (
        "GROUP BY 前插入",
        "SELECT * FROM orders GROUP BY region",
        "user_north",
        "SELECT * FROM orders WHERE region = 'North' GROUP BY region",
    ),
    (
        "LIMIT 前插入",
        "SELECT * FROM orders LIMIT 10",
        "user_north",
        "SELECT * FROM orders WHERE region = 'North' LIMIT 10",
    ),
    (
        "WHERE + ORDER BY + LIMIT",
        "SELECT * FROM orders WHERE amount > 100 ORDER BY id LIMIT 5",
        "user_north",
        "SELECT * FROM orders WHERE amount > 100 AND region = 'North' ORDER BY id LIMIT 5",
    ),
    (
        "HAVING 前插入",
        "SELECT region, SUM(amount) AS s FROM orders GROUP BY region HAVING s > 1000",
        "user_north",
        "SELECT region, SUM(amount) AS s FROM orders WHERE region = 'North' GROUP BY region HAVING s > 1000",
    ),
]

JOIN_CASES = [
    (
        "JOIN 中匹配表",
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id",
        "user_north",
        # WHERE 插入位置在 JOIN ON 条件之后
        "WHERE region = 'North'",
    ),
    (
        "JOIN 中不匹配表",
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id",
        "unknown_user",
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id",
    ),
    (
        "INNER JOIN",
        "SELECT * FROM orders o INNER JOIN users u ON o.user_id = u.id",
        "user_north",
        "WHERE region = 'North'",
    ),
    (
        "LEFT JOIN",
        "SELECT * FROM orders o LEFT JOIN users u ON o.user_id = u.id WHERE u.active = 1",
        "user_north",
        "WHERE u.active = 1 AND region = 'North'",
    ),
]

MULTI_STATEMENT_CASES = [
    (
        "两条语句·第一条匹配",
        "SELECT * FROM orders; SELECT * FROM users",
        "user_north",
        # 只给 orders 注入，users 不变
        True,  # 用 True 表示使用 substring 检查
        ("WHERE region = 'North'", "SELECT * FROM users"),
    ),
]

ALIAS_CASES = [
    (
        "表别名不影响匹配",
        "SELECT * FROM orders AS o WHERE o.id > 10",
        "user_north",
        "WHERE o.id > 10 AND region = 'North'",
    ),
    (
        "字段名含下划线",
        "SELECT first_name FROM employees",
        "analyst_beijing",
        "SELECT first_name FROM employees",
    ),
]

EDGE_CASES = [
    (
        "空字符串",
        "",
        "user_north",
        "",
    ),
    (
        "纯空白",
        "   ",
        "user_north",
        "",
    ),
    (
        "带分号的单语句",
        "SELECT * FROM orders;",
        "user_north",
        "SELECT * FROM orders WHERE region = 'North';",
    ),
]


# ─── 参数化测试 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, sql, user_id, expected", SIMPLE_CASES)
def test_simple_cases(
    rls: RowLevelSecurity, name: str, sql: str, user_id: str | None, expected: str
) -> None:
    """基础 RLS 注入场景。"""
    result = rls.inject(sql, user_id)
    assert result == expected, (
        f"[{name}] 失败\n"
        f"  输入:    {sql!r}\n"
        f"  期望:    {expected!r}\n"
        f"  实际:    {result!r}"
    )


@pytest.mark.parametrize("name, sql, user_id, expected", CLAUSE_ORDER_CASES)
def test_clause_order(
    rls: RowLevelSecurity, name: str, sql: str, user_id: str | None, expected: str
) -> None:
    """WHERE 应插入在 GROUP/ORDER/LIMIT/HAVING 之前。"""
    result = rls.inject(sql, user_id)
    assert result == expected, (
        f"[{name}] 失败\n"
        f"  输入:    {sql!r}\n"
        f"  期望:    {expected!r}\n"
        f"  实际:    {result!r}"
    )


@pytest.mark.parametrize("name, sql, user_id, expected", JOIN_CASES)
def test_join_cases(
    rls: RowLevelSecurity, name: str, sql: str, user_id: str | None, expected: str
) -> None:
    """JOIN 查询中的 RLS 注入。"""
    result = rls.inject(sql, user_id)
    assert expected in result, (
        f"[{name}] 失败\n"
        f"  输入:    {sql!r}\n"
        f"  期望包含: {expected!r}\n"
        f"  实际:    {result!r}"
    )


@pytest.mark.parametrize(
    "name, sql, user_id, _, checks", MULTI_STATEMENT_CASES
)
def test_multi_statement(
    rls: RowLevelSecurity,
    name: str,
    sql: str,
    user_id: str | None,
    _: bool,
    checks: tuple[str, ...],
) -> None:
    """多语句场景：仅匹配表所在语句被注入。"""
    result = rls.inject(sql, user_id)
    for check_str in checks:
        assert check_str in result, (
            f"[{name}] 失败 - 期望包含 {check_str!r}，实际 {result!r}"
        )


@pytest.mark.parametrize("name, sql, user_id, expected", ALIAS_CASES)
def test_alias_cases(
    rls: RowLevelSecurity,
    name: str,
    sql: str,
    user_id: str | None,
    expected: str,
) -> None:
    """表别名、不同字段名场景。"""
    result = rls.inject(sql, user_id)
    assert expected in result, (
        f"[{name}] 失败\n"
        f"  输入:    {sql!r}\n"
        f"  期望包含: {expected!r}\n"
        f"  实际:    {result!r}"
    )


@pytest.mark.parametrize("name, sql, user_id, expected", EDGE_CASES)
def test_edge_cases(
    rls: RowLevelSecurity, name: str, sql: str, user_id: str | None, expected: str
) -> None:
    """边界情况。"""
    result = rls.inject(sql, user_id)
    assert result == expected, (
        f"[{name}] 失败\n"
        f"  输入:    {sql!r}\n"
        f"  期望:    {expected!r}\n"
        f"  实际:    {result!r}"
    )


# ─── 附加测试 ─────────────────────────────────────────────────────────────────

def test_custom_policy(rls_custom: RowLevelSecurity) -> None:
    """自定义策略正确生效。"""
    result = rls_custom.inject(
        "SELECT * FROM sales WHERE amount > 1000",
        "analyst_beijing",
    )
    assert "city = 'Beijing'" in result
    assert "amount > 1000" in result


def test_no_user_id_returns_original(rls: RowLevelSecurity) -> None:
    """user_id 为 None 时返回原始 SQL。"""
    sql = "SELECT * FROM orders"
    assert rls.inject(sql) == sql


def test_policy_table_not_in_sql(rls: RowLevelSecurity) -> None:
    """若 SQL 中不包含策略指定的表名，不注入。"""
    sql = "SELECT * FROM users WHERE id = 1"
    result = rls.inject(sql, "user_north")
    assert result == sql


def test_where_condition_contains_and(rls: RowLevelSecurity) -> None:
    """已存在 WHERE 时正确追加 AND。"""
    result = rls.inject(
        "SELECT region, SUM(amount) FROM orders WHERE region = 'East' GROUP BY region",
        "user_north",
    )
    # 应同时保留原始条件 + AND 新条件
    assert "region = 'East'" in result
    assert "AND region = 'North'" in result
    assert "GROUP BY" in result


def test_semicolon_handling(rls: RowLevelSecurity) -> None:
    """带分号的语句正确处理。"""
    result = rls.inject("SELECT * FROM orders;", "user_north")
    assert result.endswith(";")
    assert "WHERE region = 'North'" in result


def test_multiple_policies_mutate_independently() -> None:
    """不同用户策略互不影响。"""
    rls = RowLevelSecurity()
    north_result = rls.inject("SELECT * FROM orders", "user_north")
    east_result = rls.inject("SELECT * FROM orders", "user_east")
    assert "North" in north_result
    assert "East" in east_result
    assert north_result != east_result
