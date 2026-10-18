"""Expenses as CSV: day, category, amount."""
from tally.money import format_amount

HEADER = "day,category,amount"


def cell(text):
    """A cell as CSV writes it: one holding a comma is quoted."""
    return f'"{text}"' if "," in text else text


def csv_lines(items):
    """One CSV line per expense, in the order recorded, without the header."""
    return [f"{i['day']},{cell(i['category'])},{format_amount(i['cents'])}" for i in items]
