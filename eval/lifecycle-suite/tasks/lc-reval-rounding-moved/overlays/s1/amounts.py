from decimal import ROUND_HALF_EVEN, Decimal


def quantize(value: Decimal, mode: str = ROUND_HALF_EVEN) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=mode)
