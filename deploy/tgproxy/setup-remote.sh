#!/bin/sh
# Запускать на ЗАРУБЕЖНОМ сервере от root:  sh setup-remote.sh 'ssh-ed25519 AAAA... dragon-tgproxy'
# Создаёт пользователя tunnel без входа в консоль: ключ разрешает только проброс соединений.
set -eu
PUB="${1:?передайте публичный ключ в кавычках}"
id tunnel >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin tunnel
install -d -m 700 -o tunnel -g tunnel /home/tunnel/.ssh
echo "restrict,port-forwarding $PUB" > /home/tunnel/.ssh/authorized_keys
chown tunnel:tunnel /home/tunnel/.ssh/authorized_keys
chmod 600 /home/tunnel/.ssh/authorized_keys
echo "Готово. Проверка доступа к Telegram отсюда:"
curl -sS -m 10 -o /dev/null -w "api.telegram.org -> HTTP %{http_code}\n" https://api.telegram.org || true
