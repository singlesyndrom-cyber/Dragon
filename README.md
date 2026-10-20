# Dragon — платформа для клубов ККИ

Турниры (швейцарка, «Быстрый швейцарец», EDH-банк с таймером), лиги и рейтинги клубов, база карт (Scryfall и
JSON-базы «Берсерка»), деклисты и аналитика меты, новости, Telegram-бот (анонсы, автоотчёты, аукцион карт).

| Часть | Где | Порт |
|---|---|---|
| Сайт (Next.js) | `frontend/` | 3000 |
| API (FastAPI) | `backend/app` | 8000, документация `/docs` |
| Telegram-бот (aiogram) | `backend/app/bot` | — |
| PostgreSQL 16 | — | 5432 |

## Запуск

1. `cp .env.example .env` и заполните:
   - `JWT_SECRET` — длинная случайная строка;
   - `TELEGRAM_BOT_TOKEN` — токен от @BotFather;
   - `NEXT_PUBLIC_TG_BOT_NAME` — имя бота без @;
   - `TELEGRAM_TRADE_CHAT_ID` — торговый канал аукциона (бот должен быть в нём админом);
   - `TELEGRAM_GLOBAL_CHAT_ID` — канал для глобальных новостей (необязательно);
   - `PUBLIC_BASE_URL` — адрес сайта для ссылок в сообщениях бота.
2. Для первого запуска оставьте `AUTO_CREATE_TABLES=true`.
3. `docker compose up -d --build`
4. Сайт: http://localhost:3000, API: http://localhost:8000/docs
5. Зарегистрируйтесь на сайте и сделайте себя администратором:
   `docker compose exec db psql -U kki -c "UPDATE users SET role='admin' WHERE id=1;"`
6. В админке нажмите «Обновить базу», чтобы загрузить карты MTG из Scryfall.

Вход через Telegram на сайте: в @BotFather выполните `/setdomain` и укажите домен сайта.

## Тесты

GitHub Actions на каждый push прогоняет тесты бэкенда на PostgreSQL и собирает сайт.
Локально: `cd backend && pip install -r requirements.txt pytest pytest-asyncio && pytest`
(интеграционные тесты — с `RUN_INTEGRATION=1` и `DATABASE_URL` на пустую базу).
