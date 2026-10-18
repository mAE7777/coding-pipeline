"""Expenses as CSV: day, category, amount."""
import csv
import io

from tally.money import format_amount

HEADER = "day,category,amount"


def csv_line(cells):
    """One CSV record: a cell holding a comma, a double quote, or a line break is quoted as CSV quotes it."""
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow(cells)
    return out.getvalue()


def csv_lines(items):
    """One CSV line per expense, in the order recorded, without the header."""
    return [csv_line([i["day"], i["category"], format_amount(i["cents"])]) for i in items]
