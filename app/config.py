"""Configuration settings for CapCut TTS Service."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8001, env="PORT")
    debug: bool = Field(default=False, env="DEBUG")

    # Cloudflare R2 (S3-compatible)
    r2_account_id: Optional[str] = Field(default=None, env="R2_ACCOUNT_ID")
    r2_access_key_id: Optional[str] = Field(default=None, env="R2_ACCESS_KEY_ID")
    r2_secret_access_key: Optional[str] = Field(default=None, env="R2_SECRET_ACCESS_KEY")
    r2_bucket_name: str = Field(default="german-learning", env="R2_BUCKET_NAME")
    r2_public_url: str = Field(default="https://storage.colenboro.xyz", env="R2_PUBLIC_URL")

    # CapCut TTS
    capcut_api_base: str = Field(
        default="https://editor-api-sg.capcutapi.com",
        env="CAPCUT_API_BASE"
    )
    capcut_device_id: str = Field(default="", env="CAPCUT_DEVICE_ID")
    capcut_iid: str = Field(default="", env="CAPCUT_IID")
    capcut_tdid: str = Field(default="", env="CAPCUT_TDID")

    # TTS defaults
    default_voice_vi: str = Field(default="BV074_streaming", env="DEFAULT_VOICE_VI")
    default_voice_de: str = Field(default="DiT_de_male_koubo", env="DEFAULT_VOICE_DE")
    default_resource_id_vi: str = Field(
        default="7102355709945188865",
        env="DEFAULT_RESOURCE_ID_VI"
    )
    default_resource_id_de: str = Field(
        default="7584344912276114704",
        env="DEFAULT_RESOURCE_ID_DE"
    )

    # Polling
    poll_max_attempts: int = Field(default=30, env="POLL_MAX_ATTEMPTS")
    poll_interval: float = Field(default=0.5, env="POLL_INTERVAL")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
