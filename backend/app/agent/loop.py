"""
ReAct Agent 循环封装 — 创建 LangChain ReAct Agent，管理执行、
超时熔断、异常捕获和 SQL 代码块提取。

通过 ``AgentLoop.run()`` 执行单次推理，外部 Orchestrator 负责
重试和错误反馈。
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.agents import AgentFinish
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from app.llm.provider import LLMProvider


# ─── SQL 提取 ─────────────────────────────────────────────────────────────────

_SQL_BLOCK_PATTERN = re.compile(
    r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE
)


def extract_sql(text: str) -> Optional[str]:
    """从 ReAct Agent 的最终输出中提取 ```sql 代码块。

    Args:
        text: Agent 输出的文本（可能含 ```sql ... ``` 标记）。

    Returns:
        提取到的第一条 SQL 语句，没有找到则返回 ``None``。
    """
    match = _SQL_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


# ─── Agent 工厂 ───────────────────────────────────────────────────────────────

def _build_react_prompt() -> ChatPromptTemplate:
    """构建 ReAct Agent 使用的 Prompt 模板。

    System Prompt 由 Orchestrator 动态构建后作为变量传入。
    """
    return ChatPromptTemplate.from_messages([
        ("system", "{system_prompt}"),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])


# ─── Agent 循环 ───────────────────────────────────────────────────────────────

class AgentLoop:
    """ReAct Agent 执行循环。

    封装了 Agent 的创建、执行、超时熔断和异常处理。
    每个 ``AgentLoop`` 实例可重复使用（工具相同但 prompt 可变）。
    """

    def __init__(
        self,
        tools: list[BaseTool],
        max_iterations: int = 10,
        max_execution_time: int = 15,
    ) -> None:
        """
        Args:
            tools:               LangChain Tool 列表。
            max_iterations:      Agent 内部 ReAct 迭代上限。
            max_execution_time:  单次 Agent 调用的超时秒数（秒）。
        """
        self._tools = tools
        self._max_iterations = max_iterations
        self._max_execution_time = max_execution_time
        self._llm_provider = LLMProvider()

    # ── 公开 API ───────────────────────────────────────────────────────────

    async def run(
        self,
        system_prompt: str,
        question: str,
    ) -> dict:
        """执行一次 ReAct Agent 调用。

        Args:
            system_prompt: 包含 schema、few-shot、RLS 等上下文的完整 System Prompt。
            question:      用户问题。

        Returns:
            {"sql": "...", "raw_output": "...", "success": True}
            或
            {"sql": None, "raw_output": "...", "success": False, "error": "..."}
        """
        llm = self._llm_provider.get_default_model()
        prompt = _build_react_prompt()

        agent = create_react_agent(llm, self._tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=self._tools,
            max_iterations=self._max_iterations,
            handle_parsing_errors=True,
            verbose=False,
        )

        try:
            result = await asyncio.wait_for(
                executor.ainvoke({
                    "system_prompt": system_prompt,
                    "input": question,
                    "chat_history": [],
                    "agent_scratchpad": [],
                }),
                timeout=self._max_execution_time,
            )
        except asyncio.TimeoutError:
            return {
                "sql": None,
                "raw_output": "",
                "success": False,
                "error": "Agent 推理超时（超过 {} 秒）".format(self._max_execution_time),
            }
        except Exception as e:
            return {
                "sql": None,
                "raw_output": "",
                "success": False,
                "error": f"Agent 推理异常: {e!s}",
            }

        output = result.get("output", "")
        if isinstance(output, AgentFinish):
            output = output.return_values.get("output", "")

        sql = extract_sql(output)

        if not sql:
            return {
                "sql": None,
                "raw_output": output,
                "success": False,
                "error": "Agent 未生成有效的 SQL 代码块",
            }

        return {
            "sql": sql,
            "raw_output": output,
            "success": True,
            "error": None,
        }
