# Local development. Requires PostgreSQL 16, uv and Node 22.
API := services/api
WEB := apps/web

.PHONY: setup migrate worker cycle api web test e2e invite backtest lint

setup:
	cd $(API) && uv sync
	cd $(WEB) && npm ci

migrate:
	cd $(API) && uv run alembic upgrade head

cycle:            ## one worker pass: sync schedule, price markets, lock, settle, grant
	cd $(API) && uv run rift cycle

worker:
	cd $(API) && uv run rift worker

api:
	cd $(API) && uv run rift api --port 8000

web:
	cd $(WEB) && npm run dev

invite:           ## make invite ADMIN=1 for the admin
	cd $(API) && uv run rift invite $(if $(ADMIN),--admin,)

backtest:
	cd $(API) && uv run rift backtest

test:
	cd $(API) && uv run pytest -q
	cd $(WEB) && npm run typecheck && npm run lint

lint:
	cd $(API) && uv run ruff check src tests

e2e:              ## make e2e CODES="code1 code2 code3" (fresh invites; web on :3000)
	cd $(WEB) && node e2e/walkthrough.mjs http://localhost:3000 ../../docs/screens $(CODES)
