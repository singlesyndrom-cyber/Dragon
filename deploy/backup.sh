#!/bin/sh
# Ежедневная копия базы. Хранит последние 14 копий в ./backups.
# cron: 0 4 * * * cd /opt/dragon && sh deploy/backup.sh
set -e
mkdir -p backups
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U kki kki | gzip > "backups/kki-$(date +%F).sql.gz"
ls -1t backups/kki-*.sql.gz | tail -n +15 | xargs -r rm --
