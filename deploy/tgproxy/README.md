# Прокси для Telegram-бота

Нужен, если сервер не достаёт до `api.telegram.org` (проверка: `curl -m 10 -sI https://api.telegram.org` зависает).
Через туннель идёт только трафик бота (и фото лотов аукциона); сайт, база и почта работают напрямую.
Если туннель упадёт, сообщения копятся в очереди и уйдут, когда связь вернётся.

Понадобится любой дешёвый VPS за рубежом (Финляндия, Нидерланды, Германия; 1 CPU / 512 МБ хватит).

## 1. Ключ на нашем сервере
```
cd /opt/dragon
mkdir -p deploy/tgproxy/keys
ssh-keygen -t ed25519 -N "" -C dragon-tgproxy -f deploy/tgproxy/keys/id_ed25519
cat deploy/tgproxy/keys/id_ed25519.pub
```
Ключи лежат только на сервере, в git не попадают.

## 2. Зарубежный сервер
Скопируйте туда `deploy/tgproxy/setup-remote.sh` (или вставьте его текст в `nano setup-remote.sh`) и выполните от root:
```
sh setup-remote.sh 'ssh-ed25519 AAAA... dragon-tgproxy'
```
(в кавычках - строка, которую вывела команда `cat ... .pub`).

## 3. .env на нашем сервере
```
COMPOSE_PROFILES=tgproxy
TGPROXY_HOST=<IP зарубежного сервера>
TELEGRAM_PROXY=socks5://tgproxy:1080
```

## 4. Запуск
```
docker compose -f docker-compose.prod.yml up -d --build tgproxy backend bot
docker compose -f docker-compose.prod.yml logs --tail=20 tgproxy bot
```
В логе бота должно появиться `Run polling for bot @...`.
