from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # API keys
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    typefully_api_key: str
    openai_api_key: str

    # Paths
    db_path: Path = Path("data/brain.db")
    log_path: Path = Path("logs/agent.log")
    log_level: str = "INFO"

    @field_validator("db_path", "log_path", mode="before")
    @classmethod
    def coerce_path(cls, v: object) -> Path:
        return Path(str(v))


def load_config_yaml(path: Path = Path("config.yaml")) -> dict:  # type: ignore[type-arg]
    with path.open() as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


settings = Settings()
config = load_config_yaml()
