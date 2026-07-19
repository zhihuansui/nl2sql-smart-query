"""
Schema Linker — 基于向量检索从 Chroma ``table_schemas`` 集合中
召回与用户问题最相关的表结构文本。

将 schema 文本输入给 LLM，帮助它准确理解数据库中有哪些表和字段。
"""

from __future__ import annotations

from typing import Any

from app.vector_store.chroma_client import (
    TABLE_SCHEMAS,
    add_document,
    get_table_schemas_collection,
    query_similar,
)
from app.vector_store.embedder import embed_text


class SchemaLinker:
    """表结构检索器。

    将用户问题向量化，在 ``table_schemas`` 集合中检索最相关的
    Top-K 张表的结构文本。
    """

    async def retrieve(self, question: str, top_k: int = 3) -> list[str]:
        """检索与问题最相关的表结构文本列表。

        Args:
            question: 用户自然语言问题。
            top_k:    返回的表结构数量。

        Returns:
            表结构文本列表，每项如 ``"表 users: id(bigint PK 用户ID), ..."``
            检索失败时返回空列表。
        """
        try:
            collection = get_table_schemas_collection()
            query_vec = await embed_text(question)
            result = await query_similar(collection, query_vec, top_k=top_k)
            return result.get("documents", [])
        except Exception:
            # 向量检索失败时静默兜底，上层 Orchestrator 会使用空的 schema 列表
            return []

    async def index_table(
        self,
        table_name: str,
        schema_text: str,
        doc_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """将一张表的 schema 文本写入 Chroma 索引。

        通常在系统启动时由初始化流程调用。

        Args:
            table_name:  表名（仅用于元数据）。
            schema_text: 结构文本，如 ``"表 users: id(bigint PK), ..."``。
            doc_id:      向量 ID，建议用 ``"schema:{table_name}"``。
            metadata:    可选元数据。
        """
        collection = get_table_schemas_collection()
        embedding = await embed_text(schema_text)
        meta = {"table": table_name, **(metadata or {})}
        await add_document(collection, schema_text, embedding, doc_id, meta)
