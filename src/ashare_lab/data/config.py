"""Environment-only settings for the isolated market-data database."""

from urllib.parse import quote_plus

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSettings(BaseSettings):
    """Validated local secrets and fixed database isolation settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    tushare_token: SecretStr = Field(default=SecretStr(""), validation_alias="TUSHARE_TOKEN")
    tushare_min_request_interval_seconds: float = Field(
        default=1.2,
        ge=0.1,
        validation_alias="TUSHARE_MIN_REQUEST_INTERVAL_SECONDS",
    )
    cninfo_min_request_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        validation_alias="CNINFO_MIN_REQUEST_INTERVAL_SECONDS",
    )
    sse_min_request_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        validation_alias="SSE_MIN_REQUEST_INTERVAL_SECONDS",
    )
    capco_min_request_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        validation_alias="CAPCO_MIN_REQUEST_INTERVAL_SECONDS",
    )
    mongodb_host: str = Field(default="127.0.0.1", validation_alias="MONGODB_HOST")
    mongodb_port: int = Field(default=27017, validation_alias="MONGODB_PORT")
    mongodb_username: str = Field(default="", validation_alias="MONGODB_USERNAME")
    mongodb_password: SecretStr = Field(default=SecretStr(""), validation_alias="MONGODB_PASSWORD")
    mongodb_auth_source: str = Field(default="admin", validation_alias="MONGODB_AUTH_SOURCE")
    mongodb_database: str = Field(default="ashare_quant", validation_alias="MONGODB_DATABASE")

    @property
    def mongodb_uri(self) -> str:
        """Build an authenticated local URI without logging either secret."""
        username = quote_plus(self.mongodb_username)
        password = quote_plus(self.mongodb_password.get_secret_value())
        auth_source = quote_plus(self.mongodb_auth_source)
        return (
            f"mongodb://{username}:{password}@{self.mongodb_host}:{self.mongodb_port}/"
            f"{self.mongodb_database}?authSource={auth_source}"
        )
