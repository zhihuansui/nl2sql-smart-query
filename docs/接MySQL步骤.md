# 接入 MySQL 步骤

> 项目已原生支持 MySQL，只需改 1 行代码 + 配置 `.env` 即可。

---

## 一、代码修改（1 处）

### 修改文件：`backend/app/api/tables.py` 第 102 行

MySQL 使用反引号引用标识符，当前代码用的是双引号（PostgreSQL/SQLite 风格），在 MySQL 默认配置下会报语法错误。

```diff
- sql = f'SELECT * FROM "{table_name}" LIMIT {limit} OFFSET {offset}'
+ sql = f"SELECT * FROM `{table_name}` LIMIT {limit} OFFSET {offset}"
```

---

## 二、配置 `.env`

编辑 `backend/.env`，填入你的 MySQL 连接信息：

```ini
# 目标数据库（业务库）— MySQL
TARGET_DB_TYPE=mysql
TARGET_DB_HOST=你的数据库主机IP
TARGET_DB_PORT=3306
TARGET_DB_NAME=你的数据库名
TARGET_DB_USER=readonly_user
TARGET_DB_PASS=你的密码
```

---

## 三、MySQL 用户权限

给连接用户授予只读权限即可：

```sql
CREATE USER 'readonly_user'@'%' IDENTIFIED BY '你的密码';
GRANT SELECT ON 你的数据库名.* TO 'readonly_user'@'%';
FLUSH PRIVILEGES;
```

系统只需要 **SELECT** 和 **information_schema** 读取权限，不需要任何写权限。

---

## 四、安装依赖

```bash
cd backend
pip install -r requirements.txt
```

`aiomysql`（MySQL 异步驱动）已在 `requirements.txt` 中声明，无需额外添加。

---

## 五、启动服务

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

启动后系统会自动：

1. 连接目标 MySQL 数据库
2. 扫描 `information_schema` 获取所有表结构
3. 将表结构写入 Chroma 向量库，供后续 NL2SQL 检索使用

---

## 六、验证

访问 `http://localhost:8000/api/tables`，应返回 MySQL 数据库中所有表的列表。

---

## 注意事项

| 项目 | 说明 |
|------|------|
| MySQL 版本 | 5.7+ 均可，推荐 8.0+ |
| 字符集 | 建议 `utf8mb4`，确保中文正常显示 |
| 网络 | 确保后端服务能访问 MySQL 的 3306 端口 |
| 只读 | 系统仅执行 SELECT，安全护栏会拦截所有写操作 |
| 连接池 | 默认 30 个连接，可在 `.env` 中通过 `DB_POOL_SIZE` 调整 |
