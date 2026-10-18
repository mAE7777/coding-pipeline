"""Expenses as CSV: day, category, amount."""
from tally.money import format_amount

HEADER = "day,category,amount"


def csv_lines(items):
    """One CSV line per expense, in the order recorded, without the header."""
    return [f"{i['day']},{i['category']},{format_amount(i['cents'])}" for i in items]
