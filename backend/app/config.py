from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 运行环境
    APP_ENV: str = "development"

    # LLM 配置
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-v3"
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"

    # 目标数据库（业务库）
    TARGET_DB_TYPE: str = "mysql"
    TARGET_DB_HOST: str = "localhost"
    TARGET_DB_PORT: int = 3306
    TARGET_DB_NAME: str = "business_db"
    TARGET_DB_USER: str = "readonly_user"
    TARGET_DB_PASS: str = ""

    # 系统元数据库
    META_DB_URL: str = "sqlite:///./data/meta.db"

    # Chroma 向量存储
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_HOST: str = ""                        # 空=本地模式；填主机地址=HTTP客户端
    CHROMA_PORT: int = 8001                      # Chroma HTTP 服务端口

    # Embedding
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str = ""

    # 连接池
    DB_POOL_SIZE: int = 30
    DB_POOL_IDLE_TIMEOUT: int = 300

    # CORS（前端地址）
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# 确保数据目录存在
data_dir = Path(settings.CHROMA_PERSIST_DIR).parent
data_dir.mkdir(parents=True, exist_ok=True)
