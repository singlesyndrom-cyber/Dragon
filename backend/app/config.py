from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 10080
    telegram_bot_token: str = ""
    # прокси до api.telegram.org, если хостинг его блокирует: socks5://tgproxy:1080 или http://user:pass@host:port
    telegram_proxy: str = ""
    vk_app_id: str = ""
    vk_app_secret: str = ""
    telegram_global_chat_id: str = ""
    telegram_trade_chat_id: str = ""    # общий торговый канал для аукционов   # канал платформы для глобальных статей
    public_base_url: str = ""           # адрес сайта для ссылок в сообщениях
    app_timezone: str = "Europe/Moscow"
    scryfall_auto_sync: bool = True     # бот сам загружает базу MTG при пустой базе и раз в неделю
    # прокси до Scryfall (с некоторых хостингов он не отвечает): auto - тот же, что для Telegram;
    # direct - без прокси; иначе адрес socks5://… или http://…
    scryfall_proxy: str = "auto"
    image_cache_dir: str = "/cache/images"   # картинки карт Scryfall, скачанные сервером (раздаются через /img)
    image_cache_max_gb: float = 5.0
    # почта для восстановления пароля; пусто - письма пишутся в лог бэкенда
    backups_dir: str = "/backups"       # куда контейнер backup кладёт копии (смонтировано только для чтения)
    monitor_enabled: bool = True        # письма администраторам, если бот молчит или очередь сообщений встала
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"          # ssl (порт 465) | starttls (порт 587) | none
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""                 # например Dragon <noreply@dragon-club.ru>
    password_reset_minutes: int = 60
    auto_create_tables: bool = False  # только для разработки; в проде - Alembic


settings = Settings()
