"""The ledger: every expense recorded, in the order it was recorded."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Expense:
    day: str
    category: str
    cents: int
    payee: str = ""  # the payee as the bank wrote it, for an imported expense; empty for one added by hand


class Ledger:
    def __init__(self, expenses=()):
        self._expenses = list(expenses)

    def add(self, expense):
        self._expenses.append(expense)

    def expenses(self):
        """Every expense, in the order recorded. A copy: changing it changes nothing in the ledger."""
        return list(self._expenses)

    def total(self, category):
        """What one category cost, in cents."""
        return sum(e.cents for e in self._expenses if e.category == category)
