# Dragon — платформа для клубов ККИ

Турниры (швейцарка, «Быстрый швейцарец», EDH-банк), база карт (Scryfall, «Берсерк»), деклисты и аналитика меты, новости, Telegram-бот.

## Запуск
1. `cp .env.example .env` и заполните `JWT_SECRET`, `TELEGRAM_BOT_TOKEN`.
2. `docker compose up --build`
3. API и документация: http://localhost:8000/docs

## Тесты
`cd backend && pip install -r requirements.txt pytest && pytest`
