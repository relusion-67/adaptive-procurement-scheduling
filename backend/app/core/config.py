from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Shipped only as an obvious, greppable placeholder so a fresh clone works
# out of the box in development/test. `_validate_production_secrets` below
# refuses to start the app in production with this value still in place,
# so it can never silently become a real deployment's signing key.
INSECURE_DEFAULT_JWT_SECRET_KEY = "insecure-development-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    api_title: str = "Adaptive Procurement Scheduling API"
    api_version: str = "1.0.0"
    api_prefix: str = "/api"

    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/adaptive_procurement"
    )
    redis_url: str = "redis://localhost:6379/0"
    backend_cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Authentication -------------------------------------------------
    # JWT signing secret. MUST come from the environment in any real
    # deployment; the default below is intentionally recognizable so
    # `_validate_production_secrets` can detect (and refuse to start on)
    # an unchanged production configuration.
    jwt_secret_key: str = INSECURE_DEFAULT_JWT_SECRET_KEY
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """Fail loudly rather than silently running production on an
        insecure default JWT secret. Development/test configuration is
        left untouched so the existing local/test workflow keeps working.
        """
        if self.app_env.lower() == "production" and (
            self.jwt_secret_key == INSECURE_DEFAULT_JWT_SECRET_KEY
            or len(self.jwt_secret_key) < 32
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a strong, unique value via "
                "environment configuration when APP_ENV=production. Refusing "
                "to start with the insecure development default."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
