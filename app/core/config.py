from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_host: str = "localhost"
    database_port: int = 5432
    database_user: str = "postgres"
    database_password: str = "postgres"
    database_name: str = "goldentimer"

    app_name: str = "GoldenTimer API"
    api_v1_prefix: str = "/api/v1"

    ermct_service_key: str = ""
    hospital_sync_enabled: bool = True
    hospital_sync_cycle_minutes: int = 5
    hospital_sync_full_hour: int = 3
    hospital_sync_request_delay_sec: float = 0.05

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"
    gemini_timeout_sec: int = 30

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
