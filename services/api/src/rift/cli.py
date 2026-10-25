"""Operational entry points: `rift api`, `rift worker`, `rift cycle`, `rift invite`, `rift sign-in-code`,
`rift backtest`."""

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="rift")
    sub = parser.add_subparsers(dest="cmd", required=True)
    api = sub.add_parser("api", help="serve the HTTP API")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("worker", help="run the scheduler loop")
    worker.add_argument("--interval", type=int, default=60)
    sub.add_parser("cycle", help="run one worker cycle and exit")
    invite = sub.add_parser("invite", help="create an invite code")
    invite.add_argument("--admin", action="store_true")
    code = sub.add_parser("sign-in-code", help="create a 24-hour sign-in code for a member with no signed-in device")
    code.add_argument("--user", required=True, help="the member's name or handle")
    link = sub.add_parser("sign-in-link", help="issue or revoke a permanent, reusable private login link")
    link.add_argument("--user", required=True, help="the member's name or handle")
    link.add_argument("--revoke", action="store_true", help="revoke without issuing a replacement")
    link.add_argument("--origin", default="https://rift.mustache.network", help="public site origin")
    sub.add_parser("backtest", help="print the team-strength model backtest")
    rm = sub.add_parser("remove-pick", help="remove a member's open pick (a misclick) with the whole stake back; "
                        "lists matches without --confirm")
    rm.add_argument("--user", required=True, help="the member's name or handle")
    rm.add_argument("--fixture", required=True, help="the match's provider id")
    rm.add_argument("--game", type=int, help="game number, for game markets")
    rm.add_argument("--kind", required=True, help="market kind, e.g. soul_team")
    rm.add_argument("--reason", required=True)
    rm.add_argument("--by", default="admin", help="who made the call, for the audit log")
    rm.add_argument("--confirm", action="store_true", help="remove them (otherwise only list)")
    fix = sub.add_parser("correct-result", help="set a game market's result by hand (both blind and after-draft "
                         "copies); the worker re-settles it on its next pass")
    fix.add_argument("--fixture", required=True, help="the match's provider id")
    fix.add_argument("--game", type=int, required=True)
    fix.add_argument("--kind", required=True, help="market kind, e.g. baron_before")
    fix.add_argument("--codes", help="winning outcome codes or team codes, comma-separated (e.g. YES, BLG)")
    fix.add_argument("--void", action="store_true", help="void instead: every stake comes back")
    fix.add_argument("--reason", required=True)
    fix.add_argument("--by", default="admin", help="who made the call, for the audit log")
    args = parser.parse_args()

    if args.cmd == "api":
        import uvicorn

        # Invite URLs and session-bearing query strings must not enter access logs.
        uvicorn.run("rift.api.app:app", host=args.host, port=args.port, proxy_headers=True,
                    access_log=False)
    elif args.cmd == "worker":
        from rift.worker import run_forever

        run_forever(args.interval)
    elif args.cmd == "cycle":
        from rift.adapters.leaguepedia import make_source
        from rift.adapters.lolesports import LolesportsClient
        from rift.config import get_settings
        from rift.db import session_factory
        from rift.worker import Worker

        logging.basicConfig(level=logging.INFO)
        settings = get_settings()
        Worker(session_factory(), settings, LolesportsClient(settings), make_source(settings)).cycle()
    elif args.cmd == "correct-result":
        from sqlalchemy import select

        from rift.db import db_now, transaction
        from rift.models import AuditEvent, Fixture, Market, Outcome, Team

        if not args.void and not args.codes:
            parser.error("give --codes or --void")
        with transaction() as db:
            fixture = db.execute(select(Fixture).where(Fixture.provider_id == args.fixture)).scalar_one()
            rows = [m for m in db.execute(select(Market).where(Market.fixture_id == fixture.id,
                                                               Market.kind == args.kind)).scalars()
                    if m.params.get("game_index") == args.game]
            if not rows:
                parser.error("no such market")
            # A team code (e.g. BLG) stands for that team's side in this fixture, so nobody has to know A from B.
            side = {}
            for code, team_id in (("A", fixture.team_a_id), ("B", fixture.team_b_id)):
                team = db.get(Team, team_id) if team_id else None
                if team is not None and team.code:
                    side[team.code.upper()] = code
            wanted = [side.get(c.strip().upper(), c.strip()) for c in (args.codes or "").split(",") if c.strip()]
            correction = {"codes": [] if args.void else wanted, "void": args.void,
                          "reason": args.reason, "by": args.by, "at": db_now(db).isoformat()}
            for m in rows:
                if m.state == "OPEN":  # still taking bets: a known result can't sit on it
                    print(m.template_key, "OPEN, skipped")
                    continue
                labels = dict(db.execute(select(Outcome.code, Outcome.label).where(Outcome.market_id == m.id)).all())
                if not args.void and not set(correction["codes"]) <= set(labels):
                    parser.error(f"{m.template_key} has no outcome {correction['codes']}")
                m.params = {**m.params, "correction": correction}
                db.add(AuditEvent(actor=args.by, action="market.corrected", entity_type="market",
                                  entity_id=str(m.id), data=correction))
                print(m.template_key, m.state, "->", "VOID" if args.void else
                      ", ".join(f"{c} ({labels[c]})" for c in correction["codes"]))
    elif args.cmd == "remove-pick":
        from sqlalchemy import func, or_, select

        from rift.db import db_now, transaction
        from rift.models import Fixture, Market, Selection, User
        from rift.placement import admin_remove

        with transaction() as db:
            named = or_(func.lower(User.handle) == args.user.lower(), func.lower(User.display_name) == args.user.lower())
            user = db.execute(select(User).where(named)).scalar_one_or_none()
            if user is None:
                parser.error(f"No member named {args.user!r}")
            fixture = db.execute(select(Fixture).where(Fixture.provider_id == args.fixture)).scalar_one()
            picks = [(sel, m) for sel, m in db.execute(
                select(Selection, Market).join(Market, Market.id == Selection.market_id)
                .where(Selection.user_id == user.id, Selection.status == "OPEN", Market.fixture_id == fixture.id,
                       Market.kind == args.kind)).all()
                     if args.game is None or m.params.get("game_index") == args.game]
            if not picks:
                parser.error(f"{user.display_name} has no open {args.kind} pick on that match")
            for sel, m in picks:
                line = f"{sel.id}  {m.title}: {sel.rules_snapshot.get('outcome')} {sel.stake_rc:,} RC @ {sel.odds:.2f}"
                if args.confirm:
                    admin_remove(db, sel.id, reason=args.reason, by=args.by, now=db_now(db))
                    line += f"  -> removed, {sel.stake_rc:,} RC back"
                print(line)
            if not args.confirm:
                print(f"{len(picks)} pick(s) for {user.display_name}. Re-run with --confirm to remove them.")
    elif args.cmd == "invite":
        from rift.auth import create_invite
        from rift.db import transaction

        with transaction() as db:
            code = create_invite(db, "ADMIN" if args.admin else "PLAYER")
        print(code)
    elif args.cmd in ("sign-in-code", "sign-in-link"):
        from sqlalchemy import func, or_, select

        from rift.auth import ADMIN_CODE_TTL, create_sign_in_code, create_sign_in_link, revoke_sign_in_link
        from rift.db import db_now, transaction
        from rift.models import User

        with transaction() as db:
            named = or_(func.lower(User.handle) == args.user.lower(),
                        func.lower(User.display_name) == args.user.lower())
            user = db.execute(select(User).where(named)).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"No member named {args.user!r}")
            name = user.display_name
            if args.cmd == "sign-in-code":
                code, expires_at = create_sign_in_code(db, user, db_now(db), ADMIN_CODE_TTL, actor="cli")
                output = f"{code}  for {name}, valid until {expires_at:%Y-%m-%d %H:%M %Z}"
            elif args.revoke:
                revoke_sign_in_link(db, user)
                output = f"Permanent sign-in link revoked for {name}."
            else:
                token = create_sign_in_link(db, user)
                output = f"{args.origin.rstrip('/')}/signin#token={token}"
        print(output)
    elif args.cmd == "backtest":
        from rift import ratings
        from rift.db import session_factory

        with session_factory()() as db:
            bt = ratings.backtest(db)
        print(f"series={bt.series} log_loss={bt.log_loss:.4f} baseline={bt.baseline_log_loss:.4f} "
              f"brier={bt.brier:.4f} accuracy={bt.accuracy:.3f} beats_baseline={bt.beats_baseline}")


if __name__ == "__main__":
    main()
