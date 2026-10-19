"""Exact RC arithmetic. Balances are integers; odds are Decimals; never floats."""

from decimal import ROUND_HALF_UP, Decimal

ODDS_QUANT = Decimal("0.01")


def to_odds(value: Decimal | str) -> Decimal:
    odds = Decimal(value).quantize(ODDS_QUANT, rounding=ROUND_HALF_UP)
    if odds <= 1:
        raise ValueError(f"decimal odds must exceed 1.00, got {odds}")
    return odds


def winning_return(stake_rc: int, odds: Decimal) -> int:
    """Total credited for a winning selection (stake included), ROUND_HALF_UP to whole RC."""
    if stake_rc <= 0:
        raise ValueError("stake must be positive")
    return int((Decimal(stake_rc) * odds).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def settlement_return(stake_rc: int, odds: Decimal, result: str) -> int:
    if result == "WON":
        return winning_return(stake_rc, odds)
    if result == "VOID":
        return stake_rc
    if result == "LOST":
        return 0
    raise ValueError(f"unknown result {result}")
