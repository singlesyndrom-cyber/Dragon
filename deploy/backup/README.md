# Резервные копии

Контейнер `backup` каждый день в 04:00 по Москве кладёт в `/opt/dragon/backups`:

- `kki-ГГГГ-ММ-ДД.sql.gz` — полная копия базы;
- `kki-light-ГГГГ-ММ-ДД.sql.gz` — то же без базы карт (её можно заново скачать из Scryfall в админке).
  Эту маленькую копию бот присылает администраторам в Telegram — так копия есть и вне сервера.

Хранятся последние 14 копий каждого вида. Состояние — в админке, блок «Состояние системы».

Сделать копию прямо сейчас:
```
docker compose -f docker-compose.prod.yml restart backup     # при старте делает копию, если за сутки её не было
# или вручную:
docker compose -f docker-compose.prod.yml exec backup sh -c 'pg_dump -h db -U kki kki | gzip > /backups/kki-manual-$(date +%F-%H%M).sql.gz'
```

Восстановить (база будет заменена копией!):
```
cd /opt/dragon
docker compose -f docker-compose.prod.yml stop backend bot
docker compose -f docker-compose.prod.yml exec -T db psql -U kki -d postgres -c "DROP DATABASE kki;" -c "CREATE DATABASE kki OWNER kki;"
gunzip -c backups/kki-2026-10-23.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U kki -d kki
docker compose -f docker-compose.prod.yml start backend bot
```
Из облегчённой копии после восстановления запустите синхронизацию карт в админке.
