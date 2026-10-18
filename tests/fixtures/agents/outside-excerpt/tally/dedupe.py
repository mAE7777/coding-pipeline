"""Which lines of a statement are already in the ledger, so that importing a statement again records nothing twice.

Banks' exports overlap (a September statement and a mid-September to mid-October one share two weeks), so each
import compares the statement with what earlier imports recorded. A statement line and a recorded expense are the
same spending when they have the same day, payee, and amount. Expenses added by hand have no payee and never
match a statement line.
"""
from collections import namedtuple

Split = namedtuple("Split", "new already")


def key(item):
    """What makes a transaction and an expense the same spending: the day, the payee as the bank wrote it (case
    aside), and the amount in cents."""
    return item.day, item.payee.casefold(), item.cents


def split(transactions, expenses):
    """(the transactions not recorded yet, the transactions already recorded), each in statement order.

    >>> from tally.importer import Transaction
    >>> from tally.ledger import Expense
    >>> coffee = Transaction("2026-09-20", "CORNER COFFEE HOUSE", 350)
    >>> fuel = Transaction("2026-10-01", "SHELL STATION 114", 5800)
    >>> split([coffee, fuel], [Expense("2026-09-20", "food", 350, "Corner Coffee House")]).new == [fuel]
    True
    """
    seen = {key(e) for e in expenses if e.payee}
    new, already = [], []
    for t in transactions:
        k = key(t)
        if k in seen:
            already.append(t)
        else:
            seen.add(k)
            new.append(t)
    return Split(new, already)
