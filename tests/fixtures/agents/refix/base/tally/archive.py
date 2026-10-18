"""The month archive: one CSV file per month, kept for the person's records."""
from pathlib import Path

from tally import export


def archive_month(items, month, folder):
    """Write the expenses of month (YYYY-MM) to <folder>/<month>.csv, the header first, replacing the file when it
    exists; returns the path and the number of expenses written."""
    rows = [i for i in items if i["day"].startswith(month + "-")]
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{month}.csv"
    path.write_text("\n".join([export.HEADER, *export.csv_lines(rows)]) + "\n", encoding="utf-8")
    return path, len(rows)
