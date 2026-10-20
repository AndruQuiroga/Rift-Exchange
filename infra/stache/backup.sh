#!/bin/sh
set -eu
umask 077
mkdir -p /backups
export PGPASSWORD="$(cat /run/secrets/postgres_password)"
while true; do
    if pg_isready -h rift-exchange_db -U rift -d rift >/dev/null 2>&1; then
        stamp=$(date -u +%Y%m%dT%H%M%SZ)
        if pg_dump -h rift-exchange_db -U rift -d rift -Fc -f "/backups/rift-$stamp.dump.tmp"; then
            pg_restore --list "/backups/rift-$stamp.dump.tmp" >/dev/null
            mv "/backups/rift-$stamp.dump.tmp" "/backups/rift-$stamp.dump"
            find /backups -type f -name '*.dump' -mtime +14 -delete
            echo "Database backup completed on $(hostname)"
            sleep 86400
        else
            echo 'Database backup failed; retrying in 60 seconds' >&2
            sleep 60
        fi
    else
        sleep 10
    fi
done
