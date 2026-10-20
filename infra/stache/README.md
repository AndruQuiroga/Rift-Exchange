# Stache releases

Rift uses SSH to Swarm, Git manifests, and GHCR image digests. Portainer is an
observer for this stack. Existing applications retain their current owners.
GitHub Actions has no production deployment credentials.

## Configuration and deployment

Copy `target.example.psd1` to the ignored `target.local.psd1`. Fill its manager SSH
alias, expected hostname/account/cluster, distinct data/backup nodes, backup SSH
alias, ingress overlay and private ingress origin using the private infrastructure
wiki. Never commit the completed file. Preserve host trust and use an already
loaded workstation SSH key over the existing private connection.

The `Validate and publish` workflow runs backend tests/lint, a fresh migration and
schema-drift check, frontend checks, manifest validation and image builds. Pushes
to the default branch, `main`, or `codex/**` publish only after validation. Pull
requests build without publication. Use the image digests from a successful run.

```powershell
./infra/stache/preflight.ps1
./infra/stache/deploy.ps1 `
  -ApiImage 'ghcr.io/andruquiroga/rift-api@sha256:VALIDATED_DIGEST' `
  -WebImage 'ghcr.io/andruquiroga/rift-web@sha256:VALIDATED_DIGEST' `
  -ReleaseId 'COMMITPREFIX-20261020T120000Z'
```

Release IDs use 7-40 lowercase commit hex characters followed by a UTC timestamp.
Use a new ID for every attempt. The helper uploads reviewed files to
`~/rift-exchange/releases/<id>` on the configured manager, verifies identity and
ownership, serializes releases with `flock`, verifies pulls, provisions initial
secrets privately, and stops API/worker writes before snapshot and migration.
The configured manager must also be the data node for local snapshot checks.
A short maintenance window is expected during updates.

Migrations and initialization run as temporary Swarm services on the private data
network. Failure leaves the application paused and retains the failing task for
diagnosis. No automatic database rollback occurs. The helper changes
`~/rift-exchange/current` only after API/web/worker health and private Traefik
readiness pass. Inspect backup health on its configured separate node as well.

For a failed job, inspect `docker service ps rift-job-<id>-<job>` first. Its logs
may contain provider details; keep them private. After diagnosis remove only that
temporary job if needed, preserve application volumes, and retry with a new ID.

## Leaguepedia credentials and live mode

Sign in at https://lol.fandom.com/wiki/Special:BotPasswords and create an
application password named `RiftExchange`. Grant only read/Cargo access offered
by the site; editing and account-management permissions are unnecessary. Save
the exact login pair shown by Fandom (including its bot-name format), rather
than the main account password. See [Fandom's login documentation](https://help.fandom.com/wiki/Logging_in_to_third-party_tools).

Keep the pair out of chat, Git, command arguments and logs. Provision external
Swarm secrets `rift_leaguepedia_bot_user_v1` and
`rift_leaguepedia_bot_password_v1` through the existing private SSH connection,
using stdin or protected files with `docker secret create`. Do not overwrite
existing secrets blindly; Swarm secrets are immutable. The application reads
them through the existing `RIFT_*_FILE` settings support.

After the local authenticated probe succeeds, `./infra/stache/provision-leaguepedia.ps1`
can transfer protected local files through SSH stdin. Its defaults are the
ignored `artifacts/leaguepedia-bot-user.txt` and `artifacts/leaguepedia-bot-password.txt`.
It verifies the deployment target and refuses to replace either existing secret.
If interrupted after creating one secret, inspect the partial provisioning before
retrying. The helper does not enable live mode.

Deploy validated images built from these changes using the usual command plus
`-LeaguepediaMode live`. The helper checks that both secrets exist before
pausing the application, merges `leaguepedia-live.yml`, and runs
`python -m rift.operations check-leaguepedia` as a private release job before
bootstrap. A failed login, Cargo error, or empty/unparseable game probe blocks
the release. Subsequent releases preserve the last successful mode; explicitly
use `-LeaguepediaMode mock` to disable it.

The probe confirms login and a query against the game/ban tables. It does not
prove current tournament coverage or safe grading. Inspect representative
fixtures and provider errors separately. Leaguepedia currently supplies winner
cross-checks; its ban rows are parsed but not yet persisted or used by a ban
market generator. Champion picks and total-kill props use LoL Esports final
frames and require enough verified tournament games. Pre-series player props
remain deferred pending a roster source. Enabling live mode alone does not
enable these missing market types.

For a local probe, set `RIFT_LEAGUEPEDIA_MODE=live` and point
`RIFT_LEAGUEPEDIA_BOT_USER_FILE` / `RIFT_LEAGUEPEDIA_BOT_PASSWORD_FILE` to
protected files, then run `python -m rift.operations check-leaguepedia` from the
backend environment. This probe does not require a database.

## Data and status

Postgres uses `rift-exchange_database` on the configured data node. Backups use
`rift-exchange_backups` on the distinct backup node. Both are node-local: preserve
placement. Postgres 16 and application releases are digest-pinned. Secret names
are `rift_postgres_password_v1` and `rift_database_url_v1`; values are never printed.

At the configured manager, use:

```sh
docker stack services rift-exchange
docker stack ps rift-exchange --no-trunc
```

Public readiness: `https://rift.mustache.network/api/v1/health/ready`. Liveness:
`/api/v1/healthz`. Readiness tests migration metadata and the initialized season.
Worker health requires recent successful lock/grant jobs; authenticated admin
health shows provider failures separately. Core health is not proof that every
upstream provider is available.

Daily custom-format dumps are written on the separate backup node. They are kept
for about fourteen days; backup health fails if no dump is newer than 25 hours.
Every deployment forces an immediate post-migration dump. Updates also save
`~/rift-exchange/pre-<release>.dump` on the data node; review their retention manually.
Both copies remain in the same rack, so an external destination is a future addition.

Rehearse restoration by exporting a scheduled dump to ignored local
`artifacts/backups`, restoring into isolated Postgres 16 and verifying the schema
revision, season, fixture/market counts and ledger reconciliation. Never rehearse
by restoring over production data.

## Ingress, invites and recovery

The explicit public hostname uses the existing tunnel and private ingress origin.
Traefik routes `/api` to FastAPI without stripping the prefix. No database/API host
ports are published. HTTPS terminates at Cloudflare, cookies use Secure/HttpOnly,
API responses are no-store, and the app's router/API access logs are disabled.

Create an invite by executing `rift invite --admin` or `rift invite` in the API
container. Capture the output into a private file, not release logs or a PR. Share
`https://rift.mustache.network/join?code=<code>` privately. A code creates one
account. V0 sessions last 60 days; returning-account sign-in/recovery is not yet
implemented. Preserve the session cookie and avoid logging out until recovery is
added. Do not create duplicate accounts with fresh invites as a workaround.

For an application rollback with a compatible schema, deploy previous healthy
digests with a new release ID. Review migrations first. Do not automatically
run Alembic downgrade, restore over live writes or delete persistent volumes.

See [the deployment design](../../docs/deployment/stache.md) for release acceptance
and the dated launch record for verified results and outstanding limitations.
