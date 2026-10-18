"""Reading a bank statement: its spending lines as transactions, or an error naming the first line that cannot be
read. Nothing here touches the ledger; the import command decides what is recorded."""
import csv
from dataclasses import dataclass
from pathlib import Path

from tally import banks, money


class BadStatement(ValueError):
    """A statement that cannot be imported. The message names the file and, for a bad line, its line number."""


@dataclass(frozen=True)
class Transaction:
    day: str
    payee: str
    cents: int


@dataclass(frozen=True)
class Statement:
    bank: str
    spending: tuple
    income_lines: int


def statement_lines(path):
    """The statement's lines, a byte order mark at its start removed."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise BadStatement(f"{path}: no such file") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BadStatement(f"{path}: cannot read it ({exc})") from None
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise BadStatement(f"{path}: the first line must be the bank's header, and it is empty")
    return lines


def transaction(fmt, row):
    """The row as a Transaction, or None when it is money in. banks.BadField or money.BadAmount when a cell
    cannot be read."""
    out = fmt.spent(row)
    day = fmt.parse_day(row[fmt.day])
    payee = " ".join(row[fmt.payee].split())
    if not payee:
        raise banks.BadField(f"{fmt.payee} is empty")
    if out is None:
        return None
    return Transaction(day, payee, money.parse_amount(str(out)))


def read_statement(path):
    """Every spending line of the statement at path, in the order the bank wrote them, and the count of income
    lines left out. All or nothing: one line that cannot be read stops the whole statement."""
    lines = statement_lines(path)
    try:
        fmt = banks.detect(lines[0])
    except banks.UnknownFormat as exc:
        raise BadStatement(f"{path}: {exc}") from None
    reader = csv.reader(lines[1:], delimiter=fmt.delimiter)
    spending, income = [], 0
    for cells in reader:
        number = reader.line_num + 1
        if not any(c.strip() for c in cells):
            continue
        if len(cells) != len(fmt.header):
            raise BadStatement(f"{path} line {number}: {len(cells)} fields, but a {fmt.name} statement has "
                               f"{len(fmt.header)} ({', '.join(fmt.header)})")
        try:
            found = transaction(fmt, dict(zip(fmt.header, cells)))
        except (banks.BadField, money.BadAmount) as exc:
            raise BadStatement(f"{path} line {number}: {exc}") from None
        if found is None:
            income += 1
        else:
            spending.append(found)
    return Statement(fmt.name, tuple(spending), income)
