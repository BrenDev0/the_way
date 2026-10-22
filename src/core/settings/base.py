from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """The base of every settings class in the project."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
