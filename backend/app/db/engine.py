"""
异步 SQLAlchemy 引擎与会话工厂。

从 META_DB_URL 环境变量创建 async engine，自动处理 SQLite
（注入 aiosqlite 驱动）。提供 FastAPI 依赖注入函数。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.models import Base


# ─── Engine ───────────────────────────────────────────────────────────────────

def _build_async_connection_string() -> str:
    """将配置文件中的数据库 URL 转为异步版本。

    SQLite 需要 ``sqlite+aiosqlite`` 驱动前缀，
    而 MySQL / PostgreSQL 通常已有异步驱动，直接返回。
    """
    url = settings.META_DB_URL

    if url.startswith("sqlite://"):
        # sqlite:///./data/meta.db → sqlite+aiosqlite:///./data/meta.db
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    # MySQL: 预期用户已在 URL 中使用 aiomysql 或 asyncmy
    # PostgreSQL: 预期使用 asyncpg
    return url


engine = create_async_engine(
    _build_async_connection_string(),
    echo=(settings.APP_ENV == "development"),
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    pool_recycle=settings.DB_POOL_IDLE_TIMEOUT,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── Public API ───────────────────────────────────────────────────────────────

async def init_db() -> None:
    """创建所有 ORM 表。

    应在应用启动时（FastAPI lifespan）调用一次。
    对于 SQLite，此操作等效于执行 ``CREATE TABLE IF NOT EXISTS``。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入 —— 提供异步数据库会话。

    Yields:
        一个 AsyncSession 实例。
        请求完成后自动 commit； 发生异常时 rollback。

    Usage::

        @router.get("/items")
        async def list_items(session: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
