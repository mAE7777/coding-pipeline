"""Amounts: parsed from what a person types, kept as whole cents, shown with two decimals."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class BadAmount(ValueError):
    pass


def parse_amount(text):
    """The amount typed ("12.5", "0.99") as whole cents; BadAmount when it is not a number."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise BadAmount(f"not an amount: {text}") from None
    if not value.is_finite():
        raise BadAmount(f"not an amount: {text}")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_amount(cents):
    """Cents as the tool shows them: 1250 -> "12.50"."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole}.{part:02d}"
