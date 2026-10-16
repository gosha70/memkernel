from decimal import Decimal


def to_cents(value: Decimal) -> int:
    return int(value * 100)
