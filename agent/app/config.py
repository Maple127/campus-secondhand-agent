"""应用配置。

所有敏感信息（LLM Key、服务令牌）只从环境变量 / .env 读取，
绝不写入代码或提交入库。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量加载的配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- LLM ----------
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    # 是否让 LLM 请求走系统代理。默认 True（调用公网 API 常需要代理）；
    # 若无代理环境导致连不上，可设为 false。
    llm_trust_env: bool = Field(default=True, alias="LLM_TRUST_ENV")

    # ---------- Java 后端 ----------
    backend_base_url: str = Field(default="http://localhost:8081", alias="BACKEND_BASE_URL")
    agent_service_token: str = Field(default="", alias="AGENT_SERVICE_TOKEN")
    backend_timeout: float = Field(default=20.0, alias="BACKEND_TIMEOUT")
    # 是否让后端请求走系统代理。默认 False：
    # Windows 上 Python 会从注册表读到系统代理（如 127.0.0.1:7897），
    # 若开启会把 localhost 的后端请求也送去代理，表现为 502。
    backend_trust_env: bool = Field(default=False, alias="BACKEND_TRUST_ENV")

    # ---------- 服务自身 ----------
    agent_host: str = Field(default="127.0.0.1", alias="AGENT_HOST")
    agent_port: int = Field(default=8090, alias="AGENT_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # 允许跨源访问的来源（逗号分隔）。Thymeleaf 页面在 8081，需在此放行。
    cors_origins: str = Field(
        default="http://localhost:8081,http://127.0.0.1:8081",
        alias="CORS_ORIGINS",
    )

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ---------- Agent 行为 ----------
    max_agent_steps: int = Field(default=8, alias="MAX_AGENT_STEPS")
    log_tool_args: bool = Field(default=True, alias="LOG_TOOL_ARGS")
    # 单会话保留的最大消息条数
    max_history_messages: int = Field(default=40, alias="MAX_HISTORY_MESSAGES")

    # ---------- 持久化 ----------
    # LangGraph checkpointer 与幂等账本共用的数据库文件。
    # 之所以必须持久化：人工确认是"挂起 → 等待用户 → 恢复执行"的跨请求流程，
    # 状态若只存内存，进程一重启确认就丢失，用户再也无法完成该操作。
    checkpoint_db_path: str = Field(default="./data/agent_state.db", alias="CHECKPOINT_DB_PATH")

    # ---- 上下文管理 ----
    # 预算按 token 算而不是按轮数：一轮长描述和一句「嗯」差别很大。
    # 6000 是经验值，够放近期 6 条 + 一条摘要，又不至于把 DeepSeek 的窗口当无限用。
    context_token_budget: int = Field(default=6000, alias="CONTEXT_TOKEN_BUDGET")
    compress_keep_recent: int = Field(default=6, alias="COMPRESS_KEEP_RECENT")
    enable_compression: bool = Field(default=True, alias="ENABLE_COMPRESSION")

    # ---- 检索闸门（消融评测用）----
    # 关掉它就能测出「空结果重试上限」到底值多少
    enable_empty_search_gate: bool = Field(default=True, alias="ENABLE_EMPTY_SEARCH_GATE")
    max_empty_searches: int = Field(default=2, alias="MAX_EMPTY_SEARCHES")
    """连续几次空搜索后开始拦截。调到 1 可以让消融实验稳定触发闸门。"""

    # ---- 后端重试（消融评测用）----
    backend_max_retries: int = Field(default=2, alias="BACKEND_MAX_RETRIES")

    # ---- 策略路由（消融评测用）----
    # 关掉之后所有 FAST 请求都会走 AGENT，用来对比两条路径的成本
    enable_fast_path: bool = Field(default=True, alias="ENABLE_FAST_PATH")

    def require_llm_key(self) -> str:
        """取 LLM Key，缺失时给出可操作的报错而不是让 SDK 抛晦涩异常。"""
        if not self.deepseek_api_key or self.deepseek_api_key.startswith("sk-xxx"):
            raise RuntimeError(
                "未配置 DEEPSEEK_API_KEY。请在 agent/.env 中填写，"
                "或设置同名环境变量后重启服务。参考 agent/.env.example"
            )
        return self.deepseek_api_key

    def require_service_token(self) -> str:
        """取服务令牌，必须与后端 app.agent.service-token 一致。"""
        if not self.agent_service_token:
            raise RuntimeError(
                "未配置 AGENT_SERVICE_TOKEN。它必须与后端 "
                "application.properties 中的 app.agent.service-token 保持一致。"
            )
        return self.agent_service_token


@lru_cache
def get_settings() -> Settings:
    """进程内单例，避免每次请求都重新解析环境变量。"""
    return Settings()
