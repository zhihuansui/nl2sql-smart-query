"""
SQL 企业级智能数据分析助手 — 后端入口
基于 FastAPI + LangChain（LLM 调用层）
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.init_data import index_all_table_schemas, sync_golden_examples_to_chroma
from app.api.router import api_router
from app.config import settings
from app.db.engine import init_db
from app.vector_store.chroma_client import init_vector_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（启动时初始化数据库和向量存储，关闭时清理）"""
    # --- 启动时 ---
    print(f"[APP] Starting — env={settings.APP_ENV}, llm={settings.LLM_PROVIDER}")
    try:
        await init_db()
        print("[DB] Meta database tables initialized")
    except Exception as e:
        print(f"[DB] Meta database initialization failed: {e!s}")

    try:
        await init_vector_store()
        print("[Vector] Chroma collections initialized")
    except Exception as e:
        print(f"[Vector] Chroma initialization failed: {e!s}")

    try:
        table_count = await index_all_table_schemas()
        print(f"[Vector] Table schemas indexed: {table_count} tables")
    except Exception as e:
        print(f"[Vector] Table schema indexing failed: {e!s}")

    try:
        example_count = await sync_golden_examples_to_chroma()
        print(f"[Vector] Golden examples synced: {example_count} examples")
    except Exception as e:
        print(f"[Vector] Golden example sync failed: {e!s}")

    yield

    # --- 关闭时 ---
    print("[APP] Shutting down gracefully")


app = FastAPI(
    title="SQL Smart Query Agent",
    description="基于 LLM 的 NL2SQL 企业级智能数据分析助手",
    version="1.0.0",
    lifespan=lifespan,
)

# === CORS 中间件 ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 挂载路由 ===
app.include_router(api_router)


@app.get("/")
async def root():
    return {"message": "SQL Smart Query Agent is running", "version": "1.0.0"}
