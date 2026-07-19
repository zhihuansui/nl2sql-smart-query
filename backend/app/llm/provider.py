"""
LLM 模型工厂 — 支持 DeepSeek 与 OpenAI 两种 Provider。

通过环境变量 ``LLM_PROVIDER`` 切换，默认使用 DeepSeek-V3。
"""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import settings


class LLMProvider:
    """LLM 模型工厂。

    用法::

        provider = LLMProvider()
        llm = provider.get_model()           # 获取聊天模型
        llm_fast = provider.get_model(fast=True)  # 轻量模型用于简单任务
    """

    # ── 模型名映射 ─────────────────────────────────────────────────────────

    PROVIDER_MODELS = {
        "deepseek": {
            "default": settings.LLM_MODEL,   # 默认 deepseek-v3
            "fast": "deepseek-chat",         # 轻量模型
        },
        "openai": {
            "default": "gpt-4o",
            "fast": "gpt-4o-mini",
        },
    }

    # ── 公开 API ───────────────────────────────────────────────────────────

    def get_model(self, *, fast: bool = False) -> ChatOpenAI:
        """获取 LLM 聊天模型实例。

        Args:
            fast: 为 ``True`` 时返回轻量模型（分类/解释类任务），
                  否则返回主力推理模型（SQL 生成）。

        Returns:
            ``langchain_openai.ChatOpenAI`` 实例。
        """
        provider = settings.LLM_PROVIDER.lower()
        model_map = self.PROVIDER_MODELS.get(provider, self.PROVIDER_MODELS["deepseek"])
        model_name = model_map.get("fast" if fast else "default", model_map["default"])

        kwargs = {
            "model": model_name,
            "temperature": 0.0,                # SQL 生成需要确定性输出
            "api_key": settings.LLM_API_KEY,
        }

        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL.rstrip("/") + "/v1"

        return ChatOpenAI(**kwargs)

    def get_default_model(self) -> ChatOpenAI:
        """获取主力推理模型 (SQL 生成)。"""
        return self.get_model(fast=False)

    def get_fast_model(self) -> ChatOpenAI:
        """获取轻量模型 (意图分类、解释)。"""
        return self.get_model(fast=True)
