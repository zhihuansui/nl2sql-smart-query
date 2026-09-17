"""
SQL 生成循环 — 调用 LLM 生成 SQL 并提取 ```sql 代码块。

设计要点：

- 单次 LLM 调用完成生成：NL→SQL 的输入（问题 + 表结构）一次性给全，
  不需要多轮工具调用探索，链路短、延迟可控、输出可复现。
- 失败模式单一：只需从输出中提取 ```sql 代码块，无需解析结构化的
  工具调用参数，出错时容易定位。
- 超时熔断 + 异常捕获：失败时返回结构化错误，由 Orchestrator 决定
  是否把数据库真实报错回灌给 LLM 重新生成。

外部 Orchestrator 负责 Schema Linking、Few-Shot 检索、安全检查、RLS 注入等。
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.provider import LLMProvider


# ─── SQL 提取 ─────────────────────────────────────────────────────────────────

_SQL_BLOCK_PATTERN = re.compile(
    r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE
)


def extract_sql(text: str) -> Optional[str]:
    """从 LLM 输出中提取 ```sql 代码块。"""
    match = _SQL_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


# ─── SQL 生成循环 ──────────────────────────────────────────────────────────────

class AgentLoop:
    """LLM SQL 生成循环。

    单次调用 LLM 生成 SQL 并提取代码块。生成失败（超时 / 无有效 SQL）
    时返回结构化错误，由 Orchestrator 决定是否重试。
    """

    MAX_EXECUTION_SECONDS: int = 30

    def __init__(self, max_execution_time: int = 30) -> None:
        """
        Args:
            max_execution_time: 单次 LLM 调用的超时秒数。
        """
        self._max_execution_time = max_execution_time
        self._llm_provider = LLMProvider()

    # ── 公开 API ───────────────────────────────────────────────────────────

    async def run(
        self,
        system_prompt: str,
        question: str,
    ) -> dict:
        """调用 LLM 生成 SQL。

        Args:
            system_prompt: 包含 schema、few-shot、RLS 等上下文的完整 System Prompt。
            question:      用户问题。

        Returns:
            {"sql": "...", "raw_output": "...", "success": True}
            或
            {"sql": None, "raw_output": "...", "success": False, "error": "..."}
        """
        llm = self._llm_provider.get_default_model()

        # 构建消息
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    f"问题: {question}\n\n"
                    "请直接生成 SQL 查询语句，用 ```sql 代码块包裹。\n"
                    "【重要】涉及用户表的关联必须用 LEFT JOIN（而非 JOIN），"
                    "这样没有订单的用户也会出现在结果中，相关字段值用 0 或 NULL 填充。"
                )
            ),
        ]

        try:
            result = await asyncio.wait_for(
                llm.agenerate([messages]),
                timeout=self._max_execution_time,
            )
            output = result.generations[0][0].text
        except asyncio.TimeoutError:
            return {
                "sql": None,
                "raw_output": "",
                "success": False,
                "error": f"LLM 响应超时（超过 {self._max_execution_time} 秒）",
            }
        except Exception as e:
            return {
                "sql": None,
                "raw_output": "",
                "success": False,
                "error": f"LLM 调用异常: {e!s}",
            }

        sql = extract_sql(output)

        if not sql:
            return {
                "sql": None,
                "raw_output": output,
                "success": False,
                "error": f"LLM 未生成有效的 SQL 代码块。原始输出: {output[:300]}",
            }

        return {
            "sql": sql,
            "raw_output": output,
            "success": True,
            "error": None,
        }
