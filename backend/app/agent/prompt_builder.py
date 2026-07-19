"""
Prompt 模板构建器 — 按 SPEC 4.3 节模板将系统指令、表结构、
Few-Shot 示例、对话历史和 RLS 策略组装为完整 System Prompt。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional


SYSTEM_PROMPT_TEMPLATE = """## 角色
你是一个企业级 SQL 查询助手，帮助业务人员从数据库中提取数据。
严格遵守以下规则：
1. 仅生成 SELECT 语句，禁止任何 INSERT/UPDATE/DELETE/DROP/ALTER。
2. 只使用下方【可用表结构】中列出的表和字段，不确定字段时使用 SchemaInfoTool 查询。
3. 生成 SQL 前先思考：是否需要 JOIN、聚合、排序、LIMIT？
4. LIMIT 最大不超过 1000，若用户未指定，默认 LIMIT 200。
5. 输出最终 SQL 时，用 ```sql 代码块包裹。

## 可用表结构
{schema_text}

## 参考示例
{few_shot_text}

## 对话历史（最近 2 轮）
{history_text}

## 行级权限策略（如有）
{rls_policy}

## 当前日期
{current_date}"""


class PromptBuilder:
    """按模板组装 LLM System Prompt。"""

    # ── 格式化占位符 ────────────────────────────────────────────────────────

    @staticmethod
    def _format_schemas(schemas: list[str]) -> str:
        """将 schema 文本列表格式化为可读文本。"""
        if not schemas:
            return "（未检索到表结构，请使用 SchemaInfoTool 查询）"
        return "\n\n".join(schemas)

    @staticmethod
    def _format_few_shots(examples: list[dict]) -> str:
        """将 Few-Shot 示例格式化为可读文本。"""
        if not examples:
            return "（无参考示例）"
        parts = []
        for i, ex in enumerate(examples, 1):
            question = ex.get("question", "")
            sql = ex.get("sql", "")
            tags = ex.get("tags", [])
            tag_str = f"  -- 标签: {', '.join(tags)}" if tags else ""
            parts.append(f"【示例 {i}】\n问题: {question}\nSQL: {sql}{tag_str}")
        return "\n\n".join(parts)

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        """将最近 2 轮对话历史格式化为文本。"""
        if not history:
            return "（无历史记录）"
        parts = []
        for h in history:
            q = h.get("user_question", "")
            sql = h.get("generated_sql", "")
            parts.append(f"用户: {q}\n助手(执行成功): ```sql\n{sql}\n```")
        return "\n\n".join(parts)

    @staticmethod
    def _format_rls(policy: Optional[dict[str, str]]) -> str:
        """格式化 RLS 策略。"""
        if not policy:
            return "（无权限限制）"
        condition = policy.get("clause", "")
        return f"行级权限：自动追加过滤条件 `{condition}`，生成 SQL 时无需手动添加。"

    # ── 构建 ────────────────────────────────────────────────────────────────

    def build(
        self,
        *,
        schemas: list[str],
        few_shots: list[dict],
        history: list[dict],
        rls_policy: Optional[dict[str, str]],
    ) -> str:
        """构建完整的 System Prompt。

        Args:
            schemas:   SchemaLinker 检索到的表结构文本列表。
            few_shots: FewShotRetriever 检索到的示例列表。
            history:   最近 2 轮对话历史（含 question + sql）。
            rls_policy: 当前用户的 RLS 策略，如 ``{"table": "orders", "clause": "region = 'North'"}``。

        Returns:
            完整的 System Prompt 字符串。
        """
        today = date.today().isoformat()

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            schema_text=self._format_schemas(schemas),
            few_shot_text=self._format_few_shots(few_shots),
            history_text=self._format_history(history),
            rls_policy=self._format_rls(rls_policy),
            current_date=today,
        )
        return prompt
