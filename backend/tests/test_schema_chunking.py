"""
表结构切分 / 元数据 / 召回还原 单元测试。

覆盖 ``SchemaLinker.index_table`` 的「一行一个 chunk + 元数据」写入，
以及 ``retrieve`` 的「chunk 召回 → 按元数据还原整表」链路。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.schema_link import SchemaLinker, split_schema_into_chunks
from app.config import settings


SCHEMA_TEXT = """表 users:
  id(bigint NOT NULL PK 用户ID)
  name(varchar NOT NULL  用户名)
  created_at(datetime NOT NULL  创建时间)"""


# ============================================================
# 切分
# ============================================================

def test_split_one_chunk_per_line():
    """每一行数据切分为一个 chunk，空行被丢弃。"""
    chunks = split_schema_into_chunks(SCHEMA_TEXT, "users")
    assert len(chunks) == 4  # 表头行 + 3 个字段行

    assert chunks[0].column == ""
    assert chunks[1].column == "id"
    assert chunks[2].column == "name"
    assert chunks[3].column == "created_at"


def test_split_skips_blank_lines():
    """空行不产生 chunk。"""
    chunks = split_schema_into_chunks("表 t:\n\n  a(int)\n\n  b(int)\n", "t")
    assert [c.column for c in chunks] == ["", "a", "b"]


def test_chunk_stores_raw_line_but_embeds_table_qualified_text():
    """存储原文（可还原），嵌入补全表名的文本（有区分度）。"""
    chunks = split_schema_into_chunks(SCHEMA_TEXT, "users")
    id_chunk = chunks[1]

    # 原文保留缩进，用于无损还原
    assert id_chunk.text == "  id(bigint NOT NULL PK 用户ID)"
    # 嵌入文本带表名
    assert id_chunk.embed_text == "表 users: id(bigint NOT NULL PK 用户ID)"
    # 表头行本身已含表名，不重复加前缀
    assert chunks[0].embed_text == "表 users:"


def test_split_empty_text():
    """空文本不产生 chunk。"""
    assert split_schema_into_chunks("", "t") == []
    assert split_schema_into_chunks("\n\n", "t") == []


# ============================================================
# 索引：元数据写入
# ============================================================

@pytest.mark.asyncio
async def test_index_table_writes_metadata_with_table_and_version():
    """每行一个向量，元数据必须包含表名与版本。"""
    added: dict = {}

    async def fake_add(collection, documents, embeddings, doc_ids, metadatas):
        added.update(
            documents=documents,
            embeddings=embeddings,
            doc_ids=doc_ids,
            metadatas=metadatas,
        )

    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.delete_where", AsyncMock()) as m_delete,
        patch("app.agent.schema_link.embed_texts", AsyncMock(
            return_value=[[0.1] * 1024] * 4,
        )),
        patch("app.agent.schema_link.add_documents", fake_add),
    ):
        count = await SchemaLinker().index_table("users", SCHEMA_TEXT)

    assert count == 4
    assert len(added["documents"]) == 4
    assert len(added["metadatas"]) == 4
    assert added["doc_ids"] == [
        "schema:users:0", "schema:users:1", "schema:users:2", "schema:users:3",
    ]

    for i, meta in enumerate(added["metadatas"]):
        assert meta["table"] == "users"
        assert meta["version"] == settings.SCHEMA_INDEX_VERSION
        assert meta["chunk_index"] == i
        assert meta["chunk_total"] == 4

    assert [m["column"] for m in added["metadatas"]] == ["", "id", "name", "created_at"]

    # 重新索引前清理旧 chunk（幂等保证）
    m_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_index_table_empty_schema_is_noop():
    """空 schema 不写入任何向量。"""
    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.delete_where", AsyncMock()) as m_delete,
        patch("app.agent.schema_link.add_documents", AsyncMock()) as m_add,
    ):
        count = await SchemaLinker().index_table("users", "")

    assert count == 0
    m_add.assert_not_awaited()
    m_delete.assert_not_awaited()


# ============================================================
# 检索：元数据不被丢弃
# ============================================================

def test_rebuild_schema_text_sorts_by_chunk_index():
    """``collection.get()`` 乱序返回时，按 chunk_index 还原出原始表结构。"""
    chunks = split_schema_into_chunks(SCHEMA_TEXT, "users")
    shuffled = {
        "documents": [c.text for c in reversed(chunks)],
        "metadatas": [
            {"chunk_index": i} for i in reversed(range(len(chunks)))
        ],
    }

    rebuilt = SchemaLinker._rebuild_schema_text(shuffled)

    # 还原结果应当逐字节等于原始表结构文本
    assert rebuilt == SCHEMA_TEXT


def test_rebuild_schema_text_empty():
    assert SchemaLinker._rebuild_schema_text({"documents": [], "metadatas": []}) == ""


@pytest.mark.asyncio
async def test_retrieve_uses_metadata_to_regroup_tables():
    """召回的是 chunk，但返回的必须是还原后的完整表结构。"""
    recalled = {
        "documents": ["  amount(decimal)"],
        "metadatas": [
            {"table": "orders", "version": "1.0", "column": "amount", "chunk_index": 1},
        ],
        "distances": [0.05],
        "ids": ["schema:orders:1"],
    }
    full_orders = {
        "documents": ["  amount(decimal)", "表 orders:", "  id(bigint PK)"],
        "metadatas": [
            {"table": "orders", "chunk_index": 1},
            {"table": "orders", "chunk_index": 0},
            {"table": "orders", "chunk_index": 2},
        ],
    }

    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.embed_texts", AsyncMock(return_value=[[0.1] * 1024])),
        patch("app.agent.schema_link.query_similar", AsyncMock(return_value=recalled)),
        patch("app.agent.schema_link.get_where", AsyncMock(return_value=full_orders)) as m_get,
    ):
        texts = await SchemaLinker().retrieve("订单金额", top_k=3)

    # 不是返回命中的那一行 chunk，而是整张表（按 chunk_index 还原顺序）
    assert texts == ["表 orders:\n  amount(decimal)\n  id(bigint PK)"]

    # 元数据里的表名被用于第二阶段查询
    where = m_get.await_args.args[1]
    assert {"table": "orders"} in where["$and"]


@pytest.mark.asyncio
async def test_retrieve_dedupes_tables_and_keeps_relevance_order():
    """同一张表命中多个 chunk 时只算一张表，且按首次命中顺序排列。"""
    recalled = {
        "documents": ["a", "b", "c"],
        "metadatas": [
            {"table": "orders"},
            {"table": "users"},
            {"table": "orders"},  # 与第 1 条同表 → 去重
        ],
        "distances": [0.1, 0.2, 0.3],
        "ids": ["1", "2", "3"],
    }

    async def fake_get(collection, where):
        table = next(c["table"] for c in where["$and"] if "table" in c)
        return {
            "documents": [f"表 {table}:"],
            "metadatas": [{"table": table, "chunk_index": 0}],
        }

    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.embed_texts", AsyncMock(return_value=[[0.1] * 1024])),
        patch("app.agent.schema_link.query_similar", AsyncMock(return_value=recalled)),
        patch("app.agent.schema_link.get_where", fake_get),
    ):
        texts = await SchemaLinker().retrieve("问题", top_k=5)

    assert texts == ["表 orders:", "表 users:"]


@pytest.mark.asyncio
async def test_retrieve_returns_empty_when_no_version_match():
    """向量库无匹配（如版本失效）时返回空，由调用方走兜底扫描。"""
    empty = {"documents": [], "metadatas": [], "distances": [], "ids": []}

    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.embed_texts", AsyncMock(return_value=[[0.1] * 1024])),
        patch("app.agent.schema_link.query_similar", AsyncMock(return_value=empty)),
        patch.object(
            SchemaLinker, "_retrieve_by_scan", AsyncMock(return_value=["兜底"]),
        ) as m_scan,
    ):
        texts = await SchemaLinker().retrieve("问题", top_k=3)

    assert texts == ["兜底"]
    m_scan.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_filters_by_current_version():
    """检索时带上版本过滤条件，旧版本向量不会被召回。"""
    with (
        patch("app.agent.schema_link.get_table_schemas_collection", MagicMock()),
        patch("app.agent.schema_link.embed_texts", AsyncMock(return_value=[[0.1] * 1024])),
        patch("app.agent.schema_link.query_similar", AsyncMock(return_value={
            "documents": [], "metadatas": [], "distances": [], "ids": [],
        })) as m_query,
        patch.object(SchemaLinker, "_retrieve_by_scan", AsyncMock(return_value=[])),
    ):
        await SchemaLinker().retrieve("问题", top_k=3)

    assert m_query.await_args.kwargs["where"] == {
        "version": settings.SCHEMA_INDEX_VERSION,
    }
