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
