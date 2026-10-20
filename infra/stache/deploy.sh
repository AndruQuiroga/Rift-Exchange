#!/bin/sh
# Runs on the configured Docker manager. No set -x: secrets stay private.
set -eu
umask 077
cd "$(dirname "$0")"
export API_IMAGE=$1 WEB_IMAGE=$2 RELEASE_ID=$3
. ./target.env
export DATA_NODE BACKUP_NODE INGRESS_NETWORK
root="$HOME/rift-exchange"
mkdir -p "$root"
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another Rift release is running' >&2; exit 1; }
test "$(hostname)" = "$EXPECTED_HOST"
test "$(id -un)" = "$EXPECTED_USER"
test "$(docker info --format '{{.Swarm.Cluster.ID}}')" = "$EXPECTED_SWARM_ID"
test "$(docker info --format '{{.Swarm.ControlAvailable}}')" = true
docker network inspect "$INGRESS_NETWORK" >/dev/null
docker stack config -c stack.yml >/dev/null
if docker stack ls --format '{{.Name}}' | grep -qx rift-exchange &&
   ! docker service inspect rift-exchange_api >/dev/null 2>&1; then
    echo 'Existing Rift stack has no recognizable owner; refusing adoption' >&2
    exit 1
fi

# Any existing stack must have been created by this deployment path.
existing=false
if docker service inspect rift-exchange_api >/dev/null 2>&1; then
    existing=true
    test "$(docker service inspect rift-exchange_api --format '{{index .Spec.Labels "io.stache.deployment-owner"}}')" = ssh-git
fi
docker pull "$API_IMAGE" >/dev/null
docker pull "$WEB_IMAGE" >/dev/null

password_exists=false
url_exists=false
docker secret inspect rift_postgres_password_v1 >/dev/null 2>&1 && password_exists=true
docker secret inspect rift_database_url_v1 >/dev/null 2>&1 && url_exists=true
if [ "$password_exists" != "$url_exists" ]; then
    echo 'Partial secret provisioning; recover the existing credentials before continuing' >&2
    exit 1
fi
if [ "$password_exists" = false ]; then
    test "$existing" = false
    # Hex avoids URL escaping and keeps the value out of process arguments.
    password=$(openssl rand -hex 32)
    printf '%s' "$password" | docker secret create rift_postgres_password_v1 - >/dev/null
    printf 'postgresql+psycopg://rift:%s@rift-exchange_db:5432/rift?connect_timeout=5' "$password" |
        docker secret create rift_database_url_v1 - >/dev/null
    unset password
fi

wait_service() {
    service=$1
    for attempt in $(seq 1 120); do
        count=$(docker service ps "$service" --filter desired-state=running --format '{{.CurrentState}}' | grep -c '^Running ' || true)
        if [ "$count" = 1 ]; then return; fi
        sleep 5
    done
    echo "Timed out waiting for $service; inspect its task status" >&2
    exit 1
}

run_job() {
    name="rift-job-$RELEASE_ID-$1"
    shift
    docker service create --detach=true --quiet --name "$name" --label io.stache.deployment-owner=ssh-git \
        --constraint "node.hostname==$DATA_NODE" --restart-condition none \
        --network rift-exchange_data --secret source=rift_database_url_v1,target=database_url \
        --env RIFT_DATABASE_URL_FILE=/run/secrets/database_url --env RIFT_COOKIE_SECURE=true \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=2 \
        "$API_IMAGE" "$@" >/dev/null
    for attempt in $(seq 1 240); do
        task=$(docker service ps "$name" --no-trunc --format '{{.ID}}' | head -1)
        if [ -n "$task" ]; then
            state=$(docker inspect "$task" --format '{{.Status.State}}')
            case "$state" in
                complete)
                    code=$(docker inspect "$task" --format '{{.Status.ContainerStatus.ExitCode}}')
                    test "$code" = 0 || { echo "Job $name exited with $code" >&2; exit 1; }
                    docker service rm "$name" >/dev/null
                    return ;;
                failed|rejected)
                    echo "Job $name $state; inspect its private logs. App remains paused." >&2
                    exit 1 ;;
            esac
        fi
        sleep 5
    done
    echo "Job $name timed out; app remains paused" >&2
    exit 1
}

if [ "$existing" = true ]; then
    # Stop writes and the scheduler before the snapshot/migration.
    docker service scale --detach=true rift-exchange_worker=0 rift-exchange_api=0 >/dev/null
    for attempt in $(seq 1 120); do
        count=$({ docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_api; docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_worker; } | wc -l)
        test "$count" = 0 && break
        sleep 2
    done
    test "$count" = 0
    db=$(docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_db)
    test -n "$db"
    # Kept on DB VM for immediate recovery; scheduled backups use a separate node.
    docker exec "$db" pg_dump -U rift -d rift -Fc > "$root/pre-$RELEASE_ID.dump.tmp"
    test -s "$root/pre-$RELEASE_ID.dump.tmp"
    docker exec -i "$db" pg_restore --list < "$root/pre-$RELEASE_ID.dump.tmp" >/dev/null
    mv "$root/pre-$RELEASE_ID.dump.tmp" "$root/pre-$RELEASE_ID.dump"
fi

# Data-only bootstrap. Swarm does not provide Compose's depends_on gating.
APP_REPLICAS=0 docker stack deploy --detach=true --resolve-image always -c stack.yml rift-exchange
wait_service rift-exchange_db
run_job wait-db python -m rift.operations wait-db
run_job migrate alembic upgrade head
run_job bootstrap python -m rift.operations bootstrap
APP_REPLICAS=1 docker stack deploy --detach=true --resolve-image always -c stack.yml rift-exchange
# Take a post-migration dump promptly, including on the first deployment.
docker service update --force --detach=true rift-exchange_backup >/dev/null
for svc in api worker web backup; do wait_service "rift-exchange_$svc"; done

for attempt in $(seq 1 120); do
    if curl -fsS -H 'Host: rift.mustache.network' "$INGRESS_ORIGIN/api/v1/health/ready" >/dev/null &&
       curl -fsS -H 'Host: rift.mustache.network' "$INGRESS_ORIGIN/join" >/dev/null; then
        api=$(docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_api)
        web=$(docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_web)
        worker=$(docker ps -q --filter label=com.docker.swarm.service.name=rift-exchange_worker)
        if [ -n "$api" ] && [ -n "$web" ] && [ -n "$worker" ] &&
           [ "$(docker inspect "$api" --format '{{.State.Health.Status}}')" = healthy ] &&
           [ "$(docker inspect "$web" --format '{{.State.Health.Status}}')" = healthy ] &&
           [ "$(docker inspect "$worker" --format '{{.State.Health.Status}}')" = healthy ]; then
            printf 'API_IMAGE=%s\nWEB_IMAGE=%s\nRELEASE_ID=%s\n' "$API_IMAGE" "$WEB_IMAGE" "$RELEASE_ID" > release.env
            ln -sfn "$(pwd)" "$root/current"
            echo "Rift release $RELEASE_ID healthy through Traefik"
            exit 0
        fi
    fi
    sleep 5
done
echo 'Readiness timeout. Preserve database and inspect tasks; do not downgrade schema automatically.' >&2
exit 1
