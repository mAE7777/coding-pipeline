"""The monthly report: what each category cost in each month."""
from collections import defaultdict

from tally import dates, money


def monthly(expenses):
    """One line per month and category, "YYYY-MM category amount": oldest month first, categories in alphabetical
    order within a month."""
    totals = defaultdict(int)
    for e in expenses:
        totals[(dates.month_of(e.day), e.category)] += e.cents
    return [f"{month} {category} {money.format_amount(cents)}" for (month, category), cents in sorted(totals.items())]
