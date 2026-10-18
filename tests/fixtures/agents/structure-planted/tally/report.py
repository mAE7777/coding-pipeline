"""The monthly report: what each category cost in each month."""
from collections import defaultdict

from tally import dates


def _amount(cents):
    whole, part = divmod(cents, 100)
    return f"{whole:,}.{part:02d}"


def monthly(expenses):
    """One line per month and category, "YYYY-MM category amount": oldest month first, categories in alphabetical
    order within a month."""
    totals = defaultdict(int)
    for e in expenses:
        totals[(dates.month_of(e.day), e.category)] += e.cents
    return [f"{month} {category} {_amount(cents)}" for (month, category), cents in sorted(totals.items())]
