"""Loans as CSV, safe to open in a spreadsheet."""
import csv
import io

RISKY = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(text):
    """A cell a spreadsheet shows as text, never runs as a formula."""
    text = str(text)
    return "'" + text if text.startswith(RISKY) else text


def to_csv(loans):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["title", "isbn", "borrower", "lent_on", "due_on", "returned_on"])
    for loan in loans:
        writer.writerow([safe_cell(loan.book.title), loan.book.isbn, safe_cell(loan.borrower), loan.lent_on,
                         loan.due_on, loan.returned_on or ""])
    return out.getvalue()


def write_csv(loans, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_csv(loans))
