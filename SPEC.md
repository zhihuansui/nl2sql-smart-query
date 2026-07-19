# SQL 企业级智能数据分析助手 — 技术规格说明书（SPEC）

| 版本 | 日期    | 作者 |
| :--- | :------ | :--- |
| v1.0 | 2026-07 | zhh  |

---

## 1. 系统架构总览

### 1.1 架构图（文字描述）

```
┌─────────────────────────────────────────────────────┐
│                    前端层 (React 18)                   │
│  ┌──────────┐  ┌────────────┐  ┌─────────────────┐  │
│  │ 对话面板  │  │ 数据源面板   │  │ 历史记录面板     │  │
│  └────┬─────┘  └─────┬──────┘  └───────┬─────────┘  │
│       │              │                  │             │
│  ┌────┴──────────────┴──────────────────┴─────────┐  │
│  │              API Service Layer (axios)          │  │
│  └───────────────────────┬────────────────────────┘  │
└──────────────────────────┼───────────────────────────┘
                           │ REST / SSE (流式)
┌──────────────────────────┼───────────────────────────┐
│                    后端层 (FastAPI)                    │
│  ┌───────────────────────┴────────────────────────┐  │
│  │              API Router (v1/)                   │  │
│  │  /query  /history  /tables  /health            │  │
│  └───────────────────────┬────────────────────────┘  │
│                          │                            │
│  ┌───────────────────────┴────────────────────────┐  │
│  │           Agent Orchestrator                   │  │
│  │  ┌──────────┐  ┌────────┐  ┌──────────────┐   │  │
│  │  │ Schema   │  │ ReAct  │  │ SQL Guard    │   │  │
│  │  │ Link     │  │ Loop   │  │ (安全护栏)    │   │  │
│  │  └────┬─────┘  └───┬────┘  └──────┬───────┘   │  │
│  └───────┼────────────┼──────────────┼────────────┘  │
│          │            │              │                │
│  ┌───────┴────────────┴──────────────┴────────────┐  │
│  │            服务层                               │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐   │  │
│  │  │ SQL      │ │ Vector   │ │ LLM          │   │  │
│  │  │ Executor │ │ Store    │ │ Provider     │   │  │
│  │  │          │ │ (Chroma) │ │ (DeepSeek/   │   │  │
│  │  │          │ │          │ │  GPT-4o)     │   │  │
│  │  └──────────┘ └──────────┘ └──────────────┘   │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────┴───┐   ┌───┴────┐  ┌───┴────┐
         │ MySQL  │   │ Chroma │  │ LLM    │
         │ (业务)  │   │ DB     │  │ API    │
         └────────┘   └────────┘  └────────┘
```

### 1.2 技术选型明细

| 层级 | 技术 | 版本 | 用途 |
| :--- | :--- | :--- | :--- |
| 前端框架 | React | 18.x | 整体 UI 框架 |
| UI 组件库 | Ant Design | 5.x | 表格、表单、弹窗、骨架屏 |
| HTTP 客户端 | axios | 1.x | API 请求 + 流式 SSE |
| 状态管理 | React Context + useReducer | - | 会话状态、查询历史 |
| 后端框架 | FastAPI | 0.110+ | REST API + SSE 流式响应 |
| Agent 框架 | LangChain | >= 0.3.0 | ReAct Agent 编排 |
| LLM 抽象 | langchain-openai / langchain-deepseek | - | 统一 LLM 调用接口 |
| SQL 工具包 | SQLAlchemy | 2.0+ | 数据库连接池、ORM |
| SQL 解析 | sqlparse | 0.5+ | SQL 类型检测（护栏） |
| 向量存储 | Chroma | - | 表结构 & Few-Shot 向量检索 |
| Embedding | text-embedding-3-small (OpenAI) | - | 文本向量化 |
| 数据库（生产） | MySQL 8.0 / PostgreSQL 15 | - | 业务目标数据库 |
| 数据库（开发） | SQLite | - | 本地开发测试 |
| Python 运行时 | Python | 3.10+ | 后端运行时 |

---

## 2. 数据库设计（系统元数据）

### 2.1 表结构

```sql
-- 会话表
CREATE TABLE sessions (
    id          VARCHAR(36) PRIMARY KEY,           -- UUID
    title       VARCHAR(200) DEFAULT '新会话',      -- 自动从首条问题截取
    user_id     VARCHAR(64) NOT NULL,              -- 登录用户 ID（预留）
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 查询历史表
CREATE TABLE query_history (
    id              VARCHAR(36) PRIMARY KEY,        -- UUID
    session_id      VARCHAR(36) NOT NULL,           -- FK → sessions.id
    user_question   TEXT NOT NULL,                  -- 用户原始问题
    generated_sql   TEXT,                           -- Agent 最终生成的 SQL
    executed_sql    TEXT,                           -- 实际执行的 SQL（含 RLS 注入）
    explanation     TEXT,                           -- 白话解释
    result_rows     JSON,                           -- 查询结果（前端展示用，最多 200 行）
    total_count     INT,                            -- 总行数（含截断的）
    status          ENUM('success','failed','blocked') DEFAULT 'success',
    error_message   TEXT,                           -- 失败原因（如有）
    execution_ms    INT,                            -- 执行耗时（毫秒）
    retry_count     TINYINT DEFAULT 0,             -- 重试次数
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 黄金示例库
CREATE TABLE golden_examples (
    id              VARCHAR(36) PRIMARY KEY,
    question        TEXT NOT NULL,                   -- 自然语言问题
    sql             TEXT NOT NULL,                   -- 标准 SQL 答案
    tables_used     JSON,                            -- 涉及的表名数组 ["users","orders"]
    tags            JSON,                            -- 标签 ["聚合","JOIN","时间范围"]
    embedding_id    VARCHAR(200),                    -- Chroma 中的向量 ID
    reviewed_by     VARCHAR(64),                     -- DBA 审核人
    usage_count     INT DEFAULT 0,                   -- 被检索次数
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 数据源配置表
CREATE TABLE db_connections (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,           -- 连接名称（展示用）
    db_type         ENUM('mysql','postgresql','sqlite') NOT NULL,
    host            VARCHAR(255),
    port            INT,
    database_name   VARCHAR(100),
    username        VARCHAR(100),
    password_enc    VARCHAR(500),                    -- 加密存储
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 Chroma 向量集合设计

| Collection 名称 | 存储内容 | Embedding 维度 | 索引方式 |
| :--- | :--- | :--- | :--- |
| `table_schemas` | 每张表的字段名+注释拼接文本 | 1536 | cosine |
| `golden_examples` | 问题文本的 embedding | 1536 | cosine |

---

## 3. API 接口规格

### 3.1 接口总览

| 方法 | 路径 | 说明 | 流式 |
| :--- | :--- | :--- | :--- |
| POST | `/api/v1/query` | 提交自然语言查询 | ✅ SSE |
| GET | `/api/v1/sessions` | 获取会话列表 | ❌ |
| GET | `/api/v1/sessions/{id}` | 获取某会话的查询历史 | ❌ |
| DELETE | `/api/v1/sessions/{id}` | 删除会话 | ❌ |
| GET | `/api/v1/tables` | 获取所有表概览 | ❌ |
| GET | `/api/v1/tables/{name}` | 获取某表完整字段 | ❌ |
| GET | `/api/v1/examples` | 获取黄金示例列表（管理后台） | ❌ |
| POST | `/api/v1/examples` | 新增黄金示例（管理后台） | ❌ |
| GET | `/api/v1/health` | 健康检查 + 数据库连通性 | ❌ |

### 3.2 核心接口详细定义

#### `POST /api/v1/query`（SSE 流式）

**Request Body:**
```json
{
  "question": "查询7月1日到7月18日注册的用户数量",
  "session_id": "uuid-xxxx"
}
```

> `session_id` 可选，不传则新建 session

**SSE 事件流（200 OK, text/event-stream）:**

```
event: status
data: {"state": "thinking", "message": "正在理解语义..."}

event: status
data: {"state": "schema_linking", "message": "正在检索表结构...", "tables": ["users"]}

event: status
data: {"state": "executing", "message": "正在执行查询..."}

event: result
data: {
  "status": "success",
  "session_id": "uuid-xxxx",
  "sql": "SELECT COUNT(*) AS cnt FROM users WHERE register_date BETWEEN '2026-07-01' AND '2026-07-18'",
  "explanation": "我理解您的需求是：统计2026年7月1日至7月18日期间注册的用户数量。",
  "columns": ["cnt"],
  "rows": [[1283]],
  "total_count": 1,
  "execution_ms": 340
}

event: error
data: {
  "status": "failed",
  "message": "当前查询较复杂，建议简化条件或联系 DBA 协助",
  "session_id": "uuid-xxxx"
}

event: error
data: {
  "status": "blocked",
  "message": "检测到删除意图，该操作已被拦截。如需清理数据，请联系 DBA 团队。",
  "session_id": "uuid-xxxx"
}
```

#### `GET /api/v1/tables`

**Response (200):**
```json
{
  "tables": [
    {
      "name": "users",
      "comment": "用户基本信息表",
      "row_count_approx": 120000,
      "column_count": 15
    },
    {
      "name": "orders",
      "comment": "订单主表",
      "row_count_approx": 850000,
      "column_count": 22
    }
  ]
}
```

#### `GET /api/v1/tables/{name}`

**Response (200):**
```json
{
  "name": "users",
  "comment": "用户基本信息表",
  "columns": [
    {
      "name": "id",
      "type": "bigint",
      "nullable": false,
      "comment": "用户唯一标识",
      "is_pk": true
    },
    {
      "name": "register_date",
      "type": "datetime",
      "nullable": true,
      "comment": "注册时间",
      "is_pk": false
    }
  ]
}
```

#### `GET /api/v1/health`

**Response (200):**
```json
{
  "status": "healthy",
  "db_connected": true,
  "db_type": "mysql",
  "db_version": "8.0.35",
  "chroma_connected": true,
  "llm_provider": "deepseek-v3"
}
```

---

## 4. 核心引擎模块设计

### 4.1 模块目录结构

```
backend/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置管理（环境变量）
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py            # 路由注册
│   │   ├── query.py             # POST /query（SSE）
│   │   ├── sessions.py          # GET/DELETE /sessions
│   │   ├── tables.py            # GET /tables
│   │   ├── examples.py          # GET/POST /examples
│   │   └── health.py            # GET /health
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py      # Agent 编排器（主入口）
│   │   ├── schema_link.py       # 向量检索表结构
│   │   ├── few_shot.py          # 动态 Few-Shot 检索
│   │   ├── prompt_builder.py    # Prompt 模板组装
│   │   ├── tools.py             # LangChain Tool 定义（sql_db_query等）
│   │   └── loop.py              # ReAct 纠错循环逻辑
│   ├── security/
│   │   ├── __init__.py
│   │   ├── guard.py             # SQL 护栏（正则+sqlparse）
│   │   └── rls.py               # 行级权限过滤器
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py            # SQLAlchemy 连接池
│   │   ├── models.py            # ORM 模型
│   │   └── metadata.py          # 目标库元数据扫描
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py          # LLM 工厂（DeepSeek/GPT-4o）
│   │   └── explainer.py         # SQL 白话解释
│   └── vector_store/
│       ├── __init__.py
│       ├── chroma_client.py     # Chroma 客户端封装
│       └── embedder.py          # Embedding 函数
└── tests/
    ├── test_query.py
    ├── test_guard.py
    ├── test_rls.py
    └── test_agent_loop.py
```

### 4.2 Agent 编排器核心流程（伪代码）

```python
# orchestrator.py
class QueryOrchestrator:
    MAX_RETRIES: int = 2
    TIMEOUT_SECONDS: int = 15

    async def execute(self, question: str, session_id: str) -> AsyncGenerator:
        """SSE 流式入口，逐个 yield 状态事件"""

        # 1. 意图识别
        yield StatusEvent("thinking", "正在理解语义...")
        if not self._is_data_query(question):
            yield StatusEvent("rejected", "未识别到数据查询意图...")
            return

        # 2. Schema Linking
        yield StatusEvent("schema_linking", "正在检索表结构...")
        schemas = await self.schema_linker.retrieve(question, top_k=3)
        few_shots = await self.few_shot.retrieve(question, top_k=2)

        # 3. 组装 Prompt
        system_prompt = self.prompt_builder.build(
            schemas=schemas,
            few_shots=few_shots,
            chat_history=self._get_history(session_id, last=2),
            rls_policy=self.rls.get_current_policy()  # 若有行级权限
        )

        # 4. ReAct 循环
        for attempt in range(self.MAX_RETRIES + 1):
            yield StatusEvent("executing" if attempt == 0 else "retrying",
                            f"正在执行查询...（第{attempt+1}次）")

            sql, error = await self._run_agent(system_prompt, question, self.TIMEOUT_SECONDS)

            if error is None:
                # 护栏检查
                if self.guard.is_dangerous(sql):
                    yield ErrorEvent("blocked", "检测到非查询类操作...")
                    return
                # 注入 RLS
                safe_sql = self.rls.inject(sql)
                # 执行
                rows, execution_ms = await self.sql_executor.run(safe_sql)
                # 白话解释
                explanation = await self.explainer.generate(question, safe_sql)
                # 存入历史
                self._save_history(session_id, question, sql, safe_sql, explanation, rows, execution_ms)
                yield ResultEvent("success", sql=sql, explanation=explanation, rows=rows, execution_ms=execution_ms)
                return
            else:
                # 将错误注入 system_prompt 交给下一轮
                system_prompt += f"\n[上次错误]: {error}"

        # 5. 全部重试失败 → 熔断
        yield ErrorEvent("failed", "当前查询较复杂，建议简化条件或联系 DBA 协助")

    async def _run_agent(self, system_prompt: str, question: str, timeout: int):
        """单次 Agent 调用，带超时熔断"""
        llm = self.llm_provider.get_model()
        tools = [SQLQueryTool(self.sql_executor), SchemaInfoTool(self.metadata)]
        agent = create_react_agent(llm, tools, system_prompt)
        try:
            result = await asyncio.wait_for(
                agent.ainvoke({"input": question}),
                timeout=timeout
            )
            sql = self._extract_sql(result["output"])
            return sql, None
        except asyncio.TimeoutError:
            return None, "查询超时"
        except Exception as e:
            return None, str(e)
```

### 4.3 Prompt 模板设计

```
## 角色
你是一个企业级 SQL 查询助手，帮助业务人员从数据库中提取数据。
严格遵守以下规则：
1. 仅生成 SELECT 语句，禁止任何 INSERT/UPDATE/DELETE/DROP/ALTER。
2. 只使用下方【可用表结构】中列出的表和字段，不确定字段时使用 SchemaInfoTool 查询。
3. 生成 SQL 前先思考：是否需要 JOIN、聚合、排序、LIMIT？
4. LIMIT 最大不超过 1000，若用户未指定，默认 LIMIT 200。
5. 输出时，在 ```sql 代码块内给出最终 SQL。

## 可用表结构
{schema_text}

## 参考示例
{few_shot_text}

## 对话历史（最近 2 轮）
{history_text}

## 行级权限策略（如有）
{rls_policy}

## 当前日期
{current_date}

## 用户问题
{question}
```

### 4.4 安全护栏设计

```python
# guard.py
import re
import sqlparse

DANGEROUS_KEYWORDS = [
    "DELETE", "DROP", "ALTER", "INSERT", "UPDATE",
    "TRUNCATE", "REPLACE", "CREATE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "INTO OUTFILE", "INTO DUMPFILE"
]

class SQLGuard:
    @staticmethod
    def is_dangerous(sql: str) -> tuple[bool, str]:
        """返回 (是否危险, 原因)"""
        upper_sql = sql.upper().strip()

        # 第一层：正则快速匹配高风险关键字
        for keyword in DANGEROUS_KEYWORDS:
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, upper_sql):
                return True, f"检测到 {keyword} 操作，该操作已被拦截"

        # 第二层：sqlparse 解析验证类型
        parsed = sqlparse.parse(sql)
        if parsed:
            stmt_type = parsed[0].get_type()
            if stmt_type != 'SELECT' and stmt_type != 'UNKNOWN':
                return True, f"检测到 {stmt_type} 语句，本系统仅支持 SELECT 查询"

        return False, ""
```

### 4.5 RLS（行级权限）注入设计

```python
# rls.py
class RowLevelSecurity:
    # 策略配置（企业版，可从 DB 读取）
    POLICIES = {
        "user_north": {"table": "orders", "clause": "region = 'North'"},
        "user_east":  {"table": "orders", "clause": "region = 'East'"},
    }

    @staticmethod
    def inject(sql: str, user_id: str = None) -> str:
        """在 SQL 的 WHERE 子句末尾注入权限过滤条件"""
        if not user_id or user_id not in RowLevelSecurity.POLICIES:
            return sql  # 无策略 → 返回原 SQL

        policy = RowLevelSecurity.POLICIES[user_id]
        # 使用 sqlparse 解析 SQL，找到涉及的 FROM 表名
        # 若表名匹配 policy['table']，在 WHERE 后追加 AND clause
        # 无 WHERE 时追加 WHERE clause
        ...
```

---

## 5. 前端组件设计

### 5.1 组件树

```
<App>
  <ConfigProvider theme={lightTheme}>
    <Layout>
      <Sider width={240}>                         // 左侧面板
        <DataSourcePanel>
          <TableList>                             // 表名列表
            <TableItem onClick→showDetail />
          </TableList>
          <TableDetailModal />                    // 字段弹窗
        </DataSourcePanel>
      </Sider>

      <Layout.Content>                            // 右侧主区域
        <ChatPanel>
          <ChatHeader>                            // 标题 + 操作按钮
            <SessionTitle />
            <NewChatButton />
            <HistoryButton />
          </ChatHeader>

          <ChatBody>                              // 对话流
            <MessageBubble type="user|assistant">
              // assistant 类型:
              <StatusIndicator state="thinking|executing|..." />
              <ResultTable>                       // 结果表格（斑马纹+固定表头）
                <Table columns={cols} dataSource={rows} />
              </ResultTable>
              <Collapse>                          // 折叠面板
                <SQLBlock sql={sql} />
                <ExplanationBlock text={exp} />
              </Collapse>
              <ErrorBlock type="failed|blocked" />
            </MessageBubble>
            <Skeleton active />                   // 骨架屏加载态
          </ChatBody>

          <ChatInput>                             // 输入框
            <TextArea onPressEnter={send} />
            <SendButton />
          </ChatInput>
        </ChatPanel>

        <HistoryDrawer>                           // 历史记录抽屉
          <HistoryList>
            <HistoryItem onClick→refill />
          </HistoryList>
          <ClearHistoryButton />
        </HistoryDrawer>
      </Layout.Content>
    </Layout>
  </ConfigProvider>
</App>
```

### 5.2 状态管理

```typescript
// useQueryReducer.ts
interface AppState {
  sessionId: string | null;
  messages: Message[];          // 对话消息列表
  status: QueryStatus;          // 'idle' | 'thinking' | 'executing' | 'success' | 'failed'
  tables: TableInfo[];          // 数据源表格列表
  historyOpen: boolean;         // 历史面板是否展开
}

type Action =
  | { type: 'SEND_QUESTION'; question: string }
  | { type: 'STATUS_UPDATE'; status: QueryStatus; message: string }
  | { type: 'QUERY_RESULT'; result: QueryResult }
  | { type: 'QUERY_ERROR'; error: QueryError }
  | { type: 'LOAD_TABLES'; tables: TableInfo[] }
  | { type: 'LOAD_HISTORY'; messages: Message[] }
  | { type: 'TOGGLE_HISTORY' };
```

### 5.3 SSE 事件处理 Hook

```typescript
// useQuerySSE.ts
function useQuerySSE() {
  const sendQuery = async (question: string, sessionId?: string) => {
    // 使用 POST + fetch + ReadableStream 处理 SSE
    // 监听 event: status → dispatch STATUS_UPDATE
    // 监听 event: result → dispatch QUERY_RESULT
    // 监听 event: error  → dispatch QUERY_ERROR
  };
  return { sendQuery };
}
```

---

## 6. 错误处理与熔断策略

| 场景 | 处理方式 | 用户感知 |
| :--- | :--- | :--- |
| LLM 返回非 SQL 内容 | 提取 SQL 代码块；无则重试 | 无感知 |
| SQL 执行报错（语法/字段不存在） | ReAct 循环：解析错误→修正→重试，最多 2 次 | 无感知（2 次内修复） |
| 重试 2 次仍失败 | 熔断，返回友好提示 | "当前查询较复杂，建议简化条件..." |
| Agent 总耗时 > 15s | 强制中断，返回 timeout | 同上 |
| 高危 SQL（DELETE/DROP 等） | 拦截，不执行 | "检测到删除意图，该操作已被拦截..." |
| 数据库连接断开 | 返回 503 + 自动重连 | "数据库暂不可用，请稍后重试" |
| LLM API 不可用 | 返回 503 | "AI 服务暂不可用，请 5 分钟后重试" |
| 向量检索无匹配 | 使用默认 Prompt（含全部表schema）降级 | 无感知，但 SQL 可能不准 |
| 查询结果为空 | 正常返回空表格 + 说明文案 | "未查询到符合条件的数据" |

---

## 7. 环境变量配置

```env
# === 后端 ===
APP_ENV=development                          # development | production
LLM_PROVIDER=deepseek                        # deepseek | openai
LLM_API_KEY=sk-xxxx
LLM_MODEL=deepseek-v3                        # 或 gpt-4o
LLM_BASE_URL=https://api.deepseek.com/v1    # 自定义 endpoint

# 目标数据库
TARGET_DB_TYPE=mysql
TARGET_DB_HOST=localhost
TARGET_DB_PORT=3306
TARGET_DB_NAME=business_db
TARGET_DB_USER=readonly_user
TARGET_DB_PASS=xxxx

# 系统元数据库（SQLite 用于开发）
META_DB_URL=sqlite:///./data/meta.db

# Chroma
CHROMA_PERSIST_DIR=./data/chroma

# Embedding
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=sk-xxxx

# 连接池
DB_POOL_SIZE=30
DB_POOL_IDLE_TIMEOUT=300

# === 前端 ===
VITE_API_BASE=http://localhost:8000/api/v1
```

---

## 8. 测试策略

| 测试层级 | 覆盖范围 | 工具 |
| :--- | :--- | :--- |
| 单元测试 | SQL Guard、RLS 注入、Prompt 模板、工具函数 | pytest |
| Agent 集成测试 | 给定问题→验证 Agent 最终 SQL 是否正确（Mock LLM） | pytest + mock |
| E2E 测试 | 前端输入→流式返回→表格渲染（Mock 数据库） | Playwright |
| 安全测试 | 注入攻击、越权 SQL、RLS 绕过测试 | pytest (parametrize) |

---

## 9. 开发与部署

### 9.1 快速启动

```bash
# 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 编辑配置
uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

### 9.2 Docker 部署

```dockerfile
# Dockerfile（后端）
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 9.3 Docker Compose

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [chroma]
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
  chroma:
    image: chromadb/chroma:latest
    ports: ["8001:8000"]
    volumes: [chroma_data:/chroma/chroma]
volumes:
  chroma_data:
```
