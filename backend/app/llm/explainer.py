"""
SQL 白话解释器 — 使用 LLM 将 SQL 翻译为业务人员能理解的
中文解释。

按 SPEC 2.4 节要求，在结果表格上方固定区域展示。
"""

from __future__ import annotations

from app.llm.provider import LLMProvider


_EXPLAIN_PROMPT = """你是一个企业数据助手中的解释器，你的任务是将 SQL 查询语句
翻译为业务人员能看懂的中文白话。

要求：
1. 只说"我理解您的需求是……"，不要解释技术细节（不要提 JOIN、WHERE 这些术语）。
2. 如果涉及时间条件，用 "X月X日" 或 "X月" 代替日期范围。
3. 如果涉及聚合（SUM/COUNT/AVG），说出统计的口径。
4. 保持简洁，一句话说完，不要超过 80 字。

用户问题：{question}
SQL语句：{sql}

请输出中文解释："""


class Explainer:
    """将 SQL 翻译为中文白话解释。"""

    def __init__(self) -> None:
        self._provider = LLMProvider()

    async def generate(self, question: str, sql: str) -> str:
        """根据原始问题和 SQL 生成白话解释。

        Args:
            question: 用户原始自然语言问题。
            sql: 最终执行的 SQL（已含 RLS 注入）。

        Returns:
            中文解释文本，如 "我理解您的需求是：统计2026年7月华北区订单总额。"
        """
        llm = self._provider.get_fast_model()
        prompt = _EXPLAIN_PROMPT.format(question=question, sql=sql)

        try:
            response = await llm.ainvoke(prompt)
            text = response.content.strip().strip('"').strip("'")
            return text
        except Exception:
            # 降级：当 LLM 不可用时返回基础模板
            return f"我理解您的需求是：根据您的问题「{question}」查询相关数据。"
