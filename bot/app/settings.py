from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    backend_url: str = "http://backend:8000"
    request_timeout_seconds: int = 10
    database_path: str = "bot_data.sqlite3"
    war_reminder_enabled: bool = True
    war_reminder_window_hours: int = 4
    war_reminder_interval_minutes: int = 10
    war_reminder_cooldown_minutes: int = 60


settings = Settings()
