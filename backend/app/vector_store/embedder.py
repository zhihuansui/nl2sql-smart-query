"""
Embedding 服务 —— 封装 OpenAI text-embedding-3-small。

提供单条 / 批量文本的向量化功能，输出 1536 维向量。
"""

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings


@lru_cache(maxsize=1)
def _get_client() -> AsyncOpenAI:
    """获取 OpenAI 异步客户端单例。

    使用 ``EMBEDDING_API_KEY`` 初始化；支持通过
    ``OPENAI_BASE_URL`` 环境变量自定义 endpoint（兼容
    第三方 embedding 服务）。
    """
    return AsyncOpenAI(api_key=settings.EMBEDDING_API_KEY)


def _require_api_key() -> None:
    """检查 API Key 是否已配置，未配置则抛出明确的运行时错误。"""
    if not settings.EMBEDDING_API_KEY:
        raise RuntimeError(
            "EMBEDDING_API_KEY 未配置。请在 .env 文件中设置 "
            "EMBEDDING_API_KEY=sk-xxx 以启用 embedding 功能。"
        )


async def embed_text(text: str) -> list[float]:
    """将单条文本向量化为 1536 维向量。

    Args:
        text: 要向量化的文本。

    Returns:
        一个包含 1536 个 float 的向量。

    Raises:
        RuntimeError: EMBEDDING_API_KEY 未配置时抛出。

    Example::

        >>> vec = await embed_text("查询上周的订单总额")
        >>> len(vec)
        1536
    """
    _require_api_key()
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化 —— 一次 API 调用完成多条文本。

    Args:
        texts: 要向量化的文本列表。

    Returns:
        向量列表，顺序与输入 ``texts`` 一致。
        输入为空时返回空列表。

    Raises:
        RuntimeError: EMBEDDING_API_KEY 未配置时抛出。

    Example::

        >>> vecs = await embed_texts(["问题1", "问题2"])
        >>> len(vecs)
        2
        >>> len(vecs[0])
        1536
    """
    if not texts:
        return []

    _require_api_key()
    client = _get_client()
    response = await client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )

    # 按 index 排序确保与输入顺序一致
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]
