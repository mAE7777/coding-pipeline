"""The bank statement formats tally imports, and how to tell them apart by their header line.

Each bank exports its account in its own CSV dialect: its own separator, column names, date format, decimal
mark, and way of telling money out from money in. A Format describes one dialect, and detect() picks the format
whose header is the statement's first line.
"""
import csv
import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class UnknownFormat(ValueError):
    pass


class BadField(ValueError):
    pass


def example_day(day_format):
    return datetime.date(2026, 9, 3).strftime(day_format)


@dataclass(frozen=True)
class Format:
    """One bank's dialect. Money out is told in one of three ways: a signed amount (negative is money out), a
    debit and a credit column (exactly one filled), or an unsigned amount with a column naming the direction."""
    name: str
    delimiter: str
    header: tuple
    day: str
    day_format: str
    payee: str
    amount: str = ""
    debit: str = ""
    credit: str = ""
    direction: str = ""
    out_word: str = ""
    in_word: str = ""
    decimal_comma: bool = False

    def parse_day(self, text):
        """The booking day as YYYY-MM-DD."""
        try:
            return datetime.datetime.strptime(text.strip(), self.day_format).date().isoformat()
        except ValueError:
            raise BadField(f"{self.day} {text!r} is not a date like {example_day(self.day_format)}") from None

    def parse_money(self, text, column):
        """A money cell as a Decimal, or None when the cell is empty."""
        raw = text.strip()
        if not raw:
            return None
        raw = raw.replace(".", "").replace(",", ".") if self.decimal_comma else raw.replace(",", "")
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise BadField(f"{column} {text!r} is not an amount") from None
        if not value.is_finite():
            raise BadField(f"{column} {text!r} is not an amount")
        return value

    def spent(self, row):
        """What the row took out of the account, as a positive Decimal; None when it is money in (or zero)."""
        if self.debit:
            out = self.parse_money(row[self.debit], self.debit)
            back = self.parse_money(row[self.credit], self.credit)
            if (out is None) == (back is None):
                raise BadField(f"exactly one of {self.debit} and {self.credit} must hold an amount")
            if out is not None and out < 0 or back is not None and back < 0:
                raise BadField(f"{self.debit} and {self.credit} hold amounts without a sign")
            return out if out else None
        value = self.parse_money(row[self.amount], self.amount)
        if value is None:
            raise BadField(f"{self.amount} is empty")
        if self.direction:
            way = row[self.direction].strip().casefold()
            if way not in (self.out_word, self.in_word):
                raise BadField(f"{self.direction} {row[self.direction]!r} is neither {self.out_word!r} nor "
                               f"{self.in_word!r}")
            if value < 0:
                raise BadField(f"{self.amount} {row[self.amount]!r} has a sign; {self.direction} gives the direction")
            return value if way == self.out_word and value else None
        return -value if value < 0 else None


FORMATS = (
    Format("northbank", ",", ("Date", "Description", "Amount"),
           day="Date", day_format="%d/%m/%Y", payee="Description", amount="Amount"),
    Format("riverside", ";", ("Transaction Date", "Payee", "Debit", "Credit"),
           day="Transaction Date", day_format="%Y-%m-%d", payee="Payee", debit="Debit", credit="Credit",
           decimal_comma=True),
    Format("mono", ",", ("Booking date", "Counterparty", "Amount (EUR)", "Type"),
           day="Booking date", day_format="%d.%m.%Y", payee="Counterparty", amount="Amount (EUR)",
           direction="Type", out_word="debit", in_word="credit"),
)


def detect(first_line):
    """The format whose header is this line (cells compared without surrounding spaces); UnknownFormat when no
    bank writes it."""
    for fmt in FORMATS:
        cells = next(csv.reader([first_line], delimiter=fmt.delimiter), [])
        if tuple(c.strip() for c in cells) == fmt.header:
            return fmt
    known = "; ".join(f"{f.name}: {f.delimiter.join(f.header)}" for f in FORMATS)
    raise UnknownFormat(f"the first line is not a header tally knows ({known})")
