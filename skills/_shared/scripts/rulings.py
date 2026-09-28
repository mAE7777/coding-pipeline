#!/usr/bin/env python3
"""Prove that every owner ruling in decisions.md quotes words the owner actually typed.

Usage:
  rulings.py record <project> --id D-<nnn> --quote "<the owner's words>" [--session <id> | --session codex:<id>]
  rulings.py check <project>

An owner entry in docs/project/decisions.md is a "## D-<nnn> · ..." section containing "[owner <date>]"
followed by the owner's words in double quotes. `record` looks for those words in a message the owner typed
as a whole sentence (or the whole message; a fragment could drop a "no" or a "don't") in the session
transcript (Claude Code: ~/.claude/projects/*/<session>.jsonl, session default
$CLAUDE_CODE_SESSION_ID; Codex: ~/.codex/sessions/**/rollout-*<id>*.jsonl), counting only typed prompts
(including messages sent while a turn runs), never tool output, hook text, compaction summaries, agent
hand-backs, or task notifications (which the harness also delivers in the user role), and
appends the proof to .evidence/rulings.jsonl (local-only). `check` requires, for every quoted string in every
owner entry, a proof whose quote equals it (whitespace aside), re-reads the transcript when it still exists, and checks
that each stand-in consent token in an owner entry is paired with a named non-goal or a contract-blocked
entry ("pairs: named non-goal (...)" or "pairs: contract-blocked @...").

Prints PASS / FAIL / WARN lines. Exit 0 when nothing FAILs, 1 otherwise, 2 on bad usage.
"""
import datetime
import glob
import json
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
SECTION = re.compile(r"^## (D-\d{3,})\b.*?(?=^## D-\d{3,}\b|\Z)", re.M | re.S)
OWNER = re.compile(r"\[owner (\d{4}-\d{2}-\d{2})\]\s*\"([^\"]+)\"")
CONSENT = re.compile(r"\[placeholder-consent:[^\]]*\]")
PAIRS = re.compile(r"pairs:\s*(named non-goal \(.+?\)|contract-blocked @\S+)", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def claude_transcript(session):
    hits = glob.glob(str(HOME / ".claude/projects" / "*" / f"{session}.jsonl"))
    return Path(hits[0]) if hits else None


def codex_transcript(session):
    hits = glob.glob(str(HOME / ".codex/sessions" / "**" / f"rollout-*{session}*.jsonl"), recursive=True)
    return Path(sorted(hits)[-1]) if hits else None


# Text the harness injects into the user role: agent hand-backs, task notifications, command echoes, reminders,
# continuation summaries. None of it was typed by the person, whatever field it arrives in.
INJECTED = ("<agent-message", "<task-notification", "<local-command", "<command-", "<bash-", "<system-reminder",
            "<user-prompt-submit-hook", "[SYSTEM NOTIFICATION", "[Subagent hand-back]", "This session is being continued",
            "Another Claude session sent a message")


def human(origin):
    """False when an origin marker says the message came from something other than the person."""
    return not isinstance(origin, dict) or origin.get("kind") in (None, "human")


def typed(text):
    return bool(text) and not text.lstrip().startswith(INJECTED)


COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def command_args(text):
    """The words the person typed after a slash command (stored as <command-name> ... <command-args>), or None."""
    if not text.lstrip().startswith(("<command-message>", "<command-name>")):
        return None
    m = COMMAND_ARGS.search(text)
    return m.group(1).strip() if m and m.group(1).strip() else None


def typed_messages(path):
    """[(uuid or line number, timestamp, text)] for every message the person typed. Agent hand-backs and task
    notifications arrive in the user role (a queued prompt with origin kind "peer", or a user entry); they are
    model or harness output and never count, and neither does anything from a subagent's side chain."""
    with open(path, encoding="utf-8") as f:
        return typed_in_lines(f)


def last_typed(path, tail_bytes=2_000_000):
    """The person's latest typed message, read from the end of the transcript only (hooks call this on every
    stop, and transcripts grow large). None when the tail holds no typed message."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - tail_bytes))
        chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.splitlines()[1:] if size > tail_bytes else chunk.splitlines()
    found = typed_in_lines(lines)
    return found[-1][2] if found else None


def typed_in_lines(lines):
    out = []
    for n, line in enumerate(lines, 1):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ts = e.get("timestamp", "")
        if e.get("isSidechain"):
            continue
        # Claude Code: typed prompts
        if e.get("type") == "user" and not e.get("isMeta") and not e.get("isCompactSummary") \
                and not e.get("isVisibleInTranscriptOnly") and human(e.get("origin")):
            content = (e.get("message") or {}).get("content")
            texts = [content] if isinstance(content, str) else \
                [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
            for t in texts:
                if command_args(t):
                    out.append((e.get("uuid") or f"line {n}", ts, command_args(t)))
                elif typed(t):
                    out.append((e.get("uuid") or f"line {n}", ts, t))
        # Claude Code: messages typed while a turn was running (origin kind "human"; agents arrive as "peer")
        att = e.get("attachment")
        if isinstance(att, dict) and att.get("type") == "queued_command" and att.get("commandMode") == "prompt" \
                and not att.get("isMeta") and not e.get("isMeta") and not att.get("handback") \
                and human(att.get("origin")):
            p = att.get("prompt")
            if isinstance(p, list):
                p = " ".join(x.get("text", "") for x in p if isinstance(x, dict))
            if isinstance(p, str) and typed(p):
                out.append((e.get("uuid") or f"line {n}", ts, p))
        # Codex rollouts
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else None
        if payload and e.get("type") == "event_msg" and payload.get("type") == "user_message" \
                and typed(payload.get("message", "")):
            out.append((f"line {n}", ts, payload.get("message", "")))
    return out


EDGE = " .,;:!?\"'\u3002\uff0c\uff01\uff1f"
BOUNDARY = re.compile(r"[.!?]+(?=\s|$)|[\u3002\uff01\uff1f]+|\n")


def quote_fits(quote, message):
    """True when the quote is the whole message or one or more whole consecutive sentences of it. A fragment is
    never enough: cut from "No. Don't drop the export feature", "drop the export feature" says the opposite."""
    q = norm(quote).strip(EDGE)
    if not q:
        return False
    cuts = sorted({0, len(message)} | {m.end() for m in BOUNDARY.finditer(message)})
    for i, start in enumerate(cuts):
        for end in cuts[i + 1:]:
            run = norm(message[start:end]).strip(EDGE)
            if run == q:
                return True
            if len(run) > len(q):
                break
    return False


def find_quote(path, quote):
    found = [m for m in typed_messages(path) if quote_fits(quote, m[2])]
    return found[-1] if found else None


def ledger_path(project):
    return Path(project) / ".evidence/rulings.jsonl"


def read_ledger(project):
    p = ledger_path(project)
    rows = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def resolve_transcript(session):
    if session.startswith("codex:"):
        return codex_transcript(session[len("codex:"):])
    return claude_transcript(session)


def cmd_record(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0])
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] in ("--id", "--quote", "--session")}
    if "--id" not in opts or "--quote" not in opts:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    session = opts.get("--session")
    if not session:
        from session_env import current  # noqa: E402
        tool, sid = current()
        if tool in (None, "ambiguous"):
            print(f"FAIL   ruling      no --session given and this command's session is "
                  f"{'ambiguous (both Claude Code and Codex variables are set)' if tool else 'unknown'}; "
                  "pass --session <id> or --session codex:<id>")
            return 1
        session = f"codex:{sid}" if tool == "codex" else sid
    transcript = resolve_transcript(session)
    if transcript is None:
        print(f"FAIL   ruling      no transcript found for session {session}")
        return 1
    hit = find_quote(transcript, opts["--quote"])
    if hit is None:
        print(f"FAIL   ruling      \"{opts['--quote'][:60]}\" is not a whole sentence (or the whole message) the owner "
              f"typed in session {session}; quote their full sentence, or ask them and record their own words")
        return 1
    row = {"id": opts["--id"], "quote": norm(opts["--quote"]), "session": session, "transcript": str(transcript),
           "message": hit[0], "message_time": hit[1],
           "recorded": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    lp = ledger_path(project)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(f"PASS   ruling      {opts['--id']} quote found in the owner's message {hit[0]} ({hit[1]})")
    if len(row["quote"]) < 12:
        print(f"WARN   ruling      {opts['--id']} quote is short; the proof points at the exact message")
    return 0


def same_words(a, b):
    """Equal after collapsing whitespace and trimming punctuation at the ends (a trailing period adds no words)."""
    edge = " .,;:!?\"'\u3002\uff0c\uff01\uff1f"
    return norm(a).strip(edge) == norm(b).strip(edge)


def quote_problems(did, owners, ledger):
    """([problem], [warning]) for one owner entry: every quoted string must equal (whitespace aside) a proof
    recorded for this entry, and that proof must still be in the transcript. A quote that only contains a
    proven fragment is not proven: words around the fragment were never shown to be the owner's."""
    problems, warnings = [], []
    for _, q in owners:
        rows = [r for r in ledger if r.get("id") == did and same_words(r.get("quote", ""), q)]
        if not rows:
            problems.append(f"{did} says [owner] \"{norm(q)[:50]}\" but no recorded proof equals those words "
                            "(rulings.py record with exactly the quoted words)")
            continue
        t = Path(rows[-1].get("transcript", ""))
        if not t.is_file():
            warnings.append(f"{did}: transcript no longer on disk; proof recorded {rows[-1].get('recorded')}")
        elif find_quote(t, rows[-1]["quote"]) is None:
            problems.append(f"{did}: the recorded quote is no longer in the owner's messages in {t.name}")
    return problems, warnings


def entry_proven(project, did):
    """(True, "") when decisions.md has an owner entry D-<nnn> whose every quote has a still-valid proof."""
    decisions = Path(project) / "docs/project/decisions.md"
    if not decisions.is_file():
        return False, "no docs/project/decisions.md"
    for m in SECTION.finditer(decisions.read_text(encoding="utf-8")):
        if m.group(1) != did:
            continue
        owners = OWNER.findall(m.group(0))
        if not owners:
            return False, f"{did} is not an owner ruling"
        problems, _ = quote_problems(did, owners, read_ledger(project))
        return (False, problems[0]) if problems else (True, "")
    return False, f"no entry {did} in decisions.md"


def cmd_check(argv):
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0])
    decisions = project / "docs/project/decisions.md"
    if not decisions.is_file():
        print("SKIP   rulings     no docs/project/decisions.md")
        return 0
    text = decisions.read_text(encoding="utf-8")
    ledger = read_ledger(project)
    fails = 0
    owner_entries = 0
    for m in SECTION.finditer(text):
        did, body = m.group(1), m.group(0)
        owners = OWNER.findall(body)
        consents = CONSENT.findall(body)
        if consents and not owners:
            print(f"FAIL   rulings     {did} holds a stand-in consent but no owner ruling")
            fails += 1
        if not owners:
            continue
        owner_entries += 1
        problems, warnings = quote_problems(did, owners, ledger)
        for w in warnings:
            print(f"WARN   rulings     {w}")
        if problems:
            for pr in problems:
                print(f"FAIL   rulings     {pr}")
            fails += 1
            continue
        for token in consents:
            if not PAIRS.search(body):
                print(f"FAIL   rulings     {did}: stand-in consent {token[:60]} is not paired with a named "
                      "non-goal or a contract-blocked entry")
                fails += 1
    if not fails:
        print(f"PASS   rulings     {owner_entries} owner ruling(s) proven")
    return 1 if fails else 0


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if argv[0] == "record":
        return cmd_record(argv[1:])
    if argv[0] == "check":
        return cmd_check(argv[1:])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
