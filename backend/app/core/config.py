"""Aether Configuration — Phase 0 → Phase 2

Environment-driven configuration. All secrets via env vars.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from pydantic_settings import BaseSettings


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    api_key: str
    base_url: Optional[str] = None
    model: str = "default"
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: float = 120.0
    input_cost_per_1m: float = 0.0
    output_cost_per_1m: float = 0.0


@dataclass(frozen=True)
class DBConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "aether"
    user: str = "aether"
    password: str = "aether"

    @property
    def async_url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class MemoryConfig:
    """Phase 1: Cognee + Qdrant + KuzuDB"""
    cognee_enabled: bool = False
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    kuzu_db_path: str = "/tmp/aether/kuzu.db"
    graphiti_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"


@dataclass(frozen=True)
class SandboxConfig:
    """Phase 2: Firecracker / Kubernetes"""
    enabled: bool = False
    runtime: str = "docker"  # docker | firecracker | k8s
    sandbox_root: str = "/tmp/aether/sandbox"
    k8s_namespace: str = "aether-sandboxes"
    max_concurrent: int = 10


@dataclass(frozen=True)
class SecurityConfig:
    """Phase 2: JWT, RBAC"""
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    rbac_enabled: bool = False


@dataclass(frozen=True)
class AetherConfig:
    kimi_k2: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="kimi",
        api_key=os.getenv("KIMI_API_KEY", "").strip(),
        base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1").strip(),
        model=os.getenv("KIMI_MODEL", os.getenv("KIMI_K2_MODEL", "kimi-k2.6")).strip(),
        temperature=1.0,  # Kimi k2.6 model only accepts temperature=1
        max_tokens=4096,
        input_cost_per_1m=0.56,
        output_cost_per_1m=2.24,
    ))

    deepseek: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="deepseek",
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip(),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        temperature=0.1,
        max_tokens=4096,
        input_cost_per_1m=0.028,
        output_cost_per_1m=0.028,
    ))

    db: DBConfig = field(default_factory=lambda: DBConfig(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "aether"),
        user=os.getenv("POSTGRES_USER", "aether"),
        password=os.getenv("POSTGRES_PASSWORD", "aether"),
    ))

    memory: MemoryConfig = field(default_factory=lambda: MemoryConfig(
        cognee_enabled=os.getenv("COGNEE_ENABLED", "false").lower() == "true",
        qdrant_host=os.getenv("QDRANT_HOST", "localhost"),
        qdrant_port=int(os.getenv("QDRANT_PORT", "6333")),
        kuzu_db_path=os.getenv("KUZU_DB_PATH", "/tmp/aether/kuzu.db"),
        graphiti_enabled=os.getenv("GRAPHITI_ENABLED", "false").lower() == "true",
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    ))

    sandbox: SandboxConfig = field(default_factory=lambda: SandboxConfig(
        enabled=os.getenv("SANDBOX_ENABLED", "false").lower() == "true",
        runtime=os.getenv("SANDBOX_RUNTIME", "docker"),
        sandbox_root=os.getenv("SANDBOX_ROOT", "/tmp/aether/sandbox"),
        k8s_namespace=os.getenv("K8S_NAMESPACE", "aether-sandboxes"),
        max_concurrent=int(os.getenv("SANDBOX_MAX_CONCURRENT", "10")),
    ))

    security: SecurityConfig = field(default_factory=lambda: SecurityConfig(
        jwt_secret=os.getenv("JWT_SECRET", "change-me-in-production"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "30")),
        rbac_enabled=os.getenv("RBAC_ENABLED", "false").lower() == "true",
    ))

    ws_host: str = os.getenv("WS_HOST", "0.0.0.0")
    ws_port: int = int(os.getenv("WS_PORT", "8000"))
    max_tool_retries: int = int(os.getenv("MAX_TOOL_RETRIES", "3"))
    tool_timeout: float = float(os.getenv("TOOL_TIMEOUT", "60.0"))
    max_planning_steps: int = int(os.getenv("MAX_PLANNING_STEPS", "10"))


CONFIG = AetherConfig()


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://aether:aether@postgres:5432/aether"
    redis_url: str = "redis://redis:6379/0"
    kimi_api_key: str = ""
    deepseek_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
