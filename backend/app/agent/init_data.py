"""
启动时数据初始化 — 将目标数据库表结构与 MySQL 黄金示例
自动同步到 Chroma 向量库。

在 ``main.py`` 的 lifespan startup 阶段调用：
    await init_vector_store()
    await index_all_table_schemas()
    await sync_golden_examples_to_chroma()
"""

from __future__ import annotations

from sqlalchemy import select

from app.agent.few_shot import FewShotRetriever
from app.agent.schema_link import SchemaLinker
from app.config import settings
from app.db.engine import async_session_factory
from app.db.metadata import MetadataScanner
from app.db.models import GoldenExample


async def index_all_table_schemas() -> int:
    """扫描目标数据库的全部表，逐行切分向量化后写入 Chroma ``table_schemas`` 集合。

    每行数据（表头行 + 每个字段一行）是一个独立 chunk，附带表名、版本等元数据。
    ``index_table`` 内部会先清理该表的旧 chunk，因此重复启动是幂等的。

    Returns:
        成功索引的表数量。目标库不可达时返回 0。
    """
    scanner = MetadataScanner()
    linker = SchemaLinker()
    indexed = 0
    chunk_total = 0

    try:
        tables = await scanner.get_all_tables()
    except Exception as e:
        print(f"[Init] 目标数据库扫描失败，跳过表结构索引: {e!s}")
        await scanner.close()
        return 0

    for table in tables:
        table_name = table.get("name", "")
        if not table_name:
            continue

        try:
            schema_text = await scanner.get_table_schema_text(table_name)
        except Exception as e:
            print(f"[Init] 读取表 {table_name} 结构失败: {e!s}")
            continue

        if not schema_text:
            continue

        try:
            chunk_total += await linker.index_table(
                table_name=table_name,
                schema_text=schema_text,
            )
            indexed += 1
        except Exception as e:
            print(f"[Init] 表 {table_name} 向量化失败（Embedding/Ollama 不可用？）: {e!s}")

    await scanner.close()
    print(
        f"[Init] 表结构向量化完成: {indexed}/{len(tables)} 张表, "
        f"{chunk_total} 个 chunk (版本 {settings.SCHEMA_INDEX_VERSION})"
    )
    return indexed


async def sync_golden_examples_to_chroma() -> int:
    """将 MySQL ``golden_examples`` 表中的全部记录同步到 Chroma。

    doc_id 使用 example 主键，重复执行时自动覆盖。

    Returns:
        同步的示例数量。MySQL 为空或不可达时返回 0。
    """
    retriever = FewShotRetriever()
    synced = 0

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(GoldenExample))
            examples = result.scalars().all()
    except Exception as e:
        print(f"[Init] 黄金示例 MySQL 读取失败，跳过同步: {e!s}")
        return 0

    if not examples:
        print("[Init] 无黄金示例需要同步（golden_examples 表为空）")
        return 0

    for ex in examples:
        try:
            await retriever.index_example(
                question=ex.question,
                sql=ex.sql,
                doc_id=str(ex.id),
                tables=ex.tables_used or [],
                tags=ex.tags or [],
            )
            synced += 1
        except Exception as e:
            print(f"[Init] 示例 {ex.id} 向量化失败: {e!s}")

    print(f"[Init] 黄金示例同步完成: {synced}/{len(examples)} 条")
    return synced
