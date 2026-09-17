"""
Schema Linker — 表结构的「切分 → 向量化 → 召回 → 还原」链路。

与早期"一张表一个向量"的做法不同，这里把表结构文本**按行切分**成 chunk，
每行（表头行、每个字段一行）单独向量化并附带元数据（表名、版本、字段名、
行号），检索时先由向量召回相关 chunk，再用元数据把同一张表的所有 chunk
捞回来、按行号还原成完整表结构。

这样做的好处是：宽表（几十个字段）的整表向量会稀释语义，导致"哪个表有
XX 字段"这类问题召回不准；拆成行级 chunk 后，单个字段的描述可以精确命中，
同时又不丢失整表上下文。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.vector_store.chroma_client import (
    get_table_schemas_collection,
    add_documents,
    delete_where,
    get_where,
    query_similar,
)
from app.vector_store.embedder import embed_texts


# 每个字段行在向量召回阶段放大多少倍候选数。
# 召回的是 chunk，但最终要按"表"返回，所以需要多召回一些才能凑够 top_k 张表。
_RECALL_FACTOR = 8

# 单次向量召回 chunk 数的上限，防止 top_k 过大时拖慢查询。
_MAX_RECALL = 100


# ─── Chunk 数据结构 ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SchemaChunk:
    """表结构切分后的单个 chunk（对应原文本的一行）。"""

    text: str
    """原始行文本（含缩进），用于还原表结构时按序拼接。"""

    embed_text: str
    """送入 embedding 的文本 —— 补全了表名的自包含版本。"""

    column: str
    """该行对应的字段名；表头行为空字符串。"""


# ─── 切分 ─────────────────────────────────────────────────────────────────────

def split_schema_into_chunks(schema_text: str, table_name: str) -> list[SchemaChunk]:
    """将一张表的 schema 文本按行切分为 chunk —— 每行数据 = 一个 chunk。

    空行被丢弃。

    **为什么 ``text`` 和 ``embed_text`` 是两个不同的字符串**：单行
    ``id(bigint NOT NULL PK 用户ID)`` 脱离表名后，在几乎所有表里都长得
    差不多，直接拿去 embedding 会得到一堆彼此难以区分的向量。所以存储的
    是原文（保证能无损还原），嵌入的是补了表名前缀的自包含文本（保证
    向量有区分度）。Chroma 的 ``documents`` 与 ``embeddings`` 本就可以
    分开传，正好支持这一点。

    Args:
        schema_text: ``MetadataScanner.get_table_schema_text()`` 的输出。
        table_name:  表名，用于构造 ``embed_text``。

    Returns:
        SchemaChunk 列表，顺序与原文行序一致。
    """
    chunks: list[SchemaChunk] = []

    for raw_line in schema_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        column = _parse_column_name(stripped)
        # 字段行补表名；表头行（"表 users:"）本身已含表名，保持原样
        embed_text = f"表 {table_name}: {stripped}" if column else stripped
        chunks.append(SchemaChunk(text=raw_line, embed_text=embed_text, column=column))

    return chunks


def _parse_column_name(line: str) -> str:
    """从 ``id(bigint NOT NULL PK 用户ID)`` 这类列定义行提取字段名。

    表头行 ``表 users:`` 不含左括号，返回空字符串。
    """
    idx = line.find("(")
    return line[:idx].strip() if idx > 0 else ""


# ─── 检索器 ───────────────────────────────────────────────────────────────────

class SchemaLinker:
    """表结构检索器。

    优先通过向量检索找到最相关的 Top-K 张表；若 Chroma 为空（首次使用
    或尚未初始化），则直接扫描数据库所有表作为兜底。
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
        # ── 首选：向量召回 chunk + 元数据还原整表 ──
        try:
            texts = await self._retrieve_by_chunks(question, top_k)
            if texts:
                return texts
        except Exception:
            pass

        # ── 兜底：直接扫描所有表 ──
        return await self._retrieve_by_scan(top_k)

    # ── 两阶段检索 ────────────────────────────────────────────────────────────

    async def _retrieve_by_chunks(self, question: str, top_k: int) -> list[str]:
        """第一阶段按 chunk 召回，第二阶段用元数据还原完整表结构。"""
        collection = get_table_schemas_collection()
        version = settings.SCHEMA_INDEX_VERSION

        query_vec = (await embed_texts([question]))[0]
        recall_k = min(max(top_k * _RECALL_FACTOR, top_k), _MAX_RECALL)

        result = await query_similar(
            collection,
            query_vec,
            top_k=recall_k,
            where={"version": version},
        )

        # ── 用元数据把 chunk 归并回「表」 ──
        # query 结果已按距离升序，故首次出现的顺序即表的相关度排序。
        table_names: list[str] = []
        for meta in result.get("metadatas", []):
            name = (meta or {}).get("table")
            if name and name not in table_names:
                table_names.append(name)

        if not table_names:
            return []

        # ── 取回每张表的全部 chunk，按 chunk_index 还原完整表结构 ──
        texts: list[str] = []
        for name in table_names[:top_k]:
            fetched = await get_where(
                collection,
                {"$and": [{"table": name}, {"version": version}]},
            )
            rebuilt = self._rebuild_schema_text(fetched)
            if rebuilt:
                texts.append(rebuilt)
        return texts

    @staticmethod
    def _rebuild_schema_text(fetched: dict[str, Any]) -> str:
        """把同一张表的 chunk 按 ``chunk_index`` 排序后拼回完整表结构文本。

        ``collection.get()`` 不保证返回顺序，所以必须依赖元数据里的行号排序。
        """
        documents = fetched.get("documents") or []
        metadatas = fetched.get("metadatas") or []

        rows: list[tuple[int, str]] = []
        for i, doc in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            try:
                index = int((meta or {}).get("chunk_index", i))
            except (TypeError, ValueError):
                index = i
            rows.append((index, doc))

        if not rows:
            return ""
        rows.sort(key=lambda pair: pair[0])
        return "\n".join(doc for _, doc in rows)

    # ── 兜底扫描 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _retrieve_by_scan(top_k: int) -> list[str]:
        """Chroma 不可用/未索引时，直接扫描数据库取表结构。"""
        from app.db.metadata import MetadataScanner

        scanner = MetadataScanner()
        try:
            tables = await scanner.get_all_tables()
            result: list[str] = []
            for table in tables:
                schema_text = await scanner.get_table_schema_text(table["name"])
                if schema_text:
                    result.append(schema_text)
            return result[:top_k]
        except Exception:
            return []
        finally:
            await scanner.close()

    # ── 索引 ──────────────────────────────────────────────────────────────────

    async def index_table(
        self,
        table_name: str,
        schema_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """将一张表的 schema 文本切分、向量化后写入 Chroma 索引。

        每行一个 chunk，元数据包含：

        +---------------+------------------------------------------+
        | ``table``     | 表名（要求在检索端按表还原）              |
        | ``version``   | 索引版本，见 ``SCHEMA_INDEX_VERSION``    |
        | ``column``    | 该行对应的字段名（表头行为空串）          |
        | ``chunk_index`` | 行号，还原时的排序依据                  |
        | ``chunk_total`` | 该表 chunk 总数                         |
        +---------------+------------------------------------------+

        写入前会先删除该表的所有旧向量（含旧版本、旧切分格式），
        因此重复执行是幂等的，不会产生重复 chunk。

        Args:
            table_name:  表名。
            schema_text: 结构文本，如 ``"表 users:\\n  id(bigint PK), ..."``。
            metadata:    额外的元数据，会合并进每个 chunk 的元数据。

        Returns:
            写入的 chunk 数量；``schema_text`` 为空时返回 0。
        """
        chunks = split_schema_into_chunks(schema_text, table_name)
        if not chunks:
            return 0

        collection = get_table_schemas_collection()
        version = settings.SCHEMA_INDEX_VERSION

        # 清理该表的旧 chunk（旧版本 / 旧的整表单文档格式），保证幂等
        await delete_where(collection, {"table": table_name})

        embeddings = await embed_texts([c.embed_text for c in chunks])
        total = len(chunks)

        doc_ids = [f"schema:{table_name}:{i}" for i in range(total)]
        metadatas = [
            {
                "table": table_name,
                "version": version,
                "column": chunk.column,
                "chunk_index": i,
                "chunk_total": total,
                **(metadata or {}),
            }
            for i, chunk in enumerate(chunks)
        ]

        await add_documents(
            collection,
            [c.text for c in chunks],
            embeddings,
            doc_ids,
            metadatas,
        )
        return total

    async def delete_table(self, table_name: str) -> None:
        """删除某张表在向量库中的全部 chunk（表被删除时调用）。"""
        await delete_where(get_table_schemas_collection(), {"table": table_name})
