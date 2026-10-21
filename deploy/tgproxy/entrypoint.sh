#!/bin/sh
# Держит SSH-туннель открытым; при обрыве переподключается через 5 секунд.
set -u
: "${TGPROXY_HOST:?задайте TGPROXY_HOST в .env - IP зарубежного сервера}"
USER_="${TGPROXY_USER:-tunnel}"
PORT="${TGPROXY_PORT:-22}"
KEY=/keys/id_ed25519
[ -f "$KEY" ] || { echo "нет ключа $KEY - см. deploy/tgproxy/README.md"; sleep 60; exit 1; }
install -m 600 "$KEY" /tmp/key
while true; do
  echo "туннель -> $USER_@$TGPROXY_HOST:$PORT"
  ssh -N -D 0.0.0.0:1080 -i /tmp/key -p "$PORT" \
      -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/keys/known_hosts \
      -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
      -o ConnectTimeout=15 "$USER_@$TGPROXY_HOST"
  echo "туннель оборвался (код $?), переподключение через 5 с"
  sleep 5
done
