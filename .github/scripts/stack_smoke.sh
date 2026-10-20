#!/bin/sh
# Поднимает весь проект (docker compose) и проверяет, что страницы сайта, которые рендерит сервер,
# показывают данные из API. Ловит ошибки связки сайт -> API, которые не видны тестам и сборке.
set -e
docker compose up -d
for i in $(seq 1 60); do curl -sf localhost:8000/health >/dev/null && break; sleep 2; done
for i in $(seq 1 60); do curl -sf localhost:3000/ >/dev/null && break; sleep 2; done
TOKEN=$(curl -sf -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"smoke@example.com","password":"smoke-pass-1","nickname":"Smoke"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
CLUB=$(curl -sf -X POST localhost:8000/clubs -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Проверочный клуб","city":"Тест"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
TID=$(curl -sf -X POST localhost:8000/tournaments -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"club_id\":$CLUB,\"name\":\"Проверочный турнир\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
fail=0
check() {  # url, ожидаемый текст
  if curl -sf "localhost:3000$1" | grep -q "$2"; then echo "OK   $1"; else echo "FAIL $1: нет «$2»"; fail=1; fi
}
check / "Проверочный турнир"
check /tournaments "Проверочный турнир"
check "/tournaments/$TID" "Проверочный клуб"
check /clubs "Проверочный клуб"
check /api/clubs "Проверочный клуб"
if [ $fail = 1 ]; then docker compose logs --tail=40 frontend backend; exit 1; fi
