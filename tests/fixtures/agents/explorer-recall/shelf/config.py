"""Settings: where the loans file lives and how long a loan lasts."""
import json
import os
from pathlib import Path

DEFAULT_LOAN_DAYS = 21
CONFIG_FILE = Path.home() / ".config" / "shelf" / "config.json"


def read_config(path=CONFIG_FILE):
    """The user's settings file as a dict; {} when there is none."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def data_path(config=None):
    """The loans file: SHELF_DATA, then the settings file, then loans.json in the current folder."""
    config = read_config() if config is None else config
    return Path(os.environ.get("SHELF_DATA") or config.get("data") or "loans.json")


def loan_days(config=None):
    """How many days a loan lasts: SHELF_LOAN_DAYS, then the settings file, then the default."""
    config = read_config() if config is None else config
    raw = os.environ.get("SHELF_LOAN_DAYS") or config.get("loan_days")
    if raw is None:
        return DEFAULT_LOAN_DAYS
    days = int(raw)
    if days < 1:
        raise ValueError(f"a loan lasts at least one day, not {days}")
    return days
