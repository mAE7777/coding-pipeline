"""Categories for imported spending: the person's rules, kept in rules.txt, matched against each payee.

A rule is one line, `<text> -> <category>`: a payee that contains the text, ignoring case, gets the category. The
first rule that matches wins, so specific rules go above general ones. Blank lines and lines starting with # are
left out. A payee that no rule matches is "uncategorized", which the person can total and fix like any category.
"""
from dataclasses import dataclass
from pathlib import Path

RULES = Path("rules.txt")
UNCATEGORIZED = "uncategorized"


class BadRules(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    text: str
    category: str

    def matches(self, payee):
        return self.text in payee.casefold()


def parse_rules(text, source=RULES):
    """The rules in text, in order; BadRules naming the first line that is not a rule."""
    rules = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pattern, arrow, category = line.partition("->")
        pattern, category = pattern.strip(), category.strip()
        if not arrow or not pattern or not category:
            raise BadRules(f"{source} line {number}: a rule is `<text> -> <category>`, not {line!r}")
        if "->" in category:
            raise BadRules(f"{source} line {number}: one arrow per rule, not {line!r}")
        rules.append(Rule(pattern.casefold(), category))
    return rules


def load_rules(path=RULES):
    """The rules in path; none when there is no rules file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise BadRules(f"cannot read {path}: {exc}") from None
    return parse_rules(text, path)


def category_of(payee, rules):
    """The category of the first rule matching the payee, or uncategorized."""
    return next((r.category for r in rules if r.matches(payee)), UNCATEGORIZED)
