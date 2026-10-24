"""HTTP API /api/v1 (docs/spec/09_API_CONTRACTS.md)."""

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rift import auth, draft, ledger, markets, props, swiss_card
from rift.api import views
from rift.config import Settings, get_settings
from rift.db import db_now, session_factory
from rift.models import (
    AuditEvent,
    Fixture,
    Market,
    OddsSnapshot,
    OutboxEvent,
    Outcome,
    ProviderSync,
    Reaction,
    Season,
    Selection,
    Ticket,
    User,
    Wallet,
)
from rift.placement import PlacementError, QuoteItem, accept_ticket, cancel_selection, create_quote

COOKIE = "rift_session"
CLIENT_HEADER = "x-rift-client"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def create_app(settings: Settings | None = None, factory=None) -> FastAPI:
    settings = settings or get_settings()
    factory = factory or session_factory()
    app = FastAPI(title="Rift Exchange", version="0.1.0", openapi_url="/api/v1/openapi.json",
                  docs_url="/api/v1/docs")

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content={"error": {
            "code": exc.code, "message": exc.message, "details": exc.details,
            "request_id": request.headers.get("x-request-id")}})

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        # The same envelope as every other error, so the client can show what was wrong.
        fields = [".".join(str(p) for p in e.get("loc", ())[1:]) or "request" for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {
            "code": "INVALID_REQUEST", "message": f"That request wasn't valid ({', '.join(fields)}).",
            "details": {"fields": fields}, "request_id": request.headers.get("x-request-id")}})

    @app.middleware("http")
    async def _csrf(request: Request, call_next):
        # Cookie-authenticated writes must carry a custom header, which cross-site forms cannot send.
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
                and request.headers.get(CLIENT_HEADER) != "web":
            return JSONResponse(status_code=403, content={"error": {
                "code": "CSRF", "message": "Missing client header.", "details": {}}})
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ------------------------------------------------------------ dependencies

    def db() -> Iterator[Session]:
        with factory() as session, session.begin():
            yield session

    Db = Annotated[Session, Depends(db)]

    def season_of(session: Session) -> Season:
        season = session.execute(select(Season).where(Season.code == settings.season_code)).scalar_one_or_none()
        if season is None:
            raise ApiError(503, "SEASON_NOT_READY", "The season has not been initialised yet.")
        return season

    def current_user(request: Request, session: Db) -> User:
        user = auth.user_for_token(session, request.cookies.get(COOKIE), db_now(session))
        if user is None:
            raise ApiError(401, "UNAUTHENTICATED", "Sign in with your invite link.")
        return user

    CurrentUser = Annotated[User, Depends(current_user)]

    def admin_user(user: CurrentUser) -> User:
        if user.role != "ADMIN":
            raise ApiError(403, "FORBIDDEN", "Admins only.")
        return user

    def wallet_of(session: Session, season: Season, user: User) -> Wallet:
        wallet = session.execute(select(Wallet).where(Wallet.season_id == season.id, Wallet.user_id == user.id)
                                 ).scalar_one_or_none()
        if wallet is None:
            raise ApiError(403, "NOT_A_MEMBER", "You have not joined this season.")
        return wallet

    def placement_error(e: PlacementError) -> ApiError:
        status = 404 if e.code in ("UNKNOWN_QUOTE", "UNKNOWN_OUTCOME") else \
            400 if e.code in ("EMPTY_SLIP", "INVALID_STAKE", "DUPLICATE_OUTCOME", "CONFLICTING_PICKS",
                              "BAD_IDEMPOTENCY_KEY") else 409
        return ApiError(status, e.code, e.message, e.details)

    # ------------------------------------------------------------ auth

    class RedeemBody(BaseModel):
        code: str
        name: str = ""
        handle: str = ""  # older clients sent a separate handle; it now serves as the name

    @app.post("/api/v1/auth/redeem")
    def redeem(body: RedeemBody, response: Response, session: Db):
        season = season_of(session)
        try:
            user, token = auth.redeem_invite(session, season, body.code, body.name or body.handle,
                                             db_now(session), settings.session_days)
        except auth.AuthError as e:
            raise ApiError(400, e.code, e.message) from e
        return signed_in(response, user, token)

    def signed_in(response: Response, user: User, token: str) -> dict:
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                            max_age=settings.session_days * 86400, path="/")
        return {"user": {"id": str(user.id), "handle": user.handle, "display_name": user.display_name}}

    @app.post("/api/v1/auth/sign-in-codes")
    def new_sign_in_code(user: CurrentUser, session: Db):
        code, expires_at = auth.create_sign_in_code(session, user, db_now(session))
        return {"code": code, "expires_at": expires_at.isoformat()}

    class SignInBody(BaseModel):
        code: str

    @app.post("/api/v1/auth/sign-in")
    def sign_in(body: SignInBody, response: Response, session: Db):
        try:
            user, token = auth.redeem_sign_in_code(session, body.code, db_now(session), settings.session_days)
        except auth.AuthError as e:
            raise ApiError(400, e.code, e.message) from e
        return signed_in(response, user, token)

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, session: Db):
        token = request.cookies.get(COOKIE)
        if token:
            row = session.get(auth.Session, auth.digest(token))
            if row:
                session.delete(row)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    # ------------------------------------------------------------ browse

    @app.get("/api/v1/me")
    def me(user: CurrentUser, session: Db):
        season = season_of(session)
        wallet = wallet_of(session, season, user)
        return {"user": {"id": str(user.id), "handle": user.handle, "display_name": user.display_name,
                         "role": user.role},
                "wallet": views.wallet_summary(session, wallet)}

    @app.get("/api/v1/season/current")
    def current_season(session: Db):
        season = season_of(session)
        now = db_now(session)
        days = session.execute(select(Fixture.local_date, Fixture.stage).where(Fixture.season_id == season.id)
                               .distinct().order_by(Fixture.local_date)).all()
        syncs = {r.job: r for r in session.execute(select(ProviderSync)).scalars()}
        sched = syncs.get("schedule")
        return {"code": season.code, "name": season.name, "timezone": season.timezone,
                "server_time": now.isoformat(),
                "opening_grant_rc": season.opening_grant_rc, "match_day_grant_rc": season.match_day_grant_rc,
                "first_match_day": season.first_match_day.isoformat(),
                "match_days": sorted({d.isoformat() for d, _ in days if d >= season.first_match_day}),
                "stages_by_day": {d.isoformat(): s for d, s in days},
                "data_as_of": sched.last_ok_at.isoformat() if sched and sched.last_ok_at else None}

    @app.get("/api/v1/events")
    def list_events(session: Db, user: CurrentUser, date: str | None = None, stage: str | None = None):
        return {"events": views.events(session, season_of(session), date, stage, db_now(session))}

    @app.get("/api/v1/events/{event_id}")
    def get_event(event_id: uuid.UUID, session: Db, user: CurrentUser):
        fixture = session.get(Fixture, event_id)
        if fixture is None:
            raise ApiError(404, "NOT_FOUND", "Event not found.")
        return views.event_detail(session, fixture, db_now(session))

    @app.get("/api/v1/events/{event_id}/live")
    def get_event_live(event_id: uuid.UUID, session: Db, user: CurrentUser):
        # Served from what the worker stored; an API request never calls the feed.
        fixture = session.get(Fixture, event_id)
        if fixture is None:
            raise ApiError(404, "NOT_FOUND", "Event not found.")
        return views.live_view(session, fixture, user)

    @app.get("/api/v1/markets")
    def list_markets(session: Db, user: CurrentUser, category: str | None = None):
        return {"markets": views.season_markets(session, season_of(session), category)}

    @app.get("/api/v1/markets/{market_id}/history")
    def market_history(market_id: uuid.UUID, session: Db, user: CurrentUser):
        rows = session.execute(
            select(Outcome.code, OddsSnapshot.version, OddsSnapshot.odds, OddsSnapshot.created_at)
            .join(Outcome, Outcome.id == OddsSnapshot.outcome_id).where(Outcome.market_id == market_id)
            .order_by(OddsSnapshot.created_at)).all()
        return {"history": [{"outcome": c, "version": v, "odds": str(o) if o is not None else None,
                             "at": t.isoformat()} for c, v, o, t in rows]}

    # ------------------------------------------------------------ slip

    def _market_out(session: Session, market: Market) -> dict:
        outcomes = list(session.execute(select(Outcome).where(Outcome.market_id == market.id)).scalars())
        return views.market_view(market, outcomes)

    @app.get("/api/v1/events/{event_id}/duels")
    def duel_grid(event_id: uuid.UUID, session: Db, user: CurrentUser, game: int = Query(1, ge=1, le=5)):
        return props.duels(session, season_of(session), _fixture(session, event_id), game, settings, db_now(session))

    class DuelBody(BaseModel):
        game_index: int = Field(ge=1, le=5)
        role: str = Field(pattern="^(top|jungle|mid|bottom|support)$")
        stat: str = Field(pattern=f"^({'|'.join(props.STATS)})$")  # ensure_duel checks it is still offered

    @app.post("/api/v1/events/{event_id}/duels")
    def duel_market(event_id: uuid.UUID, body: DuelBody, session: Db, user: CurrentUser):
        try:
            market = props.ensure_duel(session, season_of(session), _fixture(session, event_id), body.game_index,
                                       body.role, body.stat, settings, db_now(session))
        except props.PropsError as e:
            raise ApiError(409, e.code, e.message) from e
        return _market_out(session, market)

    @app.get("/api/v1/events/{event_id}/kill-lines")
    def kill_line_grid(event_id: uuid.UUID, session: Db, user: CurrentUser, game: int = Query(1, ge=1, le=5)):
        season = season_of(session)
        return props.kill_lines(session, _fixture(session, event_id), game, markets.tournament_stats(session, season),
                                settings, db_now(session))

    class KillLineBody(BaseModel):
        game_index: int = Field(ge=1, le=5)
        line: str = Field(pattern=r"^\d{1,2}\.5$")

    @app.post("/api/v1/events/{event_id}/kill-lines")
    def kill_line_market(event_id: uuid.UUID, body: KillLineBody, session: Db, user: CurrentUser):
        season = season_of(session)
        try:
            market = props.ensure_kill_line(session, season, _fixture(session, event_id), body.game_index, body.line,
                                            markets.tournament_stats(session, season), settings, db_now(session))
        except props.PropsError as e:
            raise ApiError(409, e.code, e.message) from e
        return _market_out(session, market)

    class QuoteBody(BaseModel):
        class Item(BaseModel):
            outcome_id: uuid.UUID
            stake_rc: int = Field(gt=0, le=10**12)

        items: list[Item] = Field(min_length=1, max_length=20)

    @app.post("/api/v1/quotes")
    def quote(body: QuoteBody, user: CurrentUser, session: Db):
        season = season_of(session)
        try:
            return create_quote(session, season_id=season.id, user_id=user.id,
                                items=[QuoteItem(i.outcome_id, i.stake_rc) for i in body.items],
                                now=db_now(session), ttl_seconds=settings.quote_ttl_seconds,
                                stake_cap_rc=settings.stake_cap_rc)
        except PlacementError as e:
            raise placement_error(e) from e

    def _fixture(session: Session, event_id: uuid.UUID) -> Fixture:
        fixture = session.get(Fixture, event_id)
        if fixture is None:
            raise ApiError(404, "NOT_FOUND", "Event not found.")
        return fixture

    @app.get("/api/v1/events/{event_id}/draft")
    def draft_grid(event_id: uuid.UUID, session: Db, user: CurrentUser, game: int = Query(1, ge=1, le=5)):
        try:
            return draft.grid(session, season_of(session), _fixture(session, event_id), game, settings,
                              db_now(session))
        except draft.DraftError as e:
            raise ApiError(409, e.code, e.message) from e

    class DraftMarketBody(BaseModel):
        game_index: int = Field(ge=1, le=5)
        champion: str = Field(min_length=1, max_length=40)
        scope: str = Field(pattern="^(picked|A|B|banned|first)$")

    @app.post("/api/v1/events/{event_id}/draft")
    def draft_market(event_id: uuid.UUID, body: DraftMarketBody, session: Db, user: CurrentUser):
        """Create (once, for everyone) the market behind a tapped champion and return it priced."""
        if body.scope != "picked":
            # Draft calls are trimmed to "picked by either team"; markets made earlier still settle.
            raise ApiError(409, "NOT_OFFERED", "Only 'picked by either team' draft calls are offered.")
        fixture = _fixture(session, event_id)
        try:
            market = draft.ensure_market(session, season_of(session), fixture, body.game_index, body.champion,
                                         body.scope, settings, db_now(session))
        except draft.DraftError as e:
            raise ApiError(409, e.code, e.message) from e
        outcomes = list(session.execute(select(Outcome).where(Outcome.market_id == market.id)).scalars())
        return views.market_view(market, outcomes)

    # ------------------------------------------------------------ Swiss record card (free calls)

    class CallBody(BaseModel):
        outcome_id: uuid.UUID

    def _card_error(e: swiss_card.CardError) -> ApiError:
        return ApiError(404 if e.code == "NOT_FOUND" else 409, e.code, e.message)

    @app.get("/api/v1/swiss/card")
    def get_card(session: Db, user: CurrentUser):
        return swiss_card.card(session, season_of(session), user.id, db_now(session))

    @app.put("/api/v1/swiss/card/{market_id}")
    def put_call(market_id: uuid.UUID, body: CallBody, session: Db, user: CurrentUser):
        season = season_of(session)
        try:
            swiss_card.set_call(session, season, user.id, market_id, body.outcome_id, db_now(session))
        except swiss_card.CardError as e:
            raise _card_error(e) from e
        return swiss_card.card(session, season, user.id, db_now(session))

    @app.delete("/api/v1/swiss/card/{market_id}")
    def delete_call(market_id: uuid.UUID, session: Db, user: CurrentUser):
        season = season_of(session)
        try:
            swiss_card.clear_call(session, season, user.id, market_id, db_now(session))
        except swiss_card.CardError as e:
            raise _card_error(e) from e
        return swiss_card.card(session, season, user.id, db_now(session))

    class TicketBody(BaseModel):
        quote_id: uuid.UUID
        confirm_odds_versions: dict[str, int]

    @app.post("/api/v1/tickets")
    def place_ticket(body: TicketBody, user: CurrentUser, response: Response,
                     idempotency_key: Annotated[str, Header()] = ""):
        # Own transaction so an ODDS_CHANGED rollback can be followed by a fresh quote.
        try:
            with factory() as session, session.begin():
                season = season_of(session)
                ticket, created = accept_ticket(
                    session, season_id=season.id, user_id=user.id, quote_id=body.quote_id,
                    confirm_odds_versions=body.confirm_odds_versions, idempotency_key=idempotency_key,
                    now=db_now(session), stake_cap_rc=settings.stake_cap_rc)
                response.status_code = 201 if created else 200
                return ticket_view(session, ticket)
        except PlacementError as e:
            if e.code != "ODDS_CHANGED":
                raise placement_error(e) from e
            with factory() as session, session.begin():
                season = season_of(session)
                previous = e.details["previous_items"]
                try:
                    new_quote = create_quote(
                        session, season_id=season.id, user_id=user.id,
                        items=[QuoteItem(uuid.UUID(i["outcome_id"]), i["stake_rc"]) for i in previous],
                        now=db_now(session), ttl_seconds=settings.quote_ttl_seconds,
                                stake_cap_rc=settings.stake_cap_rc)
                except PlacementError as inner:
                    raise placement_error(inner) from inner
            raise ApiError(409, "ODDS_CHANGED", e.message,
                           {"outcome_ids": e.details["outcome_ids"], "previous_items": previous,
                            "new_quote": new_quote}) from e

    def ticket_view(session: Session, ticket: Ticket) -> dict:
        sels = list(session.execute(select(Selection).where(Selection.ticket_id == ticket.id)).scalars())
        wallet = wallet_of(session, session.get(Season, ticket.season_id), session.get(User, ticket.user_id))
        return {"ticket_id": str(ticket.id), "accepted_at": ticket.accepted_at.isoformat(),
                "total_stake_rc": ticket.total_stake_rc, "selections": views.selection_rows(session, sels),
                "wallet": views.wallet_summary(session, wallet)}

    @app.get("/api/v1/tickets/by-key/{key}")
    def ticket_by_key(key: str, user: CurrentUser, session: Db):
        season = season_of(session)
        ticket = session.execute(select(Ticket).where(Ticket.user_id == user.id, Ticket.season_id == season.id,
                                                      Ticket.idempotency_key == key)).scalar_one_or_none()
        if ticket is None:
            raise ApiError(404, "NOT_FOUND", "No ticket was placed with that key.")
        return ticket_view(session, ticket)

    @app.post("/api/v1/picks/{selection_id}/cancel")
    def cancel_pick(selection_id: uuid.UUID, session: Db, user: CurrentUser):
        """Take a pick back before its market locks: the whole stake returns (D-038)."""
        season = season_of(session)
        wallet_of(session, season, user)
        try:
            sel = cancel_selection(session, season_id=season.id, user_id=user.id, selection_id=selection_id,
                                   now=db_now(session))
        except PlacementError as e:
            raise ApiError(404 if e.code == "UNKNOWN_PICK" else 409, e.code, e.message) from e
        wallet = wallet_of(session, season, user)
        return {"pick": views.selection_rows(session, [sel])[0], "wallet": views.wallet_summary(session, wallet)}

    @app.get("/api/v1/me/picks")
    def my_picks(user: CurrentUser, session: Db, state: str | None = Query(None, pattern="^(open|settled)$")):
        return {"picks": views.my_selections(session, user, state)}

    @app.get("/api/v1/me/wallet")
    def my_wallet(user: CurrentUser, session: Db):
        wallet = wallet_of(session, season_of(session), user)
        return {**views.wallet_summary(session, wallet), "ledger": views.ledger_view(session, wallet)}

    # ------------------------------------------------------------ league

    @app.get("/api/v1/league/standings")
    def league_standings(user: CurrentUser, session: Db):
        return {"standings": views.standings(session, season_of(session))}

    @app.get("/api/v1/league/activity")
    def league_activity(user: CurrentUser, session: Db):
        return {"activity": views.activity(session, season_of(session))}

    @app.get("/api/v1/events/{event_id}/league")
    def event_league(event_id: uuid.UUID, user: CurrentUser, session: Db):
        """Friends' picks on this match, each shown once its market has locked; before that only a count."""
        season = season_of(session)
        return {"picks": views.activity(session, season, limit=200, fixture_id=event_id, exclude_user_id=user.id),
                "pending": views.friends_pending(session, season, event_id, user.id),
                "table": views.match_table(session, season, event_id, user.id),
                "reactions": views.reactions_view(session, event_id)}

    class ReactionBody(BaseModel):
        phrase: str = Field(pattern=f"^({'|'.join(views.PHRASES)})$")

    @app.post("/api/v1/picks/{selection_id}/reactions")
    def react(selection_id: uuid.UUID, body: ReactionBody, session: Db, user: CurrentUser):
        """A fixed phrase on a friend's pick, once its market has locked (A-010, D-034). Once per phrase."""
        season = season_of(session)
        wallet_of(session, season, user)
        sel = session.get(Selection, selection_id)
        market = session.get(Market, sel.market_id) if sel else None
        if sel is None or market is None or market.season_id != season.id:
            raise ApiError(404, "NOT_FOUND", "That pick doesn't exist.")
        if sel.user_id == user.id:
            raise ApiError(409, "OWN_PICK", "React to a friend's pick, not your own.")
        if market.state in ("OPEN", "SUSPENDED"):
            raise ApiError(409, "NOT_LOCKED", "Picks are private until their market locks.")
        exists = session.execute(select(Reaction.id).where(
            Reaction.selection_id == sel.id, Reaction.from_user_id == user.id, Reaction.phrase == body.phrase)).first()
        if exists is None:
            session.add(Reaction(season_id=season.id, fixture_id=market.fixture_id, selection_id=sel.id,
                                 from_user_id=user.id, to_user_id=sel.user_id, phrase=body.phrase))
            session.add(OutboxEvent(type="reaction.created", entity_id=str(sel.id), user_id=sel.user_id, payload={
                "from": user.display_name, "text": views.PHRASES[body.phrase],
                "pick": sel.rules_snapshot.get("outcome"), "market": sel.rules_snapshot.get("title"),
                "event_id": str(market.fixture_id) if market.fixture_id else None}))
            session.flush()
        return {"reactions": views.reactions_view(session, market.fixture_id) if market.fixture_id else []}

    # ------------------------------------------------------------ stream

    @app.get("/api/v1/stream")
    async def stream(request: Request, last_event_id: Annotated[str | None, Header(alias="last-event-id")] = None):
        # No Db dependency here: FastAPI holds a dependency's session open until the response ends, which for a
        # stream is hours of an idle transaction pinning a pooled connection. Each read gets its own session.
        with factory() as session:
            user = auth.user_for_token(session, request.cookies.get(COOKIE), db_now(session))
            if user is None:
                raise ApiError(401, "UNAUTHENTICATED", "Sign in with your invite link.")
            user_id = user.id
            cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else (
                session.execute(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(1)).scalar() or 0)

        async def gen():
            nonlocal cursor
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                with factory() as session:
                    rows = session.execute(select(OutboxEvent).where(OutboxEvent.id > cursor)
                                           .order_by(OutboxEvent.id).limit(200)).scalars().all()
                for ev in rows:
                    cursor = ev.id
                    if ev.user_id is not None and ev.user_id != user_id:
                        continue
                    # Payloads are user-scoped or public by construction; the client uses them for toasts only.
                    data = json.dumps({"type": ev.type, "entity_id": ev.entity_id, "payload": ev.payload or {}})
                    yield f"id: {ev.id}\nevent: {ev.type}\ndata: {data}\n\n"
                yield ": keepalive\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------ admin (emergency controls only, D-008)

    @app.get("/api/v1/admin/health")
    def admin_health(session: Db, _admin: Annotated[User, Depends(admin_user)]):
        syncs = [{"job": r.job, "last_ok_at": r.last_ok_at and r.last_ok_at.isoformat(),
                  "last_error_at": r.last_error_at and r.last_error_at.isoformat(), "last_error": r.last_error}
                 for r in session.execute(select(ProviderSync).order_by(ProviderSync.job)).scalars()]
        held = session.execute(select(Market).where(Market.state == "HOLD")).scalars().all()
        return {"jobs": syncs, "reconciliation_mismatches": ledger.reconcile(session),
                "held_markets": [{"id": str(m.id), "title": m.title, "reason": m.state_reason} for m in held]}

    class AdminActionBody(BaseModel):
        reason: str = Field(min_length=3, max_length=500)

    @app.post("/api/v1/admin/markets/{market_id}/suspend")
    def suspend_market(market_id: uuid.UUID, body: AdminActionBody, session: Db,
                       admin: Annotated[User, Depends(admin_user)]):
        market = session.execute(select(Market).where(Market.id == market_id).with_for_update()).scalar_one()
        if market.state != "OPEN":
            raise ApiError(409, "INVALID_STATE", f"Market is {market.state}.")
        market.state, market.state_reason = "SUSPENDED", body.reason
        session.add(AuditEvent(actor=admin.handle, action="market.suspended", entity_type="market",
                               entity_id=str(market.id), data={"reason": body.reason}))
        return {"ok": True}

    @app.post("/api/v1/admin/markets/{market_id}/resume")
    def resume_market(market_id: uuid.UUID, body: AdminActionBody, session: Db,
                      admin: Annotated[User, Depends(admin_user)]):
        market = session.execute(select(Market).where(Market.id == market_id).with_for_update()).scalar_one()
        if market.state != "SUSPENDED" or market.close_at <= db_now(session):
            raise ApiError(409, "INVALID_STATE", "Only suspended markets that have not reached lock can resume.")
        market.state, market.state_reason = "OPEN", None
        session.add(AuditEvent(actor=admin.handle, action="market.resumed", entity_type="market",
                               entity_id=str(market.id), data={"reason": body.reason}))
        return {"ok": True}

    @app.get("/api/v1/admin/audit")
    def admin_audit(session: Db, _admin: Annotated[User, Depends(admin_user)]):
        rows = session.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(200)).scalars()
        return {"audit": [{"actor": a.actor, "action": a.action, "entity": f"{a.entity_type}:{a.entity_id}",
                           "data": a.data, "at": a.created_at.isoformat()} for a in rows]}

    @app.get("/api/v1/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/v1/health/ready")
    def ready():
        # A reachable process is not sufficient: the migrated schema and season
        # must be usable. Do not return SQL/connection details to anonymous clients.
        try:
            with factory() as session:
                session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                season_of(session)
        except (SQLAlchemyError, ApiError):
            return JSONResponse(status_code=503, content={"ok": False})
        return {"ok": True}

    return app


app = create_app()
