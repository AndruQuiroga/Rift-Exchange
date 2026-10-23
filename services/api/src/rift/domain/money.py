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


def partial_return(stake_rc: int, odds: Decimal, consolation: Decimal | str) -> int:
    """Right side, wrong exact outcome: the market's frozen share of the full return, ROUND_HALF_UP."""
    if stake_rc <= 0:
        raise ValueError("stake must be positive")
    share = Decimal(consolation)
    if not Decimal(0) < share < Decimal(1):
        raise ValueError(f"consolation share must be between 0 and 1, got {share}")
    return int((Decimal(stake_rc) * odds * share).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def refund_return(stake_rc: int, share: Decimal | str) -> int:
    """A share of the stake back, ROUND_HALF_UP (a champion call whose champion was banned: half back, D-033)."""
    if stake_rc <= 0:
        raise ValueError("stake must be positive")
    share = Decimal(share)
    if not Decimal(0) < share < Decimal(1):
        raise ValueError(f"refund share must be between 0 and 1, got {share}")
    return int((Decimal(stake_rc) * share).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def settlement_return(stake_rc: int, odds: Decimal, result: str, consolation: Decimal | str | None = None,
                      refund: Decimal | str | None = None) -> int:
    if result == "WON":
        return winning_return(stake_rc, odds)
    if result == "PARTIAL":
        if refund is not None:
            return refund_return(stake_rc, refund)
        if consolation is None:
            raise ValueError("a PARTIAL result needs the market's consolation share")
        return partial_return(stake_rc, odds, consolation)
    if result == "VOID":
        return stake_rc
    if result == "LOST":
        return 0
    raise ValueError(f"unknown result {result}")
