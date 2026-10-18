"""Days as the tool records them: ISO dates, YYYY-MM-DD."""
import datetime
import re

ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class BadDay(ValueError):
    pass


def parse_day(text):
    """A day typed as YYYY-MM-DD and checked to be a real date; BadDay otherwise."""
    if not ISO_DAY.fullmatch(text):
        raise BadDay(f"not a day: {text} (use YYYY-MM-DD)")
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        raise BadDay(f"not a day: {text} (no such date)") from None


def today():
    return datetime.date.today().isoformat()


def month_of(day):
    # Checks the day first: anything that is not a real YYYY-MM-DD date raises BadDay.
    return day[:7]
