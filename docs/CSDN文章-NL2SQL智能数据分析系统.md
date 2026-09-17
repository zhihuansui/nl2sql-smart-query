# 从零构建企业级 NL2SQL 系统：基于 ReAct Agent 的智能数据分析助手

> **GitHub 地址**：[点击查看完整代码](#)（替换为你的仓库链接）
>
> 一个"说人话就能查数据库"的企业级工具——业务人员输入大白话，系统自动完成自然语言 → SQL → 数据查询 → 结果展示的全链路闭环。

---

## 一、为什么要做这个项目

在企业里，运营、产品、销售经常需要问："上个月华东区销售额排名前十的商品是哪些？""今年注册的用户里有多少下过单？"

传统流程是：业务人员 → 提需求给数据分析师/DBA → 写 SQL → 跑数 → 导出 Excel → 返回。一圈下来，短则半天，长则两三天。

这个项目的目标就是**让业务人员直接问数据库，3 秒拿到结果**。

市面上已有不少 NL2SQL 方案，但多数停留在 Demo 阶段——能跑通，但缺安全护栏、缺纠错机制、缺企业级特性。这个项目按照完整的产品规格（PRD + SPEC）从零设计，把 Schema Linking、Few-Shot 检索、ReAct 纠错、SQL 安全护栏、行级权限、SSE 流式返回这些工程细节都做扎实了。

---

## 二、系统架构

全栈项目，前后端分离：

```
┌───────────────────────────────────────────┐
│         Frontend (React 18 + Ant Design)   │
│  ┌──────────┐  ┌──────────┐  ┌─────────┐  │
│  │ 数据源面板│  │ 对话面板  │  │ 历史记录 │  │
│  └──────────┘  └──────────┘  └─────────┘  │
└──────────────────┬────────────────────────┘
                   │ HTTP / SSE（流式）
┌──────────────────┴────────────────────────┐
│           Backend (FastAPI + LangChain)     │
│                                            │
│   意图识别 → Schema Linking → Few-Shot 检索 │
│       → Prompt 组装 → ReAct Agent 生成 SQL  │
│       → 安全护栏 → RLS 注入 → 执行 → 解释   │
│                                            │
│  ┌──────────┐ ┌───────────┐ ┌───────────┐  │
│  │ Meta DB  │ │ Target DB │ │  Chroma   │  │
│  │(会话/历史)│ │(业务数据库)│ │(向量检索) │  │
│  └──────────┘ └───────────┘ └───────────┘  │
└──────────────────┬────────────────────────┘
                   │
           ┌───────┴────────┐
           │  DeepSeek / GPT │
           └────────────────┘
```

### 技术栈

| 层级 | 技术选型 |
|:---|:---|
| 前端 | React 18 + TypeScript + Ant Design 5 + Vite |
| 后端框架 | Python 3.10+ / FastAPI |
| AI 引擎 | LangChain 0.3+ / LangGraph（Agent 框架） |
| LLM | DeepSeek-V3（默认）/ GPT-4o / 兼容 OpenAI 协议的任何模型 |
| Embedding | text-embedding-3-small |
| 向量存储 | Chroma（cosine 相似度，1536 维） |
| 业务数据库 | MySQL 8.0 / PostgreSQL 15 / SQLite |
| 容器化 | Docker + Docker Compose |

---

## 三、核心流程：从大白话到数据结果

整个链路一共 **10 步**，每步都有明确的职责边界：

```
用户输入 "上个月华东区销售额前十的商品"
         │
    ┌────▼────┐
    │ 1. 意图识别 │── 关键词启发式，快速判断是不是数据查询
    └────┬────┘
    ┌────▼────┐
    │ 2. Schema  │── 向量检索：从 Chroma 中召回最相关的表结构
    │   Linking │    （如 users、orders、products 三张表）
    └────┬────┘
    ┌────▼────┐
    │ 3. Few-Shot│── 向量检索：召回语义相似的"问题→SQL"范例
    │   检索    │
    └────┬────┘
    ┌────▼────┐
    │ 4. Prompt │── 把表结构 + 示范 SQL + 对话历史 + RLS 策略
    │   组装    │    按模板拼成 System Prompt
    └────┬────┘
    ┌────▼────┐
    │ 5. Agent  │── LLM 直接生成 SQL（用 ```sql 代码块包裹）
    │   生成    │    超时 30s，失败则重试
    └────┬────┘
    ┌────▼────┐
    │ 6. 安全   │── 正则 + sqlparse AST 双重检查
    │   护栏    │    DROP/DELETE/INSERT/时间注入 → 直接拦截
    └────┬────┘
    ┌────▼────┐
    │ 7. RLS   │── 根据用户身份，在 SQL 的 WHERE 后注入
    │   注入    │    region = 'East' 等行级权限条件
    └────┬────┘
    ┌────▼────┐
    │ 8. SQL   │── 只读 SELECT 执行 → 最多 200 行
    │   执行    │
    └────┬────┘
    ┌────▼────┐
    │ 9. 白话   │── LLM 把 SQL 翻译成中文解释
    │   解释    │    "统计华东区销售额最高的10个商品"
    └────┬────┘
    ┌────▼────┐
    │10. SSE   │── 流式推送给前端：状态更新 + 最终结果
    │   推送    │
    └─────────┘
```

### 关键设计决策：为什么不用 ReAct 工具调用循环？

LangChain 原生的 ReAct Agent 会在 Thought → Action → Observation 之间反复调用 LLM，对于"生成一条 SQL"这个任务来说，多轮工具调用增加延迟且不稳定。实际改为**直接让 LLM 生成 SQL**（从 ```sql 代码块中提取），更简洁可靠。表结构信息通过 Prompt 注入而非工具调用获取，减少了 Agent 的"幻觉空间"。

---

## 四、技术亮点

### 1. Schema Linking — 让 AI 知道有哪些表和字段

企业数据库动辄几十上百张表，每张表几十个字段，全塞进 Prompt 会超出 Token 限制，且无关信息会干扰 LLM 判断。

解决方式：**用向量检索做"表级别的语义搜索"**。系统启动时扫描所有表的字段名和注释，拼接成文本后 Embedding 写入 Chroma。用户提问时，用问题的 Embedding 去检索最相关的 Top-5 张表，只把这些表的 DDL 信息注入 Prompt。

```python
# 表结构文本示例（会被 Embedding 后存入 Chroma）
"表 users: id(bigint PK 用户ID), name(varchar 用户名), 
 register_date(datetime 注册时间), region(varchar 所属区域)"

"表 orders: id(bigint PK 订单ID), user_id(bigint FK 用户ID), 
 amount(decimal 订单金额), created_at(datetime 下单时间)"
```

### 2. Few-Shot 动态检索 — 给 AI 看最相关的例子

Few-Shot 是提升 NL2SQL 准确率的关键手段。但固定写死几个示例效果有限——用户问"销售额排名"时给它看"用户注册统计"的例子帮助不大。

解决方式：**同样用向量检索**，从黄金示例库中召回与当前问题语义最相似的例子，动态注入 Prompt。

```python
# 黄金示例格式
{
    "question": "统计华东地区2024年7月的订单总金额",
    "sql": "SELECT SUM(amount) FROM orders o 
             JOIN users u ON o.user_id = u.id 
             WHERE u.region = '华东' 
               AND o.created_at BETWEEN '2024-07-01' AND '2024-07-31'",
    "tags": ["聚合", "JOIN", "时间范围", "地域筛选"]
}
```

### 3. SQL 安全护栏 — 双层检查，不放过任何危险操作

安全不是"相信 AI 不会生成危险 SQL"，而是"假设 AI 可能被诱导生成危险 SQL，然后拦截它"。

| 检查层 | 方式 | 拦截对象 |
|:---|:---|:---|
| 第一层 | 正则快速扫描 | DROP / DELETE / INSERT / ALTER / TRUNCATE / 时间注入函数(SLEEP/BENCHMARK) |
| 第二层 | sqlparse AST 解析 | 任何非 SELECT 类型的语句、多语句拼接攻击 |

```python
# 检测示例
guard.inspect("SELECT * FROM users; DROP TABLE orders")
# → (True, "检测到多条 SQL 语句，其中包含 DROP 操作，已拦截")

guard.inspect("SELECT * FROM users WHERE id = 1 AND SLEEP(5)")
# → (True, "检测到 SLEEP 操作，该操作已被拦截")
```

### 4. RLS 行级权限注入 — 不同用户看到不同数据

多租户场景下，华东区经理不能看到华南区的订单数据。系统在 SQL 执行前自动注入权限条件：

```python
# user_north 用户问："查询上月订单总额"
# Agent 生成：
SELECT SUM(amount) FROM orders 
WHERE created_at >= '2026-06-01'

# RLS 注入后实际执行：
SELECT SUM(amount) FROM orders 
WHERE created_at >= '2026-06-01' AND region = 'North'
```

注入逻辑基于 sqlparse 的 AST 解析，正确处理了已有 WHERE、无 WHERE、子查询、JOIN 别名等边界情况。

### 5. SSE 流式推送 — 用户实时感知进度

查询不是黑盒等待。前端通过 Server-Sent Events 实时接收后端推送的状态：

```
event: status  →  "正在理解语义..."
event: status  →  "正在检索表结构..."（附带匹配到的表名）
event: status  →  "正在执行查询..."
event: result  →  完整结果（SQL + 表格数据 + 白话解释 + 执行耗时）
event: error   →  错误信息（带分类：rejected / blocked / failed）
```

### 6. 智能重试 + 熔断

SQL 执行报错不直接丢给用户。系统会把错误信息追加到 Prompt 尾部，让 LLM 在下一轮尝试中自动修正（比如字段名写错了、JOIN 条件漏了），最多重试 2 次。全链路超时 30 秒，避免 LLM 卡死。

---

## 五、部署指引

项目支持源码启动和 Docker 一键部署两种方式。

### 环境要求

- Python 3.10+
- Node.js 18+
- 目标数据库（MySQL 8.0 / PostgreSQL 15 / SQLite）

### 三步启动

**1. 配置环境变量**

```bash
cp .env.example .env
# 填入 LLM_API_KEY 和数据库连接信息
```

**2. 启动后端**

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**3. 启动前端**

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:3000` 即可使用。

### Docker 部署

```bash
docker compose up -d
```

一行命令启动后端 + Chroma 向量服务。详细步骤见项目 README。

---

## 六、关于安全性

安全性是这个项目的核心设计原则之一，而非事后打补丁：

| 安全机制 | 作用 |
|:---|:---|
| SQL 安全护栏 | 正则 + AST 双检，拦截所有非 SELECT 操作 |
| 时间注入防护 | 拦截 SLEEP / BENCHMARK / PG_SLEEP 等盲注函数 |
| 注释/字符串剥离 | 先剥离注释和字符串字面量再检查，防止关键字伪装 |
| 行级权限（RLS） | 自动注入 WHERE 过滤条件，确保数据隔离 |
| 只读数据库账号 | 架构层面建议目标库使用仅有 SELECT 权限的账号 |
| 结果行数限制 | 单次最多返回 200 行，防止数据泄露 |

---

## 七、测试覆盖

项目包含三层测试：

| 测试类型 | 文件 | 用例数 | 工具 |
|:---|:---|:---|:---|
| 单元测试（安全模块） | `test_guard.py` | 52 个 | pytest |
| 单元测试（RLS） | `test_rls.py` | 26 个 | pytest |
| Agent 集成测试 | `test_agent_loop.py` | 11 个 | pytest + mock |
| E2E 端到端测试 | `query_flow.spec.ts` | 10 个场景 | Playwright |

覆盖了：正常 SQL 放行、DDL/DML 拦截、多语句攻击、时间注入、RLS 各种 JOIN 场景、Agent 全链路成功/失败/重试/熔断。

---

## 八、写在最后

这个项目的目标不是做一个"能跑就行"的 Demo，而是按照企业级标准，把 NL2SQL 的每个环节都考虑周全——Schema Linking 怎么设计、安全怎么保障、权限怎么隔离、失败怎么兜底。

如果你也在做类似的方向，或者想在公司内部搭建自然语言查数工具，希望这个项目能给你一些参考。

**GitHub 地址**：[点击查看完整代码](#)（替换为你的仓库链接）

---

> 如果你觉得项目对你有帮助，欢迎 Star ⭐️  
> 有任何问题或建议，欢迎提 Issue 或 PR 交流。
