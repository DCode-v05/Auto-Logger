from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    bot_public_url: str
    pms_base_url: str = "https://iqube.therig.in"
    bot_encryption_key: str
    bot_db_path: Path = Path("./data/bot.sqlite3")
    playwright_profiles_dir: Path = Path("./data/profiles")
    attachment_tmp_dir: Path = Path("./data/tmp")
    fastapi_host: str = "127.0.0.1"
    fastapi_port: int = 8765
    mfa_timeout_seconds: int = 180
    session_idle_close_seconds: int = 600
    log_level: str = "INFO"

    @property
    def pms_login_url(self) -> str:
        return f"{self.pms_base_url.rstrip('/')}/login/"

    @property
    def pms_daily_log_create_url(self) -> str:
        return f"{self.pms_base_url.rstrip('/')}/me/daily_log/create/"

    @property
    def pms_daily_log_list_url(self) -> str:
        return f"{self.pms_base_url.rstrip('/')}/me/daily_log/"

    @property
    def pms_me_url(self) -> str:
        return f"{self.pms_base_url.rstrip('/')}/me/"

    def ensure_dirs(self) -> None:
        self.bot_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.playwright_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.attachment_tmp_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
