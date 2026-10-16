"""Which loans are overdue, and the reminder to send for each."""
import datetime


def overdue_loans(loans, today=None):
    today = today or datetime.date.today()
    return sorted((loan for loan in loans if loan.is_overdue(today)), key=lambda loan: loan.due_on)


def reminder_text(loan, today=None):
    today = today or datetime.date.today()
    days = (today - loan.due_on).days
    return (f"Hi {loan.borrower}, a friendly nudge: \"{loan.book.title}\" was due back on "
            f"{loan.due_on:%d %B} ({days} day{'s' if days != 1 else ''} ago).")
