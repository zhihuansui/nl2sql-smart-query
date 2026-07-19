"""
pytest 共享 Fixtures — 为全链路测试提供 mock 环境和数据。

Run::

    cd backend
    pip install pytest pytest-asyncio
    pytest tests/ -v
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Session


# ============================================================
# 内存 SQLite 元数据库
# ============================================================

@pytest.fixture(scope="session")
def event_loop():
    """为 async fixture 提供事件循环（session scope）。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def meta_engine():
    """创建内存 SQLite 引擎。"""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def meta_session(meta_engine) -> AsyncGenerator[AsyncSession, None]:
    """提供干净的 AsyncSession（每测试独立）。"""
    factory = async_sessionmaker(bind=meta_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
        await session.close()


# ============================================================
# Agent / Orchestrator  Mock 工具
# ============================================================

@pytest.fixture
def mock_schema_linker():
    """Mock SchemaLinker.retrieve() 返回固定表结构。"""
    with patch("app.agent.orchestrator.SchemaLinker") as mock:
        instance = mock.return_value
        instance.retrieve = AsyncMock(return_value=[
            "表 users: id(bigint PK), name(varchar), created_at(datetime)",
            "表 orders: id(bigint PK), user_id(bigint FK), amount(decimal), created_at(datetime)",
        ])
        yield instance


@pytest.fixture
def mock_few_shot():
    """Mock FewShotRetriever.retrieve() 返回示例。"""
    with patch("app.agent.orchestrator.FewShotRetriever") as mock:
        instance = mock.return_value
        instance.retrieve = AsyncMock(return_value=[
            {
                "question": "查询用户总数",
                "sql": "SELECT COUNT(*) FROM users",
                "tables": ["users"],
                "tags": ["聚合"],
            },
        ])
        yield instance


@pytest.fixture
def mock_agent_loop():
    """Mock AgentLoop.run() 直接返回固定 SQL，跳过大模型调用。"""
    with patch("app.agent.orchestrator.AgentLoop") as mock:
        instance = mock.return_value
        instance.run = AsyncMock(return_value={
            "sql": "SELECT COUNT(*) FROM users WHERE created_at >= '2026-07-01'",
            "raw_output": "I will count users since July.\n```sql\nSELECT COUNT(*) FROM users WHERE created_at >= '2026-07-01'\n```",
            "success": True,
            "error": None,
        })
        yield instance


@pytest.fixture
def mock_executor():
    """Mock TargetDBExecutor.execute() 返回固定查询结果。"""
    with patch("app.agent.orchestrator.TargetDBExecutor") as mock:
        instance = mock.return_value
        instance.execute = AsyncMock(return_value={
            "columns": ["COUNT(*)"],
            "rows": [[42]],
            "total_count": 1,
            "execution_ms": 15,
        })
        yield instance


@pytest.fixture
def mock_explainer():
    """Mock Explainer.generate() 返回固定中文解释。"""
    with patch("app.agent.orchestrator.Explainer") as mock:
        instance = mock.return_value
        instance.generate = AsyncMock(return_value="我理解您的需求是：统计2026年7月后注册的用户总数。")
        yield instance


@pytest.fixture
def mock_vector_store():
    """Mock Chroma 相关调用（embedder + chroma_client）。"""
    patches = [
        patch("app.agent.schema_link.embed_text", AsyncMock(return_value=[0.1] * 1536)),
        patch("app.agent.schema_link.query_similar", AsyncMock(return_value={
            "documents": ["表 users: id(bigint PK), name(varchar)"],
            "metadatas": [{}],
            "distances": [0.1],
            "ids": ["schema:users"],
        })),
        patch("app.agent.few_shot.embed_text", AsyncMock(return_value=[0.1] * 1536)),
        patch("app.agent.few_shot.query_similar", AsyncMock(return_value={
            "documents": ["查询用户总数"],
            "metadatas": [{"sql": "SELECT COUNT(*) FROM users"}],
            "distances": [0.1],
            "ids": ["example:abc"],
        })),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
