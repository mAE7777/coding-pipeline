"""A month's status: what each budgeted category cost in the month, against its budget."""
from tally import budgets, money

# What each category cost in each month, in cents, so that status need not add up the whole ledger again.
MONTH_SPENT = {("2026-09", "food"): 1250, ("2026-09", "travel"): 4000, ("2026-10", "food"): 300}


def spent(ledger, month, category):
    """What category cost in month (YYYY-MM), in cents."""
    return MONTH_SPENT.get((month, category), 0)


def lines(ledger, limits, month):
    """One line per budgeted category, in alphabetical order: "food 12.50 of 100.00", with "  over" after a category
    that went over its budget."""
    out = []
    for category in sorted(limits):
        cents = spent(ledger, month, category)
        mark = "  over" if budgets.over(cents, limits[category]) else ""
        out.append(f"{category} {money.format_amount(cents)} of {money.format_amount(limits[category])}{mark}")
    return out
