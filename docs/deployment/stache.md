# Rift Exchange on Stache

The first release uses Git-reviewed Swarm manifests and immutable GHCR images,
applied through the existing private SSH connection. Portainer remains an observer
for this new stack. Existing Portainer-managed applications retain their current
update path. Each stack has one deployment writer.

## Deployment options

| Method | Assessment |
| --- | --- |
| SSH to Swarm | Chosen for Rift. Existing agent access works; no recurring Portainer login session is required. |
| Portainer API access token | Suitable alternative when Portainer ownership is wanted. Separate from an expiring login JWT; validate permissions and lifecycle for the installed version. |
| CI runner inside the private network | Possible later; adds privileged execution infrastructure and maintenance. Keep untrusted PR code away from deployment credentials. |

The short-lived session in the previous infrastructure helper is not the only
Portainer authentication method. [Portainer documents user API access tokens](https://docs.portainer.io/api/access)
using `X-API-Key`. SSH was chosen to reuse the already working private management
path. Docker access remains administrative; keys stay on the workstation, host
checking stays enabled, and management endpoints remain private.

## Application design

Public HTTPS at `rift.mustache.network` reaches the existing tunnel and Traefik.
Web and API share this hostname. The higher-priority `/api` router preserves the
prefix because FastAPI already serves `/api/v1`. Postgres and the single worker
use a dedicated data overlay. No application host ports are published.

The database volume is pinned to the selected application node. Daily backups are
written on a separate node, with approximately fourteen days of retention and a
freshness health check. This protects against loss of one application VM, not
rack-wide loss. Rehearse restoration before considering the release verified.

Private infrastructure inventory belongs in the ignored
`infra/stache/target.local.psd1`, based on `target.example.psd1`. The repository
does not contain actual management addresses, host identities or cluster IDs.
Dated private inventory remains in the separate infrastructure documentation.

## Deployment implementation

- Frozen Python/npm dependencies, tested API/web image builds and CI publication.
- Explicit Docker secret-file configuration shared by API, worker, CLI and Alembic.
- Secure session cookies, no-store API responses, and access logging disabled for
  the app's routers/API so invite URLs do not enter application access logs.
- Database/season readiness, process liveness and worker freshness probes.
- A serialized release helper that verifies the target cluster and ownership,
  pulls digests, pauses API/worker writes, backs up existing data, gates on migration
  and bootstrap success, then checks container health and private ingress.
- Standalone non-root Next.js image, explicit production proxy build configuration,
  and secret exclusions in Docker build contexts.
- Node-constrained persistent volumes, bounded logs and memory, and a separate
  backup node. An image rollback never automatically downgrades/restores a database.

## Release acceptance

1. CI passes backend tests/lint, fresh migrations and schema drift checks, frontend
   checks, Swarm validation, and both image builds. Record published image digests.
2. Private preflight verifies the intended manager, cluster and ingress overlay.
3. The reviewed release succeeds with fresh secrets and a dedicated database.
4. API/web/worker and backup health pass. Provider sync, season and usable markets
   are verified independently of the process health checks.
5. A scheduled dump restores into isolated Postgres with the expected migration,
   season and ledger reconciliation result.
6. Public HTTPS, invite enforcement, Secure/HttpOnly cookies, no-store API responses,
   and SSE behavior are checked. Create/share invite links privately.

For exact commands, release behavior, troubleshooting and recovery, see
[the operations guide](../../infra/stache/README.md). Existing product/data-source
release decisions in `docs/spec` are not changed by this infrastructure work.

## References

- [Docker Swarm deployment and its v3 manifest format](https://docs.docker.com/engine/swarm/stack-deploy/)
- [Docker access over SSH](https://docs.docker.com/engine/security/protect-access/)
- [Swarm secrets](https://docs.docker.com/engine/swarm/secrets/)
- [Next.js rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites)
- [Traefik router access log controls](https://doc.traefik.io/traefik/observe/logs-and-access-logs/)
