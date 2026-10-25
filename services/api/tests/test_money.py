import threading
from datetime import date, timedelta

import pytest
from conftest import T0, outcome_id
from sqlalchemy import func, select

from rift import grants, ledger
from rift.models import Fixture, LedgerEntry, Market, Outcome, Season, Selection, Wallet
from rift.placement import PlacementError, QuoteItem, accept_ticket, create_quote
from rift.settlement import Grade, apply_grade, grade_market


def join(factory, ids, user, now=T0):
    with factory() as s, s.begin():
        season = s.get(Season, ids["season"])
        return grants.join_season(s, season, ids[user], now).id


def balance(factory, ids, user):
    with factory() as s:
        w = s.execute(select(Wallet).where(Wallet.user_id == ids[user])).scalar_one()
        return w.available_rc, w.recovery_due_rc


def place(factory, ids, user, picks, key, now=T0):
    with factory() as s, s.begin():
        q = create_quote(s, season_id=ids["season"], user_id=ids[user],
                         items=[QuoteItem(o, stake) for o, stake in picks], now=now, ttl_seconds=20)
    with factory() as s, s.begin():
        ticket, created = accept_ticket(
            s, season_id=ids["season"], user_id=ids[user], quote_id=q["quote_id"],
            confirm_odds_versions={i["outcome_id"]: i["odds_version"] for i in q["items"]},
            idempotency_key=key, now=now)
        return ticket.id, created


def test_join_grants_opening_plus_match_day_once(factory, world):
    join(factory, world, "alice")
    assert balance(factory, world, "alice") == (2000, 0)  # opening + Oct 23 match day
    join(factory, world, "alice")
    with factory() as s, s.begin():
        assert grants.run_match_day_grants(s, s.get(Season, world["season"]), T0) == 0
    assert balance(factory, world, "alice") == (2000, 0)


def test_match_day_grants_follow_venue_date_and_backfill_late_joiners(factory, world):
    with factory() as s, s.begin():
        f = s.get(Fixture, world["fixture"])
        s.add(Fixture(season_id=f.season_id, provider_id="fx-2", stage="Swiss", best_of=1,
                      scheduled_at=T0 + timedelta(days=1), local_date=date(2026, 10, 24)))
    join(factory, world, "alice")
    # 23:30 UTC on Oct 24 is still Oct 24 in Chicago; 05:30 UTC on Oct 25 is Oct 24 local too.
    with factory() as s, s.begin():
        season = s.get(Season, world["season"])
        for _ in range(5):
            grants.run_match_day_grants(s, season, T0 + timedelta(days=1, hours=14, minutes=30))
    assert balance(factory, world, "alice") == (3000, 0)
    join(factory, world, "bob", now=T0 + timedelta(days=2))
    assert balance(factory, world, "bob") == (3000, 0)  # late joiner gets identical history


def test_place_and_settle_win_then_replay_is_noop(factory, world):
    join(factory, world, "alice")
    atlas = outcome_id(factory, world["market"], "A")
    place(factory, world, "alice", [(atlas, 400)], "k1")
    assert balance(factory, world, "alice") == (1600, 0)
    grade = Grade("RESULT", ["A"], "test")
    for _ in range(3):
        with factory() as s, s.begin():
            apply_grade(s, world["market"], grade, T0)
    assert balance(factory, world, "alice") == (1600 + 648, 0)
    with factory() as s:
        assert ledger.reconcile(s) == []


def test_idempotent_ticket_retry_debits_once(factory, world):
    join(factory, world, "alice")
    atlas = outcome_id(factory, world["market"], "A")
    with factory() as s, s.begin():
        q = create_quote(s, season_id=world["season"], user_id=world["alice"], items=[QuoteItem(atlas, 100)],
                         now=T0, ttl_seconds=20)
    results = []
    for _ in range(3):
        with factory() as s, s.begin():
            t, created = accept_ticket(s, season_id=world["season"], user_id=world["alice"],
                                       quote_id=q["quote_id"], confirm_odds_versions={str(atlas): 1},
                                       idempotency_key="same", now=T0)
            results.append((t.id, created))
    assert results[0][1] is True and not results[1][1] and not results[2][1]
    assert len({r[0] for r in results}) == 1
    assert balance(factory, world, "alice") == (1900, 0)


def test_concurrent_all_in_cannot_overdraw(factory, world):
    join(factory, world, "alice")
    atlas = outcome_id(factory, world["market"], "A")
    nova = outcome_id(factory, world["market"], "B")
    quotes = []
    for o in (atlas, nova):
        with factory() as s, s.begin():
            quotes.append(create_quote(s, season_id=world["season"], user_id=world["alice"],
                                       items=[QuoteItem(o, 2000)], now=T0, ttl_seconds=20))
    outcomes, barrier = [], threading.Barrier(2)

    def go(q, key):
        barrier.wait()
        try:
            with factory() as s, s.begin():
                accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=q["quote_id"],
                              confirm_odds_versions={i["outcome_id"]: 1 for i in q["items"]},
                              idempotency_key=key, now=T0)
            outcomes.append("ok")
        except PlacementError as e:
            outcomes.append(e.code)

    threads = [threading.Thread(target=go, args=(q, f"k{i}")) for i, q in enumerate(quotes)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes) == ["INSUFFICIENT_CREDITS", "ok"]
    assert balance(factory, world, "alice") == (0, 0)


def test_odds_change_requires_reconfirmation(factory, world):
    join(factory, world, "alice")
    atlas = outcome_id(factory, world["market"], "A")
    with factory() as s, s.begin():
        q = create_quote(s, season_id=world["season"], user_id=world["alice"], items=[QuoteItem(atlas, 100)],
                         now=T0, ttl_seconds=20)
    with factory() as s, s.begin():
        o = s.get(Outcome, atlas)
        o.odds_version, o.odds = 2, o.odds + 1
    with pytest.raises(PlacementError) as e, factory() as s, s.begin():
        accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=q["quote_id"],
                      confirm_odds_versions={str(atlas): 1}, idempotency_key="k", now=T0)
    assert e.value.code == "ODDS_CHANGED"
    assert balance(factory, world, "alice") == (2000, 0)


def test_closed_market_and_expired_quote_rejected(factory, world):
    join(factory, world, "alice")
    atlas = outcome_id(factory, world["market"], "A")
    with factory() as s, s.begin():
        q = create_quote(s, season_id=world["season"], user_id=world["alice"], items=[QuoteItem(atlas, 100)],
                         now=T0, ttl_seconds=20)
    for now, code in [(T0 + timedelta(seconds=30), "QUOTE_EXPIRED"), (T0 + timedelta(hours=3), "MARKET_CLOSED")]:
        with pytest.raises(PlacementError) as e, factory() as s, s.begin():
            accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=q["quote_id"],
                          confirm_odds_versions={str(atlas): 1}, idempotency_key=code, now=now)
        assert e.value.code == code
    with factory() as s:
        assert s.execute(select(func.count()).select_from(Selection)).scalar() == 0


def test_one_outcome_per_market_per_slip(factory, world):
    join(factory, world, "alice")
    a, b = outcome_id(factory, world["market"], "A"), outcome_id(factory, world["market"], "B")
    with pytest.raises(PlacementError) as e, factory() as s, s.begin():
        create_quote(s, season_id=world["season"], user_id=world["alice"],
                     items=[QuoteItem(a, 10), QuoteItem(b, 10)], now=T0, ttl_seconds=20)
    assert e.value.code == "CONFLICTING_PICKS"


def test_correction_reverses_and_recovers_debt_without_negative_balance(factory, world):
    join(factory, world, "alice")
    join(factory, world, "bob")
    atlas = outcome_id(factory, world["market"], "A")
    nova = outcome_id(factory, world["market"], "B")
    place(factory, world, "alice", [(atlas, 2000)], "a")  # alice all-in on Atlas @1.62
    place(factory, world, "bob", [(nova, 1000)], "b")
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("RESULT", ["A"], "first"), T0)
    assert balance(factory, world, "alice") == (3240, 0)
    # Alice spends most of it on another market before the correction lands.
    with factory() as s, s.begin():
        from conftest import make_market
        m2 = make_market(s, s.get(Season, world["season"]), s.get(Fixture, world["fixture"]), "total_games",
                         [("2", "2 games", "1.90"), ("3", "3 games", "2.10")])
        m2_id = m2.id
    place(factory, world, "alice", [(outcome_id(factory, m2_id, "3"), 3000)], "c")
    assert balance(factory, world, "alice") == (240, 0)
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("RESULT", ["B"], "corrected"), T0)
    assert balance(factory, world, "alice") == (0, 3000)  # 3240 reversed: 240 taken, 3000 owed
    assert balance(factory, world, "bob") == (1000 + 2400, 0)
    with factory() as s, s.begin():
        apply_grade(s, m2_id, Grade("RESULT", ["3"], "settle"), T0)  # 3000 @2.10 = 6300
    assert balance(factory, world, "alice") == (3300, 0)  # debt repaid first
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("RESULT", ["A"], "corrected back"), T0)
    assert balance(factory, world, "alice") == (3300 + 3240, 0)
    assert balance(factory, world, "bob") == (1000, 0)
    with factory() as s:
        assert ledger.reconcile(s) == []
        assert s.execute(select(Market.result_revision).where(Market.id == world["market"])).scalar() == 3
        kinds = s.execute(select(LedgerEntry.kind).order_by(LedgerEntry.id)).scalars().all()
        assert kinds.count("REVERSAL") == 2


def test_hold_then_void_refunds_stake(factory, world):
    join(factory, world, "alice")
    place(factory, world, "alice", [(outcome_id(factory, world["market"], "A"), 500)], "k")
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("HOLD", reason="Awaiting data"), T0)
        assert s.get(Market, world["market"]).state == "HOLD"
    with factory() as s, s.begin():
        apply_grade(s, world["market"], Grade("VOID", reason="Series cancelled"), T0)
    assert balance(factory, world, "alice") == (2000, 0)


def test_series_graders(factory, world):
    with factory() as s, s.begin():
        f = s.get(Fixture, world["fixture"])
        f.status, f.team_a_wins, f.team_b_wins, f.winner_team_id = "COMPLETED", 1, 2, world["team_b"]
        season = s.get(Season, world["season"])
        from conftest import make_market
        score = make_market(s, season, f, "series_score", [("2-0", "", "3"), ("2-1", "", "3"), ("1-2", "", "3"),
                                                          ("0-2", "", "3")])
        total = make_market(s, season, f, "total_games", [("2", "", "2"), ("3", "", "2")])
        g = grade_market(s, s.get(Market, world["market"]))
        assert (g.status, g.winning_codes) == ("RESULT", ["B"])
        assert grade_market(s, score).winning_codes == ["1-2"]
        assert grade_market(s, total).winning_codes == ["3"]
        f.team_a_wins = 1
        f.team_b_wins = 1
        assert grade_market(s, score).status == "HOLD"


def test_raising_the_opening_grant_tops_up_existing_members_once(factory, world):
    join(factory, world, "alice")
    assert balance(factory, world, "alice") == (2000, 0)
    with factory() as s, s.begin():
        season = s.get(Season, world["season"])
        season.opening_grant_rc = 5000
        assert grants.run_match_day_grants(s, season, T0) == 1
    with factory() as s, s.begin():
        assert grants.run_match_day_grants(s, s.get(Season, world["season"]), T0) == 0  # once
    assert balance(factory, world, "alice") == (6000, 0)
    join(factory, world, "bob")  # a later joiner gets the new amount straight away, no top-up
    assert balance(factory, world, "bob") == (6000, 0)


def _quote(factory, ids, picks, cap=1000, now=T0):
    with factory() as s, s.begin():
        return create_quote(s, season_id=ids["season"], user_id=ids["alice"], items=[QuoteItem(o, st) for o, st in picks],
                            now=now, ttl_seconds=20, stake_cap_rc=cap)


def test_stake_cap_counts_every_pick_on_the_market(factory, world):
    join(factory, world, "alice")
    a = outcome_id(factory, world["market"], "A")
    b = outcome_id(factory, world["market"], "B")
    with pytest.raises(PlacementError) as e:
        _quote(factory, world, [(a, 1001)])
    assert e.value.code == "STAKE_LIMIT" and e.value.details["max_stake_rc"] == 1000
    q = _quote(factory, world, [(a, 700)])
    with factory() as s, s.begin():
        accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=q["quote_id"],
                      confirm_odds_versions={i["outcome_id"]: i["odds_version"] for i in q["items"]},
                      idempotency_key="cap-1", now=T0, stake_cap_rc=1000)
    with pytest.raises(PlacementError) as e:  # the other side of the same market shares the room
        _quote(factory, world, [(b, 301)])
    assert e.value.details["max_stake_rc"] == 300 and "700 RC staked" in e.value.message
    # A quote made before the room was used is checked again when it is accepted.
    early = _quote(factory, world, [(b, 300)])
    stale = _quote(factory, world, [(b, 300)])
    with factory() as s, s.begin():
        accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=early["quote_id"],
                      confirm_odds_versions={i["outcome_id"]: i["odds_version"] for i in early["items"]},
                      idempotency_key="cap-2", now=T0, stake_cap_rc=1000)
    with pytest.raises(PlacementError) as e, factory() as s, s.begin():
        accept_ticket(s, season_id=world["season"], user_id=world["alice"], quote_id=stale["quote_id"],
                      confirm_odds_versions={i["outcome_id"]: i["odds_version"] for i in stale["items"]},
                      idempotency_key="cap-3", now=T0, stake_cap_rc=1000)
    assert e.value.code == "STAKE_LIMIT"


def test_knockouts_uncap_predictions_that_close_before_the_draft(factory, world):
    from conftest import make_market
    with factory() as s, s.begin():
        fixture = s.get(Fixture, world["fixture"])
        fixture.stage = "Quarterfinals"
        g1 = make_market(s, s.get(Season, world["season"]), fixture, "game_winner", [("A", "Atlas", "1.60"), ("B", "Nova", "2.50")],
                         params={"game_index": 1, "through_draft": True}, scope="GAME")
        g1_id = g1.id
    join(factory, world, "alice")
    assert _quote(factory, world, [(outcome_id(factory, world["market"], "A"), 1500)])["total_stake_rc"] == 1500
    with pytest.raises(PlacementError) as e:  # Game 1 winner stays open through the draft: still capped
        _quote(factory, world, [(outcome_id(factory, g1_id, "A"), 1500)])
    assert e.value.code == "STAKE_LIMIT"


def test_the_league_can_remove_a_misclicked_pick_with_the_whole_stake_back(factory, world):
    """rift remove-pick: even on a locked market, the full stake returns and the pick never settles."""
    from sqlalchemy import update

    from rift.models import AuditEvent, Market, Selection
    from rift.placement import PlacementError, admin_remove

    join(factory, world, "alice")
    before = balance(factory, world, "alice")[0]
    place(factory, world, "alice", [(outcome_id(factory, world["market"], "A"), 300)], "misclick")
    with factory() as s, s.begin():
        s.execute(update(Market).values(state="LOCKED"))
        sel = s.execute(select(Selection)).scalar_one()
        admin_remove(s, sel.id, reason="misclick", by="andru", now=T0)
        assert (sel.status, sel.return_rc) == ("CANCELLED", 300)
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "selection.removed")).scalar_one()
    assert balance(factory, world, "alice")[0] == before
    with factory() as s, s.begin(), pytest.raises(PlacementError):
        admin_remove(s, s.execute(select(Selection)).scalar_one().id, reason="again", by="andru", now=T0)
