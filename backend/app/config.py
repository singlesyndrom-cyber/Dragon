from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 10080
    telegram_bot_token: str = ""
    vk_app_id: str = ""
    vk_app_secret: str = ""
    telegram_global_chat_id: str = ""
    telegram_trade_chat_id: str = ""    # общий торговый канал для аукционов   # канал платформы для глобальных статей
    public_base_url: str = ""           # адрес сайта для ссылок в сообщениях
    app_timezone: str = "Europe/Moscow"
    auto_create_tables: bool = False  # только для разработки; в проде - Alembic


settings = Settings()
