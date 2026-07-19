"""
Chroma 向量存储客户端。

按 SPEC 2.2 节管理两个集合：

+---------------------+----------------------------------+------+--------+
| Collection          | 存储内容                         | 维度 | 相似度 |
+---------------------+----------------------------------+------+--------+
| ``table_schemas``   | 表字段名 + 注释拼接文本           | 1536 | cosine |
| ``golden_examples`` | 高质问题-SQL 对的 embedding       | 1536 | cosine |
+---------------------+----------------------------------+------+--------+

Chroma 同步客户端封装为异步接口（``asyncio.to_thread``），
避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import chromadb
from chromadb import Collection
from chromadb.config import Settings as ChromaSettings

from app.config import settings

# ─── 常量 ─────────────────────────────────────────────────────────────────────

TABLE_SCHEMAS = "table_schemas"
"""表结构集合名称。"""

GOLDEN_EXAMPLES = "golden_examples"
"""黄金示例集合名称。"""

EMBEDDING_DIMENSION = 1536
"""向量维度（与 text-embedding-3-small 一致）。"""

SIMILARITY_METRIC = "cosine"
"""相似度度量方式。"""


# ─── 客户端初始化 ──────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_client() -> chromadb.ClientAPI:
    """获取/创建 Chroma 客户端单例。

    当 ``CHROMA_HOST`` 配置了主机地址时使用 HTTP 客户端
    （Docker 部署），否则使用本地持久化客户端（开发模式）。
    """
    if settings.CHROMA_HOST:
        return chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
        )
    return chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIR,
        settings=ChromaSettings(
            anonymized_telemetry=False,
        ),
    )


# ─── 集合管理 ─────────────────────────────────────────────────────────────────

def _get_or_create_collection(name: str) -> Collection:
    """获取已有集合，不存在则创建。

    Args:
        name: 集合名称（``table_schemas`` 或 ``golden_examples``）。

    Returns:
        Chroma Collection 对象。
    """
    client = _get_client()
    try:
        return client.get_collection(name)
    except ValueError:
        # 集合不存在 → 创建
        return client.create_collection(
            name=name,
            metadata={"hnsw:space": SIMILARITY_METRIC},
        )


@lru_cache(maxsize=2)
def get_table_schemas_collection() -> Collection:
    """获取 //table_schemas// 集合（结果被缓存）。"""
    return _get_or_create_collection(TABLE_SCHEMAS)


@lru_cache(maxsize=2)
def get_golden_examples_collection() -> Collection:
    """获取 //golden_examples// 集合（结果被缓存）。"""
    return _get_or_create_collection(GOLDEN_EXAMPLES)


# ─── 启动初始化 ────────────────────────────────────────────────────────────────

async def init_vector_store() -> None:
    """应用启动时预初始化 Chroma 集合，避免首次请求阻塞事件循环。

    应在 FastAPI lifespan 的 startup 阶段调用::

        @asynccontextmanager
        async def lifespan(app):
            await init_vector_store()
            yield
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, get_table_schemas_collection)
    await loop.run_in_executor(None, get_golden_examples_collection)


# ─── 异步 CRUD 操作 ───────────────────────────────────────────────────────────

async def add_document(
    collection: Collection,
    document: str,
    embedding: list[float],
    doc_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """添加单条文档与对应的 embedding 到集合。

    Args:
        collection: 目标 Chroma 集合。
        document:  文档原始文本（如 DDL 拼接文本 / 问题文本）。
        embedding: 预计算的 1536 维向量。
        doc_id:    唯一文档 ID。
        metadata:  可选元数据字典。
    """
    def _sync_add() -> None:
        collection.add(
            documents=[document],
            embeddings=[embedding],
            ids=[doc_id],
            metadatas=[metadata] if metadata else None,
        )

    await asyncio.to_thread(_sync_add)


async def query_similar(
    collection: Collection,
    query_embedding: list[float],
    top_k: int = 3,
) -> dict[str, Any]:
    """按向量相似度检索文档。

    Args:
        collection:      目标 Chroma 集合。
        query_embedding: 查询向量。
        top_k:           返回的 top-N 结果数。

    Returns:
        包含 keys ``documents``, ``metadatas``, ``distances``, ``ids`` 的字典。
        每个 value 是长度为 ``top_k`` 的列表。
    """
    def _sync_query() -> dict[str, Any]:
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )
        return {
            "ids": result["ids"][0] if result["ids"] else [],
            "documents": result["documents"][0] if result["documents"] else [],
            "metadatas": result["metadatas"][0] if result["metadatas"] else [],
            "distances": result["distances"][0] if result["distances"] else [],
        }

    return await asyncio.to_thread(_sync_query)


async def delete_document(collection: Collection, doc_id: str) -> None:
    """按 ID 删除集合中的文档。

    Args:
        collection: 目标 Chroma 集合。
        doc_id:     要删除的文档 ID。
    """
    def _sync_delete() -> None:
        collection.delete(ids=[doc_id])

    await asyncio.to_thread(_sync_delete)


async def count_documents(collection: Collection) -> int:
    """返回集合中的文档数量。

    Args:
        collection: 目标 Chroma 集合。

    Returns:
        文档总数。
    """
    def _sync_count() -> int:
        return collection.count()

    return await asyncio.to_thread(_sync_count)


async def update_document(
    collection: Collection,
    doc_id: str,
    document: str | None = None,
    embedding: list[float] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """更新集合中已有文档的内容和/或元数据。

    Args:
        collection: 目标 Chroma 集合。
        doc_id:     文档 ID。
        document:   新的文档文本（不更新则传 ``None``）。
        embedding:  新的向量（不更新则传 ``None``）。
        metadata:   新的元数据（不更新则传 ``None``）。
    """
    def _sync_update() -> None:
        collection.update(
            ids=[doc_id],
            documents=[document] if document else None,
            embeddings=[embedding] if embedding else None,
            metadatas=[metadata] if metadata else None,
        )

    await asyncio.to_thread(_sync_update)
