"""
Few-Shot Retriever — 从 Chroma ``golden_examples`` 集合中检索
与用户问题语义最相似的 2 个 "问题-SQL" 对，作为示例注入 Prompt，
引导 LLM 生成风格匹配的高质量 SQL。
"""

from __future__ import annotations

from app.vector_store.chroma_client import (
    GOLDEN_EXAMPLES,
    add_document,
    get_golden_examples_collection,
    query_similar,
)
from app.vector_store.embedder import embed_text


class FewShotRetriever:
    """黄金示例检索器。

    将用户问题向量化后检索语义最相似的 Top-K 个示例，
    每个示例包含问题原文和对应的标准 SQL。
    """

    async def retrieve(self, question: str, top_k: int = 2) -> list[dict]:
        """检索与问题最相似的 Few-Shot 示例。

        Args:
            question: 用户自然语言问题。
            top_k:    返回的示例数量。

        Returns:
            示例字典列表，每项格式::

                {
                    "question": "上月订单总数",
                    "sql": "SELECT COUNT(*) FROM orders WHERE ...",
                    "tables": ["orders"],
                    "tags": ["聚合", "时间范围"],
                }

            检索失败时返回空列表。
        """
        try:
            collection = get_golden_examples_collection()
            query_vec = await embed_text(question)
            result = await query_similar(collection, query_vec, top_k=top_k)

            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            ids = result.get("ids", [])

            examples = []
            for i, doc in enumerate(documents):
                meta = metadatas[i] if i < len(metadatas) else {}
                examples.append({
                    "question": doc,
                    "sql": meta.get("sql", ""),
                    "tables": meta.get("tables", []),
                    "tags": meta.get("tags", []),
                    "id": ids[i] if i < len(ids) else "",
                })
            return examples
        except Exception:
            return []

    async def index_example(
        self,
        question: str,
        sql: str,
        doc_id: str,
        tables: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """将一条黄金示例写入 Chroma 索引。

        Args:
            question: 自然语言问题文本（用作 embedding 源）。
            sql:      对应的标准 SQL。
            doc_id:   向量 ID，建议 ``"example:{uuid}"``。
            tables:   涉及的表名列表。
            tags:     标签列表。
        """
        collection = get_golden_examples_collection()
        embedding = await embed_text(question)
        metadata = {"sql": sql}
        if tables:
            metadata["tables"] = ",".join(tables)
        if tags:
            metadata["tags"] = ",".join(tags)
        await add_document(collection, question, embedding, doc_id, metadata)
