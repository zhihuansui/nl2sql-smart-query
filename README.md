# SQL 企业级智能数据分析助手

基于 **LangChain ReAct Agent** 的企业级智能数据查询平台。用户输入自然语言，系统自动完成 NL → SQL 转换、安全风控、查询执行、结果可视化全链路。

---

## 目录

- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [Docker 部署](#docker-部署)
- [API 文档](#api-文档)
- [测试](#测试)
- [项目结构](#项目结构)

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Frontend (React 18)                       │
│  ┌────────────────┐  ┌─────────────────────────────────────────┐   │
│  │ DataSourcePanel│  │             ChatPanel                   │   │
│  │  · 表列表       │  │  ┌──────────┐ ┌──────────┐ ┌────────┐ │   │
│  │  · 字段详情弹窗  │  │  │Message   │ │Message   │ │Result  │ │   │
│  │                 │  │  │Bubble    │ │Bubble    │ │Table   │ │   │
│  └────────┬────────┘  │  └──────────┘ └──────────┘ └────────┘ │   │
│           │           │  ┌──────────────────────────────────┐  │   │
│           │           │  │          ChatInput               │  │   │
│           │           │  └──────────────────────────────────┘  │   │
│           │           └─────────────────────────────────────────┘   │
│           │                                                         │
│           └─────────────── HistoryDrawer ──────────────────────────  │
│                               · 会话列表                              │
│                               · 加载/删除/新建                        │
└─────────────────────────────────────────────────────────────────────┘
                               │  HTTP/SSE
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Backend (FastAPI)                           │
│                                                                     │
│  ┌──────────┐  ┌──────────────────────────────────────────────────┐ │
│  │  API      │  │              Agent Orchestrator                  │ │
│  │  Router   │  │                                                  │ │
│  │  /query───┼──┤  Intent ─→ SchemaLink ─→ FewShot ─→ Prompt     │ │
│  │  /sessions│  │       → ReAct Loop ─→ SQL Guard ─→ RLS        │ │
│  │  /tables  │  │       → Executor ─→ Explainer                  │ │
│  │  /examples│  └──────────────────────────────────────────────────┘ │
│  │  /health  │                          │                            │
│  └──────────┘                          │                            │
│        │                               │                            │
│        ▼                               ▼                            │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐    │
│  │  Meta DB     │  │  Target DB   │  │  Vector Store (Chroma) │    │
│  │  (SQLite)    │  │  (MySQL/PG)  │  │  · table_schemas       │    │
│  │  · sessions  │  │              │  │  · golden_examples     │    │
│  │  · history   │  │              │  └────────────────────────┘    │
│  │  · examples  │  │              │                                │
│  └──────────────┘  └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  LLM (DeepSeek/OpenAI)│
                    └─────────────────────┘
```

### 核心流程

| 步骤 | 模块 | 说明 |
| :--- | :--- | :--- |
| 1. 意图识别 | `orchestrator.py` | 关键词启发式判断是否为数据查询 |
| 2. Schema Linking | `schema_link.py` | Chroma 向量检索相关表结构 |
| 3. Few-Shot 检索 | `few_shot.py` | 检索语义相似的问题-SQL 示例 |
| 4. Prompt 组装 | `prompt_builder.py` | 按 SPEC 4.3 模板构建 System Prompt |
| 5. ReAct Agent | `loop.py` | LangChain ReAct Agent 生成 SQL |
| 6. 安全护栏 | `guard.py` | 正则 + AST 双检拦截危险操作 |
| 7. RLS 注入 | `rls.py` | 按用户策略追加行级权限条件 |
| 8. SQL 执行 | `executor.py` | 只读 SELECT 执行（max 200 行） |
| 9. 白话解释 | `explainer.py` | LLM 将 SQL 翻译为业务中文 |
| 10. SSE 推送 | `query.py` | 流式推送各步骤状态和最终结果 |

---

## 技术栈

| 层级 | 技术 |
| :--- | :--- |
| **前端** | React 18 + TypeScript + Ant Design 5 + Vite |
| **后端** | Python 3.10+ / FastAPI |
| **AI 框架** | LangChain >= 0.3.0 / ReAct Agent |
| **数据库** | MySQL 8.0 / PostgreSQL 15（生产） / SQLite（开发） |
| **向量存储** | Chroma（1536-dim, cosine） |
| **LLM** | DeepSeek-V3（默认）/ GPT-4o（备选） |
| **Embedding** | OpenAI text-embedding-3-small |
| **容器化** | Docker + Docker Compose |

---

## 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose（可选）

### 1. 克隆 & 配置

```bash
# 环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY 和数据库连接信息
```

### 2. 启动后端

```bash
cd backend

# 虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000/docs 查看 Swagger 文档。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000。

> Vite 开发服务器自动代理 `/api` 请求到 `localhost:8000`，无需额外配置 CORS。

### 4. 验证

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 查询测试（SSE 流式）
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "查询用户总数"}'
```

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| :--- | :---: | :--- | :--- |
| **运行环境** | | | |
| `APP_ENV` | 否 | `development` | `development` / `production` |
| **LLM 配置** | | | |
| `LLM_PROVIDER` | 否 | `deepseek` | LLM 厂商: `deepseek` / `openai` |
| `LLM_API_KEY` | **是** | — | API Key |
| `LLM_MODEL` | 否 | `deepseek-v3` | 主力模型名 |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | 自定义 API 端点 |
| **目标数据库** | | | |
| `TARGET_DB_TYPE` | **是** | `mysql` | `mysql` / `postgresql` / `sqlite` |
| `TARGET_DB_HOST` | **是** | `localhost` | 主机地址 |
| `TARGET_DB_PORT` | 否 | `3306` | 端口 |
| `TARGET_DB_NAME` | **是** | `business_db` | 数据库名 |
| `TARGET_DB_USER` | **是** | `readonly_user` | 用户名（建议只读账号） |
| `TARGET_DB_PASS` | **是** | — | 密码 |
| **系统元数据库** | | | |
| `META_DB_URL` | 否 | `sqlite:///./data/meta.db` | SQLAlchemy 连接 URL |
| **向量存储** | | | |
| `CHROMA_PERSIST_DIR` | 否 | `./data/chroma` | 本地持久化目录 |
| `CHROMA_HOST` | 否 | `""` | HTTP 模式时填地址（空=本地） |
| `CHROMA_PORT` | 否 | `8001` | HTTP 端口 |
| **Embedding** | | | |
| `EMBEDDING_MODEL` | 否 | `text-embedding-3-small` | 模型名 |
| `EMBEDDING_API_KEY` | **是** | — | Embedding API Key |
| **连接池** | | | |
| `DB_POOL_SIZE` | 否 | `30` | 目标数据库连接池大小 |
| `DB_POOL_IDLE_TIMEOUT` | 否 | `300` | 空闲连接回收秒数 |
| **CORS** | | | |
| `CORS_ORIGINS` | 否 | `["http://localhost:3000"]` | 允许的前端来源 |

---

## Docker 部署

### 一键启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY、数据库连接等

# 2. 构建并启动所有服务
docker compose up -d

# 3. 查看日志
docker compose logs -f backend

# 4. 停止
docker compose down
```

服务映射：

| 服务 | 地址 |
| :--- | :--- |
| 后端 API | `http://localhost:8000` |
| Swagger 文档 | `http://localhost:8000/docs` |
| Chroma 服务 | `http://localhost:8001` |

### 单独构建

```bash
# 后端镜像
docker build -t sql-agent-backend ./backend

# 启动
docker run -p 8000:8000 --env-file .env sql-agent-backend
```

### docker-compose.yml

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [chroma]
    volumes: [./data:/app/data]

  chroma:
    image: chromadb/chroma:latest
    ports: ["8001:8000"]
    volumes: [./data/chroma:/chroma/chroma]
```

---

## API 文档

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/` | 根路径，返回运行状态 |
| `GET` | `/api/v1/health` | 深度健康检查（4 组件） |
| `POST` | `/api/v1/query` | **SSE 流式** — 提交自然语言查询 |
| `GET` | `/api/v1/sessions` | 分页会话列表 |
| `GET` | `/api/v1/sessions/{id}` | 会话详情 + 查询历史 |
| `DELETE` | `/api/v1/sessions/{id}` | 删除会话（CASCADE） |
| `GET` | `/api/v1/tables` | 目标数据库表概览 |
| `GET` | `/api/v1/tables/{name}` | 单表字段定义 |
| `GET` | `/api/v1/examples` | 黄金示例列表 |
| `POST` | `/api/v1/examples` | 新增黄金示例（自动向量化） |
| `DELETE` | `/api/v1/examples/{id}` | 删除示例（清理向量） |

### SSE 事件格式

`POST /api/v1/query` 返回 `text/event-stream`，事件类型：

```
event: status        # 中间状态
data: {"state": "thinking", "message": "..."}

event: result        # 查询成功
data: {"status": "success", "sql": "...", "columns": [...], "rows": [...], ...}

event: error         # 查询失败/拦截
data: {"status": "failed|blocked|rejected", "message": "..."}
```

---

## 测试

### 后端测试

```bash
cd backend

# 安装测试依赖
pip install pytest pytest-asyncio

# 运行安全模块测试
pytest tests/test_guard.py -v
pytest tests/test_rls.py -v

# 运行 Agent 编排集成测试
pytest tests/test_agent_loop.py -v --asyncio-mode=auto

# 运行全部测试
pytest tests/ -v --asyncio-mode=auto
```

覆盖的测试场景：

| 文件 | 用例数 | 覆盖范围 |
| :--- | :--- | :--- |
| `test_guard.py` | 52 | 正常 SQL、DDL/DML 拦截、多语句、时间注入、边缘 case |
| `test_rls.py` | 26 | 单表 JOIN、子句顺序、别名、无匹配策略 |
| `test_agent_loop.py` | 11 | 全链路成功、意图拒绝、SQL Guard 拦截、重试耗尽、RLS 注入、事件顺序、Session 创建 |

### E2E 测试（Playwright）

```bash
# 安装 Playwright
npx playwright install chromium

# 确保后端和前端均已启动，然后运行
npx playwright test e2e/query_flow.spec.ts

# 使用 UI 模式交互调试
npx playwright test --ui
```

覆盖流程：页面布局 → 数据源面板加载 → 字段详情弹窗 → SSE 流式查询 → 结果表格 → SQL 复制 → 历史抽屉 → 新建会话 → 面板折叠。

---

## 项目结构

```
├── backend/                         # Python 后端（FastAPI）
│   ├── app/
│   │   ├── main.py                 # 应用入口（lifespan 初始化）
│   │   ├── config.py               # Pydantic Settings
│   │   ├── api/                    # REST API 路由层 (SPEC 第3章)
│   │   │   ├── router.py           # 路由汇总 /api/v1
│   │   │   ├── query.py            # POST /query SSE 流式
│   │   │   ├── sessions.py         # 会话 CRUD
│   │   │   ├── tables.py           # 表元数据
│   │   │   ├── examples.py         # 黄金示例 CRUD
│   │   │   └── health.py           # 深度健康检查
│   │   ├── agent/                  # Agent 编排引擎 (SPEC 第4章)
│   │   │   ├── orchestrator.py     # 全链路编排
│   │   │   ├── schema_link.py      # 向量检索表结构
│   │   │   ├── few_shot.py         # 向量检索示例
│   │   │   ├── prompt_builder.py   # System Prompt 组装
│   │   │   ├── tools.py            # LangChain 工具定义
│   │   │   └── loop.py             # ReAct Agent 执行循环
│   │   ├── security/               # 安全风控 (SPEC 4.4-4.5)
│   │   │   ├── guard.py            # SQL 护栏（正则+AST）
│   │   │   └── rls.py              # 行级权限注入
│   │   ├── db/                     # 数据库层
│   │   │   ├── engine.py           # Meta DB 异步引擎
│   │   │   ├── models.py           # ORM 模型（4 张表）
│   │   │   ├── executor.py         # 目标库只读执行器
│   │   │   └── metadata.py         # 元数据扫描器（多方言）
│   │   ├── llm/                    # LLM 抽象层
│   │   │   ├── provider.py         # 模型工厂
│   │   │   └── explainer.py        # 白话解释器
│   │   └── vector_store/           # 向量存储 (SPEC 2.2)
│   │       ├── chroma_client.py    # Chroma 异步封装
│   │       └── embedder.py         # Embedding 计算
│   ├── tests/                      # 后端测试
│   │   ├── conftest.py             # 共享 fixtures（mock LLM/DB...）
│   │   ├── test_guard.py           # SQL Guard 52 用例
│   │   ├── test_rls.py             # RLS 26 用例
│   │   └── test_agent_loop.py      # Agent 集成测试 11 用例
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/                       # React 前端 (SPEC 第5章)
│   ├── src/
│   │   ├── main.tsx               # 入口（Ant Design ConfigProvider）
│   │   ├── App.tsx                 # 三栏布局
│   │   ├── services/api.ts        # API 服务层 + SSE 流解析
│   │   ├── hooks/
│   │   │   ├── useChatReducer.tsx  # Context + useReducer 状态管理
│   │   │   └── useQuerySSE.ts      # SSE 查询 hook
│   │   └── components/
│   │       ├── DataSourcePanel.tsx # 表列表 + 字段弹窗
│   │       ├── ChatPanel.tsx       # 消息面板
│   │       ├── ChatInput.tsx       # 输入框
│   │       ├── MessageBubble.tsx   # 消息气泡
│   │       ├── ResultTable.tsx     # 结果表格
│   │       ├── SQLBlock.tsx        # SQL 代码块
│   │       └── HistoryDrawer.tsx   # 历史抽屉
│   ├── package.json
│   ├── vite.config.ts              # Vite 配置（含代理）
│   └── tsconfig.json
├── e2e/                            # Playwright E2E 测试
│   ├── playwright.config.ts
│   └── query_flow.spec.ts          # 10 个核心用户场景
├── docker-compose.yml              # 服务编排
├── .env.example                    # 环境变量模板
└── README.md
```

---

## License

MIT
