from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./kalpi.db"
    webhook_url: str | None = None
    allow_live_trading: bool = False
    order_poll_attempts: int = 2
    order_poll_interval_seconds: float = 0.05
    broker_redirect_base_url: str = "http://localhost:8000/api/v1/brokers"

    zerodha_api_key: str | None = None
    zerodha_api_secret: SecretStr | None = None
    zerodha_access_token: SecretStr | None = None
    dhan_client_id: str | None = None
    dhan_api_secret: SecretStr | None = None
    dhan_access_token: SecretStr | None = None
    angel_one_api_key: str | None = None
    angel_one_access_token: SecretStr | None = None
    angel_one_client_local_ip: str | None = None
    angel_one_client_public_ip: str | None = None
    angel_one_mac_address: str | None = None
    groww_api_key: str | None = None
    groww_access_token: SecretStr | None = None
    upstox_api_key: str | None = None
    upstox_api_secret: SecretStr | None = None
    upstox_access_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
