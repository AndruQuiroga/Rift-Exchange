"""Deterministic grading and replay-safe settlement (docs/spec/02, 03 §Settlement precedence).

A grade is computed from stored canonical facts only. Applying the same grade twice is a no-op; a
different grade appends a new result revision, reverses prior returns and pays the corrected ones.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rift import ledger, props
from rift.champions import champion_key
from rift.domain.money import settlement_return
from rift.markets import SWISS_RECORDS, swiss_side
from rift.models import (
    Fixture,
    Game,
    Market,
    MarketResult,
    OutboxEvent,
    Outcome,
    Selection,
    Settlement,
    Team,
    Wallet,
)


@dataclass
class Grade:
    status: str  # RESULT | VOID | HOLD | PENDING
    winning_codes: list[str] = field(default_factory=list)
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    partial_codes: list[str] = field(default_factory=list)  # pay the market's consolation share


PENDING = Grade("PENDING", reason="Event not finished")


def _games(session: Session, fixture: Fixture) -> list[Game]:
    return list(session.execute(
        select(Game).where(Game.fixture_id == fixture.id).order_by(Game.game_index)
    ).scalars())


def _side_code(fixture: Fixture, team_id) -> str | None:
    if team_id is None:
        return None
    if team_id == fixture.team_a_id:
        return "A"
    if team_id == fixture.team_b_id:
        return "B"
    return None


def grade_market(session: Session, market: Market) -> Grade:
    if market.fixture_id is None:
        return grade_tournament_market(session, market)
    fixture = session.get(Fixture, market.fixture_id)
    if fixture.status == "CANCELED":
        return Grade("VOID", reason="Series cancelled")
    if fixture.status == "POSTPONED":
        return Grade("HOLD", reason="Series postponed")
    ev = {"fixture": fixture.provider_id, "score": f"{fixture.team_a_wins}-{fixture.team_b_wins}"}
    kind = market.kind

    if kind in ("series_winner", "series_score", "total_games"):
        if fixture.status != "COMPLETED":
            return PENDING
        need = fixture.best_of // 2 + 1
        a, b = fixture.team_a_wins, fixture.team_b_wins
        if max(a, b) != need or min(a, b) >= need:
            return Grade("HOLD", reason=f"Final score {a}-{b} is not a valid Bo{fixture.best_of} result",
                         evidence=ev)
        if kind == "series_winner":
            return Grade("RESULT", ["A" if a > b else "B"], "Series winner confirmed", ev)
        if kind == "series_score":
            return Grade("RESULT", [f"{a}-{b}"], "Series score confirmed", ev)
        return Grade("RESULT", [str(a + b)], "Games played confirmed", ev)

    if kind == "game_winner":
        idx = market.params["game_index"]
        game = next((g for g in _games(session, fixture) if g.game_index == idx), None)
        if game is None or game.state in ("unstarted", "inProgress"):
            if fixture.status == "COMPLETED":
                return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
            return PENDING
        if game.state == "unneeded":
            return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
        code = _side_code(fixture, game.winner_team_id)
        if code is None:
            return Grade("HOLD", reason=f"Awaiting verified Game {idx} winner", evidence=ev)
        return Grade("RESULT", [code], f"Game {idx} winner confirmed",
                     {**ev, "game": game.provider_id, "winner_evidence": game.winner_evidence})

    if kind in props.KINDS:
        idx = market.params["game_index"]
        return props.grade(market, fixture, next((g for g in _games(session, fixture) if g.game_index == idx), None))

    if kind == "champion_picked":
        champ = market.params["champion"]
        played = [g for g in _games(session, fixture) if g.state == "completed"]
        if market.scope == "GAME":
            idx = market.params["game_index"]
            game = next((g for g in played if g.game_index == idx), None)
            if game is None:
                if fixture.status == "COMPLETED":
                    return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
                return PENDING
            scoped = [game]
        else:
            if fixture.status != "COMPLETED":
                return PENDING
            scoped = played
        if not scoped or any(not g.stats_complete for g in scoped):
            return Grade("HOLD", reason="Awaiting verified draft data", evidence=ev)
        side, role = market.params.get("side"), market.params.get("role")
        team_id = str(fixture.team_a_id if side == "A" else fixture.team_b_id) if side else None
        picks = {champion_key(p["champion"]) for g in scoped for p in g.stats["players"]
                 if (team_id is None or p.get("team_id") == team_id) and (role is None or p.get("role") == role)}
        champ = champion_key(champ)
        if team_id is not None and not any(p.get("team_id") == team_id for g in scoped for p in g.stats["players"]):
            return Grade("HOLD", reason="Awaiting verified team draft data", evidence=ev)
        if role is not None and any(not p.get("role") for g in scoped for p in g.stats["players"]
                                    if p.get("team_id") == team_id):
            return Grade("HOLD", reason="Awaiting verified player roles", evidence=ev)
        return Grade("RESULT", ["YES" if champ in picks else "NO"], "Draft confirmed",
                     {**ev, "games": [g.provider_id for g in scoped]})

    if kind in ("champion_banned", "champion_first_pick"):
        # Bans and pick order come from Leaguepedia (rift.ingest.sync_drafts); HOLD until stored. The worker
        # voids anything still held after the deadline, which covers Leaguepedia never filling the game in.
        idx = market.params["game_index"]
        game = next((g for g in _games(session, fixture) if g.game_index == idx), None)
        if game is None or game.state != "completed":
            if fixture.status == "COMPLETED" or (game is not None and game.state == "unneeded"):
                return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
            return PENDING
        draft = game.bans or {}
        champ = champion_key(market.params["champion"])
        ev = {**ev, "game": game.provider_id, "source": draft.get("source")}
        if kind == "champion_banned":
            if "blue" not in draft or "red" not in draft:
                return Grade("HOLD", reason=f"Awaiting verified Game {idx} bans", evidence=ev)
            hit = champ in {champion_key(c) for c in draft["blue"] + draft["red"]}
            return Grade("RESULT", ["YES" if hit else "NO"], "Bans confirmed",
                         {**ev, "bans": {"blue": draft["blue"], "red": draft["red"]}})
        if not draft.get("first_pick"):
            return Grade("HOLD", reason=f"Awaiting verified Game {idx} pick order", evidence=ev)
        return Grade("RESULT", ["YES" if champion_key(draft["first_pick"]) == champ else "NO"],
                     "Pick order confirmed", {**ev, "first_pick": draft["first_pick"]})

    if kind == "most_kills_game":
        idx = market.params["game_index"]
        game = next((g for g in _games(session, fixture) if g.game_index == idx), None)
        if game is None or game.state != "completed":
            if fixture.status == "COMPLETED" or (game is not None and game.state == "unneeded"):
                return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
            return PENDING
        if not game.stats_complete:
            return Grade("HOLD", reason=f"Awaiting verified Game {idx} player stats", evidence=ev)
        players = game.stats["players"]
        top = max(p["kills"] for p in players)
        leaders = [p["player_id"] for p in players if p["kills"] == top]
        if len(leaders) > 1:
            return Grade("VOID", reason="Tie for most kills (void rule)", evidence={**ev, "kills": top})
        offered = {o.code for o in _market_outcomes(session, market)}
        if leaders[0] not in offered:
            return Grade("VOID", reason="Kill leader was not an offered player", evidence=ev)
        return Grade("RESULT", leaders, "Player stats confirmed", {**ev, "kills": top})

    if kind == "total_kills_game":
        idx = market.params["game_index"]
        line = float(market.params["line"])
        game = next((g for g in _games(session, fixture) if g.game_index == idx), None)
        if game is None or game.state != "completed":
            if fixture.status == "COMPLETED" or (game is not None and game.state == "unneeded"):
                return Grade("VOID", reason=f"Game {idx} was not played", evidence=ev)
            return PENDING
        if not game.stats_complete:
            return Grade("HOLD", reason=f"Awaiting verified Game {idx} stats", evidence=ev)
        total = sum(p["kills"] for p in game.stats["players"])
        return Grade("RESULT", ["OVER" if total > line else "UNDER"], "Kill totals confirmed",
                     {**ev, "total_kills": total})

    return Grade("HOLD", reason=f"No grader for {kind}")


def grade_tournament_market(session: Session, market: Market) -> Grade:
    fixtures = list(session.execute(select(Fixture).where(Fixture.season_id == market.season_id)).scalars())
    if market.kind == "tournament_winner":
        final = [f for f in fixtures if f.stage == "Finals"]
        if not final or final[0].status != "COMPLETED" or final[0].winner_team_id is None:
            return PENDING
        team = session.get(Team, final[0].winner_team_id)
        return Grade("RESULT", [team.provider_id], "Final completed", {"fixture": final[0].provider_id})
    if market.kind in ("swiss_advance", "swiss_record"):
        team = session.execute(select(Team).where(Team.provider_id == market.params["team"])).scalar_one()
        wins = losses = 0
        swiss = [f for f in fixtures if f.stage == "Swiss" and team.id in (f.team_a_id, f.team_b_id)]
        for f in swiss:
            if f.status != "COMPLETED" or f.winner_team_id is None:
                continue
            if f.winner_team_id == team.id:
                wins += 1
            else:
                losses += 1
        if market.kind == "swiss_record":
            if wins < 3 and losses < 3:
                return PENDING
            record = f"{wins}-{losses}"
            if record not in SWISS_RECORDS:
                return Grade("HOLD", reason=f"{team.code} Swiss record {record} is not a valid finish")
            partial = [r for r in SWISS_RECORDS if r != record and swiss_side(r) == swiss_side(record)]
            return Grade("RESULT", [record], f"{team.code} finished Swiss {record.replace('-', chr(8211))}",
                         {"record": record, "partial_codes": partial}, partial_codes=partial)
        if wins >= 3:
            return Grade("RESULT", ["YES"], f"{team.code} reached 3 Swiss wins", {"record": f"{wins}-{losses}"})
        if losses >= 3:
            return Grade("RESULT", ["NO"], f"{team.code} reached 3 Swiss losses", {"record": f"{wins}-{losses}"})
        return PENDING
    return Grade("HOLD", reason=f"No grader for {market.kind}")


def _market_outcomes(session: Session, market: Market) -> list[Outcome]:
    return list(session.execute(select(Outcome).where(Outcome.market_id == market.id)).scalars())


def apply_grade(session: Session, market_id, grade: Grade, now: datetime) -> bool:
    """Settle or re-settle a market. Returns True if anything changed."""
    market = session.execute(select(Market).where(Market.id == market_id).with_for_update()).scalar_one()
    if grade.status == "PENDING":
        return False
    if grade.status == "HOLD":
        if market.state in ("SETTLED", "VOID"):
            return False  # never un-settle on missing data; corrections need a definitive new grade
        changed = market.state != "HOLD" or market.state_reason != grade.reason
        market.state, market.state_reason = "HOLD", grade.reason
        return changed

    void = grade.status == "VOID"
    winning = sorted(grade.winning_codes) if not void else []
    partial = set(grade.partial_codes) if not void else set()
    last = session.execute(
        select(MarketResult).where(MarketResult.market_id == market.id)
        .order_by(MarketResult.revision.desc()).limit(1)
    ).scalar_one_or_none()
    if last is not None and last.void == void and sorted(last.winning_codes) == winning:
        return False

    revision = market.result_revision + 1
    session.add(MarketResult(market_id=market.id, revision=revision, void=void, winning_codes=winning,
                             reason=grade.reason, evidence=grade.evidence))
    outcome_codes = {o.id: o.code for o in _market_outcomes(session, market)}
    selections = list(session.execute(
        select(Selection).where(Selection.market_id == market.id).order_by(Selection.id).with_for_update()
    ).scalars())
    wallet_by_user = {
        w.user_id: w for w in session.execute(
            select(Wallet).where(Wallet.season_id == market.season_id,
                                 Wallet.user_id.in_({s.user_id for s in selections}))
        ).scalars()
    }
    locked = ledger.lock_wallets(session, {w.id for w in wallet_by_user.values()}) if selections else {}

    for sel in selections:
        code = outcome_codes[sel.outcome_id]
        result = "VOID" if void else "WON" if code in winning else "PARTIAL" if code in partial else "LOST"
        new_return = settlement_return(sel.stake_rc, sel.odds, result,
                                       consolation=sel.rules_snapshot.get("params", {}).get("consolation"))
        wallet = locked[wallet_by_user[sel.user_id].id]
        if sel.settled_revision > 0 and sel.status == result:
            pass  # unchanged outcome for this selection; record the revision without moving credits
        else:
            if sel.settled_revision > 0 and sel.return_rc > 0:
                ledger.reverse(session, wallet, amount_rc=sel.return_rc, key=f"reverse:{sel.id}:{revision}",
                               ref_type="selection", ref_id=str(sel.id),
                               memo=f"Correction: reversed {sel.status.lower()} return")
            if new_return > 0:
                memo = sel.rules_snapshot.get("title", "")
                ledger.credit(session, wallet, kind="VOID_REFUND" if result == "VOID" else "PAYOUT",
                              amount_rc=new_return, key=f"settle:{sel.id}:{revision}", ref_type="selection",
                              ref_id=str(sel.id), memo=f"{memo} (right side)" if result == "PARTIAL" else memo)
        session.add(Settlement(selection_id=sel.id, revision=revision, result=result, return_rc=new_return))
        sel.status, sel.return_rc, sel.settled_revision, sel.settled_at = result, new_return, revision, now
        session.add(OutboxEvent(type="selection.settled", entity_id=str(sel.id), user_id=sel.user_id,
                                payload={"result": result, "revision": revision}))

    market.result_revision = revision
    market.state = "VOID" if void else "SETTLED"
    market.state_reason = grade.reason
    session.add(OutboxEvent(type="leaderboard.changed", entity_id=str(market.id), payload={}))
    session.flush()
    return True
