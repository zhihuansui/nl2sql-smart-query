"""
Embedding 服务 —— 通过 OpenAI 兼容接口调用 Ollama / 第三方 Embedding 模型。

默认使用 ``bge-m3``（通过 Ollama 本地运行），输出 1024 维向量。
只需配置 ``EMBEDDING_BASE_URL`` 即可切换任意 OpenAI 兼容的 Embedding API。
"""

from functools import lru_cache

from openai import AsyncOpenAI

from app.config import settings

# 单次 embedding 请求的最大文本数。
# 表结构按行切分后，一张宽表可能产生几十条文本，一次性提交容易触发
# 上游超时/长度限制，因此分批提交。
_BATCH_SIZE = 16


@lru_cache(maxsize=1)
def _get_client() -> AsyncOpenAI:
    """获取 OpenAI 异步客户端单例。

    通过 ``EMBEDDING_BASE_URL`` 支持任意兼容 OpenAI 的 Embedding 服务：
     - Ollama（本地）: http://localhost:11434
     - 第三方 API:    https://api.siliconflow.cn 等
    """
    kwargs = {"api_key": settings.EMBEDDING_API_KEY or "ollama"}
    if settings.EMBEDDING_BASE_URL:
        kwargs["base_url"] = settings.EMBEDDING_BASE_URL.rstrip("/") + "/v1"
    return AsyncOpenAI(**kwargs)


async def embed_text(text: str) -> list[float]:
    """将单条文本向量化。"""
    return (await embed_texts([text]))[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化（自动分批，返回顺序与入参一致）。"""
    if not texts:
        return []

    client = _get_client()
    embeddings: list[list[float]] = []

    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start:start + _BATCH_SIZE]
        response = await client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
        )
        # 部分服务不保证返回顺序，按 index 排回
        embeddings.extend(
            item.embedding for item in sorted(response.data, key=lambda x: x.index)
        )

    return embeddings
