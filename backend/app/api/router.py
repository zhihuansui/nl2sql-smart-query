"""
API 路由汇总 — 聚合所有子路由模块到统一的路由器。

挂载路径: /api/v1
"""

from fastapi import APIRouter

from .examples import router as examples_router
from .health import router as health_router
from .query import router as query_router
from .sessions import router as sessions_router
from .tables import router as tables_router


api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health_router)      # GET /api/v1/health
api_router.include_router(query_router)       # POST /api/v1/query
api_router.include_router(sessions_router)    # GET|DELETE /api/v1/sessions
api_router.include_router(tables_router)      # GET /api/v1/tables, /api/v1/tables/{name}
api_router.include_router(examples_router)    # GET|POST|DELETE /api/v1/examples
