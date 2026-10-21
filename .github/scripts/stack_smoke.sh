#!/bin/sh
# Поднимает весь проект (docker compose) и проверяет, что страницы сайта, которые рендерит сервер,
# показывают данные из API. Ловит ошибки связки сайт -> API, которые не видны тестам и сборке.
set -e
docker compose up -d
for i in $(seq 1 90); do curl -sf localhost:8000/health >/dev/null && break; sleep 2; done
for i in $(seq 1 90); do curl -sf localhost:3000/ >/dev/null && break; sleep 2; done
curl -sf localhost:8000/health >/dev/null || { echo "FAIL: API не поднялся"; docker compose ps; docker compose logs --tail=80 backend; exit 1; }
curl -sf localhost:3000/ >/dev/null || { echo "FAIL: сайт не поднялся"; docker compose logs --tail=60 frontend; exit 1; }

# POST к API: печатает ответ при ошибке, иначе возвращает поле из JSON
post() {  # путь, json, поле, [токен]
  out=$(curl -s -w '\n%{http_code}' -X POST "localhost:8000$1" -H 'Content-Type: application/json' \
        ${4:+-H "Authorization: Bearer $4"} -d "$2")
  code=$(printf '%s' "$out" | tail -n1); body=$(printf '%s' "$out" | sed '$d')
  case "$code" in 2*) printf '%s' "$body" | python3 -c "import sys,json;print(json.load(sys.stdin)['$3'])" ;;
    *) echo "POST $1 -> $code: $body" >&2; docker compose logs --tail=60 backend >&2; exit 1 ;; esac
}
TOKEN=$(post /auth/register '{"email":"smoke@example.com","password":"smoke-pass-1","nickname":"Smoke"}' access_token)
# клуб создаёт только «Создатель Клуба»: в проверке статус выдаём прямо в базе
docker compose exec -T db psql -U kki -qc "UPDATE users SET is_club_creator = true WHERE nickname = 'Smoke'" >/dev/null
CLUB=$(post /clubs '{"name":"Проверочный клуб","city":"Тест"}' id "$TOKEN")
TID=$(post /tournaments "{\"club_id\":$CLUB,\"name\":\"Проверочный турнир\"}" id "$TOKEN")

fail=0
check() {  # url, ожидаемый текст
  if curl -sf "localhost:3000$1" | grep -q "$2"; then echo "OK   $1"; else echo "FAIL $1: нет «$2»"; fail=1; fi
}
check / "Проверочный турнир"
check /tournaments "Проверочный турнир"
check "/tournaments/$TID" "Проверочный клуб"
check /clubs "Проверочный клуб"
check /clubs/proverochnyy-klub "Проверочный клуб"
check /api/clubs "Проверочный клуб"
if [ $fail = 1 ]; then docker compose logs --tail=40 frontend backend; exit 1; fi
