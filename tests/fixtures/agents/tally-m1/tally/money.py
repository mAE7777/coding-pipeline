"""Amounts: parsed from what a person types, kept as whole cents, shown with two decimals."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

LARGEST = 10_000_000_000  # cents: one hundred million


class BadAmount(ValueError):
    pass


def parse_amount(text):
    """The amount a person typed ("12.5", "1,250", "0.99") as whole cents; BadAmount when it is not one."""
    try:
        value = Decimal(text.replace(",", "").strip())
    except InvalidOperation:
        raise BadAmount(f"not an amount: {text}") from None
    if not value.is_finite() or value < 0:
        raise BadAmount(f"not an amount: {text}")
    cents = int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if cents > LARGEST:
        raise BadAmount(f"not an amount: {text} (at most {format_amount(LARGEST)})")
    return cents


def format_amount(cents):
    """Cents as the tool shows every amount: 125000 -> "1,250.00"."""
    whole, part = divmod(cents, 100)
    return f"{whole:,}.{part:02d}"
