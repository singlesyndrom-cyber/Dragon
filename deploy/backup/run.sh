#!/bin/sh
# Резервные копии базы: каждый день в 04:00 (TZ контейнера), хранятся последние 14.
#   kki-ГГГГ-ММ-ДД.sql.gz        - полная копия
#   kki-light-ГГГГ-ММ-ДД.sql.gz  - без данных базы карт (её можно заново скачать из Scryfall):
#                                  маленькая, её бот отправляет администраторам в Telegram
# Восстановление: deploy/backup/README.md
set -u
DIR=/backups
KEEP=14
mkdir -p "$DIR"

status() {   # status.json читают админка и бот
  printf '{"at":"%s","ok":%s,"file":"%s","size":%s,"light":"%s","light_size":%s,"error":"%s"}\n' \
    "$(date -Iseconds)" "$1" "$2" "$3" "$4" "$5" "$6" > "$DIR/status.json.tmp" && mv "$DIR/status.json.tmp" "$DIR/status.json"
}

backup() {
  day=$(date +%F)
  full="kki-$day.sql.gz"; light="kki-light-$day.sql.gz"
  if pg_dump -h db -U kki kki | gzip > "$DIR/$full.tmp" \
     && pg_dump -h db -U kki --exclude-table-data=cards --exclude-table-data=sync_runs kki | gzip > "$DIR/$light.tmp"; then
    mv "$DIR/$full.tmp" "$DIR/$full"; mv "$DIR/$light.tmp" "$DIR/$light"
    ls -1t "$DIR"/kki-light-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
    ls -1t "$DIR"/kki-2*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
    status true "$full" "$(stat -c %s "$DIR/$full")" "$light" "$(stat -c %s "$DIR/$light")" ""
    echo "$(date -Iseconds) копия готова: $full"
  else
    rm -f "$DIR/$full.tmp" "$DIR/$light.tmp"
    status false "" 0 "" 0 "pg_dump завершился с ошибкой"
    echo "$(date -Iseconds) ОШИБКА резервной копии" >&2
  fi
}

# при старте: если за последние сутки копии нет - сделать сразу
latest=$(ls -1t "$DIR"/kki-2*.sql.gz 2>/dev/null | head -1)
if [ -z "$latest" ] || [ $(( $(date +%s) - $(stat -c %Y "$latest") )) -gt 86400 ]; then
  sleep 20   # база могла ещё подниматься
  backup
fi

while true; do
  now=$(date +%s)
  next=$(date -d "today 04:00" +%s)
  [ "$next" -le "$now" ] && next=$(date -d "tomorrow 04:00" +%s)
  sleep $((next - now))
  backup
done
