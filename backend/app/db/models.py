"""
SQLAlchemy ORM 模型 — 系统元数据库

按 SPEC 2.1 节设计，包含四张表：
- sessions        — 会话表
- query_history   — 查询历史表
- golden_examples — 黄金示例库
- db_connections  — 数据源配置表
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ─── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


# ─── Enums ────────────────────────────────────────────────────────────────────

class QueryStatus(str, enum.Enum):
    """查询执行状态。"""
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


class DBType(str, enum.Enum):
    """支持的数据库类型。"""
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"


# ─── Helper ───────────────────────────────────────────────────────────────────

def _new_uuid() -> str:
    """生成 UUID 字符串主键。"""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """当前 UTC 时间。"""
    return datetime.utcnow()


# ─── Session ──────────────────────────────────────────────────────────────────

class Session(Base):
    """
    会话表。

    记录用户对话会话，每条会话包含多次查询（由 QueryHistory 关联）。
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid,
    )
    title: Mapped[str] = mapped_column(
        String(200), default="新会话",
        comment="自动从首条问题截取",
    )
    user_id: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="登录用户 ID（预留）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow,
        comment="更新时间",
    )

    # ── 关联 ──
    history: Mapped[list[QueryHistory]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id!r} title={self.title!r}>"


# ─── QueryHistory ─────────────────────────────────────────────────────────────

class QueryHistory(Base):
    """
    查询历史表。

    记录每次查询的完整信息：用户问题、生成的 SQL、执行结果、
    白话解释、耗时、重试次数等。
    """

    __tablename__ = "query_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → sessions.id",
    )
    user_question: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="用户原始问题",
    )
    generated_sql: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Agent 最终生成的 SQL",
    )
    executed_sql: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="实际执行的 SQL（含 RLS 注入）",
    )
    explanation: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="白话解释",
    )
    result_columns: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="查询结果列名，如 ['cnt', 'name']",
    )
    result_rows: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="查询结果行数据（前端展示用，最多 200 行）",
    )
    total_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="总行数（含截断的）",
    )
    status: Mapped[QueryStatus] = mapped_column(
        SAEnum(QueryStatus, validate_strings=True),
        default=QueryStatus.SUCCESS,
        comment="状态：success / failed / blocked",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="失败原因（如有）",
    )
    execution_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="执行耗时（毫秒）",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="重试次数",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        comment="创建时间",
    )

    # ── 关联 ──
    session: Mapped[Session] = relationship(back_populates="history")

    def __repr__(self) -> str:
        return (
            f"<QueryHistory id={self.id!r} "
            f"status={self.status.value!r} "
            f"created_at={self.created_at!r}>"
        )


# ─── GoldenExample ────────────────────────────────────────────────────────────

class GoldenExample(Base):
    """
    黄金示例库。

    高质量的问题-SQL 对，用于动态 Few-Shot 注入。
    每条记录对应 Chroma 中的一条向量。
    """

    __tablename__ = "golden_examples"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid,
    )
    question: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="自然语言问题",
    )
    sql: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="标准 SQL 答案",
    )
    tables_used: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="涉及的表名数组，如 ['users', 'orders']",
    )
    tags: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="标签，如 ['聚合', 'JOIN', '时间范围']",
    )
    embedding_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Chroma 中的向量 ID",
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="DBA 审核人",
    )
    usage_count: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="被检索为 Few-Shot 的次数",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"<GoldenExample id={self.id!r} "
            f"usage_count={self.usage_count}>"
        )


# ─── DBConnection ─────────────────────────────────────────────────────────────

class DBConnection(Base):
    """
    数据源配置表。

    管理目标数据库连接信息，密码加密存储。
    支持同时管理多个数据源。
    """

    __tablename__ = "db_connections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid,
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="连接名称（展示用）",
    )
    db_type: Mapped[DBType] = mapped_column(
        SAEnum(DBType, validate_strings=True),
        nullable=False,
        comment="数据库类型：mysql / postgresql / sqlite",
    )
    host: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="主机地址",
    )
    port: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="端口号",
    )
    database_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="数据库名",
    )
    username: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="用户名",
    )
    password_enc: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="加密存储的密码",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="是否启用",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow,
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"<DBConnection id={self.id!r} "
            f"name={self.name!r} "
            f"type={self.db_type.value if isinstance(self.db_type, DBType) else self.db_type}>"
        )
