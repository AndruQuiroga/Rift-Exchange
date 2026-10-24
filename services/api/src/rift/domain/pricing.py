"""Probability models and price conversion (docs/spec/06_ODDS_ENGINE.md).

Baseline assumption: games within a series are independent with per-game win
probability q. This is labelled as a modelling simplification everywhere it is used.
"""

from decimal import ROUND_HALF_UP, Decimal
from math import comb

from rift.domain.money import ODDS_QUANT


def series_score_distribution(q: float, best_of: int) -> dict[tuple[int, int], float]:
    """P(final score a-b) for team A with per-game win probability q."""
    if best_of not in (1, 3, 5):
        raise ValueError("best_of must be 1, 3 or 5")
    need = best_of // 2 + 1
    dist: dict[tuple[int, int], float] = {}
    for losses in range(need):
        # A wins the deciding game after `losses` losses in the first need-1+losses games.
        dist[(need, losses)] = comb(need - 1 + losses, losses) * q**need * (1 - q) ** losses
        dist[(losses, need)] = comb(need - 1 + losses, losses) * (1 - q) ** need * q**losses
    return dist


def series_win_probability(q: float, best_of: int) -> float:
    return sum(p for (a, b), p in series_score_distribution(q, best_of).items() if a > b)


def total_games_distribution(q: float, best_of: int) -> dict[int, float]:
    out: dict[int, float] = {}
    for (a, b), p in series_score_distribution(q, best_of).items():
        out[a + b] = out.get(a + b, 0.0) + p
    return out


def elo_expectation(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def normalise(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        raise ValueError("probabilities must sum to a positive value")
    return {k: v / total for k, v in probs.items()}


def price(probability: float, *, min_probability: Decimal, max_odds: Decimal) -> Decimal | None:
    """Fair decimal odds (no margin). Returns None when the outcome must not be offered."""
    p = Decimal(str(probability))
    if p <= 0 or p >= 1 or p < min_probability:
        return None
    odds = (Decimal(1) / p).quantize(ODDS_QUANT, rounding=ROUND_HALF_UP)
    if odds > max_odds or odds <= Decimal("1.00"):
        return None
    return odds


# D-040: a market reopened after the draft knows the champions and the live game, so it pays this share of
# the profit a fair price would (2.00 becomes 1.75). Cancelling after the draft starts returns the same share.
AFTER_DRAFT_RATE = Decimal("0.75")


def after_draft(odds: Decimal | None) -> Decimal | None:
    """The after-draft price for fair odds: the same share of the profit, or None when nothing would be left."""
    if odds is None:
        return None
    out = (1 + (odds - 1) * AFTER_DRAFT_RATE).quantize(ODDS_QUANT, rounding=ROUND_HALF_UP)
    return out if out > Decimal("1.00") else None
