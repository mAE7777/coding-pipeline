"""Books and loans."""
import datetime
from dataclasses import dataclass
from typing import Optional


class BadIsbn(ValueError):
    pass


def normalize_isbn(text):
    """An ISBN-10 or ISBN-13 with spaces and hyphens removed, its check digit verified."""
    digits = text.replace("-", "").replace(" ", "").upper()
    if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] == "X"):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
        ok = total % 11 == 0
    elif len(digits) == 13 and digits.isdigit():
        total = sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(digits))
        ok = total % 10 == 0
    else:
        ok = False
    if not ok:
        raise BadIsbn(f"not an ISBN: {text}")
    return digits


@dataclass
class Book:
    title: str
    isbn: str = ""


@dataclass
class Loan:
    book: Book
    borrower: str
    lent_on: datetime.date
    due_on: datetime.date
    returned_on: Optional[datetime.date] = None

    def is_overdue(self, today=None):
        """Still out after its due date."""
        today = today or datetime.date.today()
        return self.returned_on is None and today > self.due_on

    def to_dict(self):
        return {"title": self.book.title, "isbn": self.book.isbn, "borrower": self.borrower,
                "lent_on": self.lent_on.isoformat(), "due_on": self.due_on.isoformat(),
                "returned_on": self.returned_on.isoformat() if self.returned_on else None}

    @classmethod
    def from_dict(cls, d):
        day = datetime.date.fromisoformat
        return cls(Book(d["title"], d.get("isbn", "")), d["borrower"], day(d["lent_on"]), day(d["due_on"]),
                   day(d["returned_on"]) if d.get("returned_on") else None)
