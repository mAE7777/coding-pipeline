#!/usr/bin/env python3
"""Keep idea conversations and documents whole: import them verbatim, and check the organized dossier
against them.

Usage:
  capture.py add <project> <file or folder> [--kind auto|chatgpt-export|chat-text|doc|log|pdf|office|code|audio]
                 [--chat <id or title>] [--title <title>] [--speaker owner|document] [--language <code>]
                 [--model <whisper model>]
  capture.py add <project> --inventory          the files adoption's inventory lists, by tier: documents,
                                                small configuration, and reports become sources to read; code
                                                and tests are left to the code map (mapped); data, raw output,
                                                and logs are registered with a script summary (bulk.md), not read
  capture.py add <project> --git-log            the project's commit history, one unit per commit, oldest first
  capture.py add <project> --tracker            its GitHub issues and pull requests with their comments
  capture.py list <conversations.json>          the conversations in a ChatGPT export
  capture.py draft <project> <extraction result.md>
                                                an independent extraction becomes dossier units (quotes checked,
                                                attribution and status kept); turns it drew nothing load-bearing
                                                from are listed as read with nothing to keep
  capture.py reconcile <project> <extraction result.md>
                                                an independent extraction against a dossier the builder wrote:
                                                every point no unit carries becomes a row to settle in a round
  capture.py audit <project> <fidelity result.md>
                                                an independent fidelity read of some sources against the units
                                                citing them: its material problems become rows to settle
  capture.py check <project>                    coverage, quotes, attribution, references, stable IDs, rounds
  capture.py closure <project>                  every dossier unit lands somewhere in the plan (brief.md)

Where things go (docs/project/sources/, local-only):
  SRC-<n>-<slug>/raw/<nn>.<ext> every revision of the input exactly as received (never edited)
  SRC-<n>-<slug>/turns.jsonl    the canonical turns: id, role, speaker, time, text (verbatim), node, parent
  SRC-<n>-<slug>/transcript.md  a readable rendering of the turns
  SRC-<n>-<slug>/meta.json      kind, title, conversation id, sha256 of every raw revision, counts
  index.md                      one line per source
  dossier.md                    the organized layer, written by the model (grammar in capture's reference)

Inputs.
  chatgpt-export  conversations.json from ChatGPT's data export (or one conversation's JSON). The main line
                  is the path to the conversation's current node; edited or regenerated alternatives are kept
                  as branches (B<k>-T<n>). Voice-mode turns come through as ChatGPT's own transcription, which
                  OpenAI says is not a verbatim record, so an owner turn spoken aloud is "owner (transcribed)".
                  Parts that carry no text (an image, an audio pointer) are named in the turn and counted.
  chat-text       a copied conversation with "You said:" / "ChatGPT said:" (or User:, Assistant:, Me:,
                  You:, ChatGPT:, Human:, AI:) markers.
  doc             a Markdown or text file; one turn per heading section (or paragraph when there are none),
                  speaker "document" unless --speaker owner.
  audio           a recording, transcribed locally with whisper through the heavy lock; turns are the pauses
                  in speech, speaker "owner (transcribed)", so a quote from it is marked as machine-transcribed.
  log             a log or record file (.log, .jsonl, .ndjson, .out, .err); one turn per window of 200 lines,
                  speaker "record", its time the first timestamp in the window.
  pdf             text extracted with pdftotext; one turn per page, speaker "document". A page without text
                  (a scan) is named; a PDF with no text at all is not read, and says so.
  office          Word, OpenDocument, RTF, HTML, EPUB: converted to Markdown with pandoc (or to text with
                  textutil when pandoc cannot read it; the converter used is recorded), then split as a doc.
  code            source code, tests, and configuration; one unit per window of 150 lines, speaker "code".
  git history and the tracker are records (speaker "record"): one unit per commit, issue, or pull request. The
  tracker needs the gh command signed in and a GitHub remote; without them the import says so and fails.
A folder is walked (hidden folders, dependencies, builds, and the sources folder itself left out): every file
it can read becomes a source (a log over 200 KB is registered with a script summary instead), a file unchanged since an earlier import is skipped, code files are left to the
code reading of /plan adopt, and every file it could not read is named with the reason. The walk is recorded in
sources/import-ledger.md.
A second import of the same conversation (same conversation id, or pasted text whose turns begin with an
existing source's turns) appends only the new turns to that source, keeping every earlier turn ID.

check FAILs when: a raw file's sha256 no longer matches; an owner turn, a document section, or a record is
neither cited by a unit nor listed under "## No-content turns" (assistant turns and code need not be); a source
has not been read by an independent extraction, or grew after its last one; a round or an audit has a row not
settled; a source has not been audited, or its latest audit found a material problem (it is audited again,
with the previous read, until an audit finds none; after two that keep finding, audit smaller portions or ask
the owner); a quote is not verbatim in the turn it cites, or an owner or
owner-agreed unit rests on no quote from an owner turn; a reference names a source or turn that does not
exist; a "superseded by" target is missing; a unit ID recorded by an earlier passing check has disappeared;
a unit line does not parse.
Exit 0 on success, 1 on a FAIL or a failed import, 2 on bad usage.
"""
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNER_MARK = r"You said:|User:|You:|Me:|Human:"
ASSIST_MARK = r"ChatGPT said:|Assistant:|ChatGPT:|AI:|Claude said:|Claude:"
MARK = re.compile(rf"^\s*({OWNER_MARK}|{ASSIST_MARK})\s*", re.M)
# The markers ChatGPT and Claude write when a chat is copied: when present, they are the only speaker breaks, so a
# reply that itself contains "User: ..." (sample dialogue, a script) stays inside the reply.
STRONG = re.compile(r"^\s*(You said:|ChatGPT said:|Claude said:)\s*", re.M)
CATEGORIES = {"problem", "vision", "narrative", "product", "user", "implementation", "research", "constraint",
              "decision", "rejected", "term", "other"}
ATTRIBUTION = {"owner", "owner-agreed", "assistant", "document", "transcribed", "record", "code"}
CODE_WINDOW = 150
INVENTORY_KINDS = {"doc": None, "legacy-record": None, "config": "code"}  # None: detected (doc, pdf, office)
# Code and tests are understood through adoption's code map, the reading of the modules that matter, and the
# characterization; they are not read as sources. Data, raw output, and logs are registered, not read.
MAPPED_CLASSES = ("code", "test")
BULK_DIRS = re.compile(r"(^|/)(raw|runs?|outputs?|responses?|logs?|dumps?|fixtures?|samples?|data|datasets?|cache|"
                       r"tmp|artifacts?|snapshots?)/", re.I)
KEEP_IN_BULK = re.compile(r"(readme|report|handoff|review|decision|plan|summary|notes?|brief|spec)[^/]*\.(md|txt)$", re.I)
SMALL_CONFIG = 20_000
COVERED_ROLES = ("document", "record")  # besides owner turns: every section and record is carried or read-with-nothing
AUDIT_METHOD_AFTER = 2  # audits that keep finding material problems: smaller portions, or ask the owner
AUDIO_SUFFIX = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm"}
LOG_SUFFIX = {".log", ".jsonl", ".ndjson", ".out", ".err"}
BIG_LOG = 200_000  # bytes: a larger log is registered with a script summary, not read window by window
PANDOC_SUFFIX = {".docx", ".odt", ".rtf", ".html", ".htm", ".epub"}
TEXTUTIL_SUFFIX = {".doc", ".docx", ".rtf", ".html", ".htm", ".odt", ".webarchive"}
TEXT_SUFFIX = {".md", ".markdown", ".txt", ".text", ".csv", ".tsv", ".org", ".rst", ".adoc"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".evidence", "dist", "build", ".next",
             "target", ".cache", ".idea", ".vscode"}
LOG_WINDOW = 200
CHANGE_METHOD_AFTER = 3  # rounds that keep finding misses: read in smaller portions or with another lens, never stop
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?")
UNIT = re.compile(r"^- (S-\d{3,}) · ([a-z]+) · ([a-z-]+) · (current|open|not taken up|rejected|superseded by S-\d{3,}) · (.+)$")
QUOTE = re.compile(r'^\s+>\s*"(.+)"\s*\((SRC-\d+) (B\d+-)?(T\d{3,})\)\s*$')
REF = re.compile(r"(SRC-\d+)\s+((?:(?:B\d+-)?T\d{3,}(?:-T\d{3,})?(?:,\s*)?)+)")


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "source"


def iso(ts):
    try:
        return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


# ---------- ChatGPT export ----------

def load_export(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def conv_id(c):
    return c.get("conversation_id") or c.get("id") or ""


def render_part(part, notes, flags):
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    kind = part.get("content_type", "part")
    if kind == "audio_transcription":
        flags.add("transcribed")
        return part.get("text", "")
    if part.get("text"):
        return part["text"]
    notes.append(kind)
    return f"[{kind.replace('_', ' ')}: no text in the export]"


def message_text(msg, notes, flags=None):
    flags = set() if flags is None else flags
    content = msg.get("content") or {}
    ctype = content.get("content_type", "text")
    if "parts" in content:
        return "\n".join(t for t in (render_part(p, notes, flags) for p in content.get("parts") or []) if t)
    if ctype in ("code", "execution_output") and content.get("text"):
        return content["text"]
    if content.get("text"):
        return content["text"]
    if content.get("result"):
        return content["result"]
    notes.append(ctype)
    return f"[{ctype.replace('_', ' ')}: not rendered]"


def role_of(msg):
    role = (msg.get("author") or {}).get("role", "")
    return {"user": "owner", "assistant": "assistant", "tool": "tool"}.get(role, role or "unknown")


def turn_of(nid, msg, mapping, notes):
    """One turn; an owner turn spoken in voice mode is marked as transcribed (not a verbatim record)."""
    flags = set()
    text = message_text(msg, notes, flags)
    role = role_of(msg)
    if role == "owner" and "transcribed" in flags:
        role = "owner (transcribed)"
    return {"node": nid, "role": role, "time": iso(msg.get("create_time")), "text": text,
            "parent": (mapping.get(nid) or {}).get("parent")}


def chatgpt_turns(conv):
    mapping = conv.get("mapping") or {}
    cur = conv.get("current_node")
    path = []
    while cur:
        path.append(cur)
        cur = (mapping.get(cur) or {}).get("parent")
    path.reverse()
    on_path = set(path)
    notes, skipped = [], 0

    def usable(node_id):
        node = mapping.get(node_id) or {}
        msg = node.get("message")
        if not msg:
            return None
        meta = msg.get("metadata") or {}
        if role_of(msg) in ("system", "unknown") or meta.get("is_visually_hidden_from_conversation"):
            return "skip"
        return msg

    main = []
    for nid in path:
        msg = usable(nid)
        if msg == "skip":
            skipped += 1
            continue
        if msg:
            main.append(turn_of(nid, msg, mapping, notes))
    branches = []
    for nid in path:
        for child in (mapping.get(nid) or {}).get("children") or []:
            if child in on_path:
                continue
            seq, stack = [], [child]
            while stack:
                cid = stack.pop(0)
                msg = usable(cid)
                if msg and msg != "skip":
                    seq.append(turn_of(cid, msg, mapping, notes))
                kids = (mapping.get(cid) or {}).get("children") or []
                stack = kids[:1] + stack
            if seq:
                branches.append({"from_node": nid, "turns": seq})
    return main, branches, skipped, notes


# ---------- pasted chat text and documents ----------

def chat_text_turns(text):
    """Turns of a pasted chat, and a warning when the speaker breaks had to be guessed from short markers."""
    marks = list(STRONG.finditer(text))
    warning = None
    if not marks:
        marks = list(MARK.finditer(text))
        if marks:
            warning = ("speaker breaks were read from short markers (User:, Me:, AI:, ...) because the paste has no "
                       "\"You said:\" / \"ChatGPT said:\" lines; a reply that quotes such a line would be split wrongly, "
                       "so check the turns before building the dossier")
    if not marks:
        return None, None
    turns = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip("\n")
        role = "owner" if re.match(OWNER_MARK, m.group(1)) else "assistant"
        turns.append({"node": None, "role": role, "time": "", "text": body.strip(), "parent": None})
    return turns, warning


def doc_turns(text, speaker):
    parts = re.split(r"(?m)^(?=#{1,6} )", text)
    parts = [p for p in parts if p.strip()]
    if len(parts) <= 1:
        parts = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [{"node": None, "role": speaker, "time": "", "text": p.strip(), "parent": None} for p in parts]


def audio_turns(path, language, model):
    whisper = shutil.which("whisper")
    if not whisper:
        return None, "NOT_RUN: whisper is not installed (uv tool install openai-whisper)"
    out = Path(tempfile.mkdtemp(prefix="capture-audio-"))
    cmd = [sys.executable, str(HERE / "heavy.py"), "run", "--", whisper, str(path), "--model", model,
           "--output_format", "json", "--output_dir", str(out)]
    if language:
        cmd += ["--language", language]
    r = subprocess.run(cmd, capture_output=True, text=True)
    jfiles = list(out.glob("*.json"))
    if r.returncode != 0 or not jfiles:
        return None, f"FAIL: whisper exited {r.returncode}: {r.stderr.strip()[-300:]}"
    segs = json.loads(jfiles[0].read_text()).get("segments", [])
    turns, cur, last_end = [], [], None
    for s in segs:
        if cur and last_end is not None and s["start"] - last_end > 2.0:
            turns.append(cur)
            cur = []
        cur.append(s)
        last_end = s["end"]
    if cur:
        turns.append(cur)
    shutil.rmtree(out, ignore_errors=True)
    return [{"node": None, "role": "owner (transcribed)", "time": f"{g[0]['start']:.0f}s",
             "text": " ".join(x["text"].strip() for x in g), "parent": None} for g in turns], None


class Unreadable(Exception):
    """A file that cannot be turned into text; the message says why and what would fix it."""


def log_turns(text):
    lines = text.splitlines()
    out = []
    for i in range(0, len(lines), LOG_WINDOW):
        chunk = lines[i:i + LOG_WINDOW]
        if not "".join(chunk).strip():
            continue
        stamp = TIMESTAMP.search("\n".join(chunk))
        span = f"lines {i + 1}-{i + len(chunk)}" + (f" · {stamp.group(0)}" if stamp else "")
        out.append({"node": None, "role": "record", "time": span, "text": "\n".join(chunk), "parent": None})
    return out


def code_turns(text):
    lines = text.splitlines()
    return [{"node": None, "role": "code", "time": f"lines {i + 1}-{i + len(lines[i:i + CODE_WINDOW])}",
             "text": "\n".join(lines[i:i + CODE_WINDOW]), "parent": None}
            for i in range(0, len(lines), CODE_WINDOW) if "".join(lines[i:i + CODE_WINDOW]).strip()]


SEP = "\x1e"


def git_history(project):
    """(text, turns): every commit, oldest first, with its full message and changed files."""
    if not shutil.which("git") or not (Path(project) / ".git").exists():
        raise Unreadable("not a git repository (no history to read)")
    r = subprocess.run(["git", "-C", str(project), "log", "--reverse", "--date=iso-strict", "--name-status",
                        f"--format={SEP}%H%n%ad%n%an%n%B"], capture_output=True, text=True)
    if r.returncode != 0:
        raise Unreadable(f"git log failed: {r.stderr.strip()[-200:]}")
    turns = []
    for block in r.stdout.split(SEP)[1:]:
        lines = block.strip("\n").splitlines()
        if len(lines) < 3:
            continue
        turns.append({"node": lines[0], "role": "record", "time": lines[1],
                      "text": f"commit {lines[0][:12]} by {lines[2]}\n" + "\n".join(lines[3:]).strip(), "parent": None})
    if not turns:
        raise Unreadable("the repository has no commits")
    return r.stdout, turns


def tracker_items(project):
    """(text, turns): every GitHub issue and pull request, oldest first, with body and comments."""
    gh = shutil.which("gh")
    if not gh:
        raise Unreadable("the gh command is not installed, so the issue tracker cannot be read")
    turns, raw, limit = [], [], 100000
    for kind in ("issue", "pr"):
        r = subprocess.run([gh, kind, "list", "--state", "all", "--limit", str(limit), "--json",
                            "number,title,body,state,createdAt,author,comments"], cwd=project, capture_output=True, text=True)
        if r.returncode != 0:
            raise Unreadable(f"gh {kind} list failed ({r.stderr.strip()[-200:] or 'no output'}); sign in with gh auth "
                             "login, or record the tracker as unread")
        items = json.loads(r.stdout or "[]")
        if len(items) >= limit:
            raise Unreadable(f"gh returned {limit} {kind}s, the most it was asked for, so some may be missing")
        raw.append(r.stdout)
        for it in items:
            comments = "\n".join(f"- {(c.get('author') or {}).get('login', '?')}: {c.get('body', '').strip()}"
                                  for c in it.get("comments") or [])
            text = (f"{'Pull request' if kind == 'pr' else 'Issue'} #{it['number']} ({it.get('state')}) by "
                    f"{(it.get('author') or {}).get('login', '?')}: {it.get('title', '')}\n\n"
                    f"{(it.get('body') or '').strip()}" + (f"\n\nComments:\n{comments}" if comments else ""))
            # Keyed by content: an issue that gained comments comes back as a new version, never skipped.
            turns.append({"node": f"{kind}-{it['number']}-{sha(text.encode())[:12]}", "role": "record",
                          "time": it.get("createdAt", ""),
                          "text": text, "parent": None})
    turns.sort(key=lambda t: t["time"])
    if not turns:
        raise Unreadable("the tracker has no issues or pull requests")
    return "\n".join(raw), turns


def pdf_turns(path):
    tool = shutil.which("pdftotext")
    if not tool:
        raise Unreadable("pdftotext is not installed (brew install poppler)")
    r = subprocess.run([tool, "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, text=True)
    if r.returncode != 0:
        raise Unreadable(f"pdftotext failed: {r.stderr.strip()[-200:]}")
    pages = r.stdout.split("\f")
    turns, blank = [], []
    for i, page in enumerate(pages, 1):
        if page.strip():
            turns.append({"node": None, "role": "document", "time": f"page {i}", "text": page.strip("\n"),
                          "parent": None})
        elif i < len(pages):
            blank.append(i)
    if not turns:
        raise Unreadable("the PDF has no text layer (a scan: run OCR, then import the text)")
    return turns, ([f"pages without text (scanned images?): {', '.join(map(str, blank))}"] if blank else []), \
        "pdftotext -layout"


def office_text(path):
    """(text, converter) for Word, OpenDocument, RTF, HTML, EPUB."""
    suffix, tried = path.suffix.lower(), []
    pandoc = shutil.which("pandoc")
    if pandoc and suffix in PANDOC_SUFFIX:
        r = subprocess.run([pandoc, str(path), "-t", "gfm", "--wrap=none"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout, "pandoc to Markdown"
        tried.append(f"pandoc: {(r.stderr.strip() or 'no text')[-150:]}")
    textutil = shutil.which("textutil")
    if textutil and suffix in TEXTUTIL_SUFFIX:
        r = subprocess.run([textutil, "-convert", "txt", "-stdout", str(path)], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout, "textutil to text" + (f" (after {tried[0]})" if tried else "")
        tried.append(f"textutil: {(r.stderr.strip() or 'no text')[-150:]}")
    raise Unreadable("no converter could read it" + (f" ({'; '.join(tried)})" if tried else
                                                     " (install pandoc: brew install pandoc)"))


def looks_like_export(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    items = data if isinstance(data, list) else [data]
    return bool(items) and all(isinstance(c, dict) and "mapping" in c for c in items[:3])


# ---------- storage ----------

def sources_dir(project):
    d = Path(project) / "docs/project/sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def existing_sources(project):
    out = []
    for m in sorted(sources_dir(project).glob("SRC-*/meta.json")):
        try:
            out.append((m.parent, json.loads(m.read_text())))
        except ValueError:
            continue
    return out


def read_turns(folder):
    p = folder / "turns.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []


def write_source(folder, meta, turns):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "turns.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in turns),
                                        encoding="utf-8")
    main = [t for t in turns if not t["id"].startswith("B")]
    meta["counts"] = {"turns": len(main), "owner": sum(1 for t in main if t["role"].startswith("owner")),
                      "branch_turns": len(turns) - len(main)}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# {meta['id']} · {meta['title']}", "",
             f"Kind: {meta['kind']}" + (f" · conversation {meta['conversation']}" if meta.get("conversation") else "")
             + f" · imported {meta['revisions'][0]['at']}",
             f"Turns: {meta['counts']['turns']} (owner {meta['counts']['owner']}) · branch turns: "
             f"{meta['counts']['branch_turns']} · hidden or system messages skipped: {meta.get('skipped', 0)} · "
             f"parts without text: {len(meta.get('unrendered', []))}",
             "Canonical text: turns.jsonl (this file is a rendering of it).", ""]
    for t in main:
        follows = f" · follows {t['follows']}" if t.get("follows") else ""
        lines += [f"### {t['id']} · {t['role']}" + (f" · {t['time']}" if t["time"] else "") + follows, "", t["text"], ""]
    branch_ids = sorted({t["id"].split("-")[0] for t in turns if t["id"].startswith("B")}, key=lambda b: int(b[1:]))
    if branch_ids:
        lines += ["## Other branches", ""]
        for b in branch_ids:
            bt = [t for t in turns if t["id"].startswith(b + "-")]
            lines += [f"### {b} · branches after {bt[0].get('branch_of', '?')}", ""]
            for t in bt:
                lines += [f"#### {t['id']} · {t['role']}" + (f" · {t['time']}" if t["time"] else ""), "", t["text"], ""]
    (folder / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def write_index(project):
    rows = ["# Sources", "", "| ID | Title | Kind | Turns | Owner turns | Imported | Revisions |", "|---|---|---|---|---|---|---|"]
    for folder, meta in existing_sources(project):
        rows.append(f"| {meta['id']} | {meta['title']} | {meta['kind']} | {meta['counts']['turns']} | "
                    f"{meta['counts']['owner']} | {meta['revisions'][0]['at']} | {len(meta['revisions'])} |")
    (sources_dir(project) / "index.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def detect_kind(path):
    suffix = path.suffix.lower()
    if suffix in AUDIO_SUFFIX:
        return "audio"
    if suffix == ".json":
        return "chatgpt-export" if looks_like_export(path) else "doc"
    if suffix in LOG_SUFFIX:
        return "log"
    if suffix == ".pdf":
        return "pdf"
    if suffix in PANDOC_SUFFIX | TEXTUTIL_SUFFIX:
        return "office"
    text = path.read_text(encoding="utf-8", errors="replace")
    return "chat-text" if MARK.search(text) else "doc"


def folder_reason(path):
    """Why a file in a folder import is not read as a source, or None when it is."""
    from languages import CODE  # noqa: E402
    suffix = path.suffix.lower()
    if suffix in CODE:
        return "code: read by the code reading of /plan adopt, not as a document"
    if suffix in AUDIO_SUFFIX | LOG_SUFFIX | PANDOC_SUFFIX | TEXTUTIL_SUFFIX | TEXT_SUFFIX | {".pdf", ".json"}:
        return None
    try:
        head = path.read_bytes()[:4096]
    except OSError as exc:
        return f"cannot be opened ({exc.strerror})"
    if b"\0" in head:
        return f"binary {suffix or 'file'} with no text to read (an image or archive: describe it by hand if it matters)"
    return None


def number(turns, start=1):
    for i, t in enumerate(turns, start):
        t["id"] = f"T{i:03d}"
    return turns


def cmd_add(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project, src = Path(argv[0]).resolve(), Path(argv[1])
    opts = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1) if argv[i].startswith("--")}
    if argv[1] in ("--inventory", "--git-log", "--tracker"):
        try:
            return {"--inventory": add_inventory, "--git-log": add_history, "--tracker": add_tracker}[argv[1]](project)
        except Unreadable as exc:
            print(f"FAIL   capture     {argv[1][2:]}: not read: {exc}")
            return 1
    if src.is_dir():
        return add_folder(project, src.resolve(), opts)
    if not src.is_file():
        print(f"capture: no such file or folder: {src}", file=sys.stderr)
        return 2
    try:
        return add_file(project, src, opts)
    except Unreadable as exc:
        print(f"FAIL   capture     {src}: not read: {exc}")
        return 1


def add_folder(project, folder, opts):
    sources = sources_dir(project).resolve()
    known = {rev["sha256"]: meta["id"] for _, meta in existing_sources(project) for rev in meta["revisions"]}
    rows, failed = [], 0
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder)
        if not path.is_file() or any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]) \
                or path.name.startswith(".") or sources in path.resolve().parents:
            continue
        reason = folder_reason(path)
        if reason:
            rows.append((str(rel), f"not a source: {reason}"))
            continue
        if path.suffix.lower() in LOG_SUFFIX and path.stat().st_size > BIG_LOG:
            rows.append((str(rel), f"registered, not read (a large log: {bulk_summary(path)}); read the windows a "
                                   "question points to"))
            continue
        digest = sha(path.read_bytes())
        if digest in known:
            rows.append((str(rel), f"unchanged since {known[digest]}"))
            continue
        before = {m["id"] for _, m in existing_sources(project)}
        try:
            code = add_file(project, path, {k: v for k, v in opts.items() if k not in ("--title", "--kind", "--chat")})
        except Unreadable as exc:
            rows.append((str(rel), f"NOT READ: {exc}"))
            failed += 1
            print(f"FAIL   capture     {rel}: not read: {exc}")
            continue
        after = [m["id"] for _, m in existing_sources(project) if m["id"] not in before]
        rows.append((str(rel), f"imported as {after[0]}" if after else ("added turns to an earlier source" if code == 0
                                                                          else "import failed (see above)")))
        failed += code != 0
        known[digest] = after[0] if after else "an earlier source"
    ledger = sources_dir(project) / "import-ledger.md"
    lines = [f"\n## {now()} · {folder}", "", "| File | Result |", "|---|---|"] + [f"| {f} | {r} |" for f, r in rows]
    with open(ledger, "a", encoding="utf-8") as fh:
        if ledger.stat().st_size == 0:
            fh.write("# Import ledger\n\nEvery file a folder import saw, and what became of it.\n")
        fh.write("\n".join(lines) + "\n")
    imported = sum(1 for _, r in rows if r.startswith("imported"))
    print(f"folder {folder}: {imported} imported · {sum(1 for _, r in rows if r.startswith('unchanged'))} unchanged · "
          f"{sum(1 for _, r in rows if r.startswith('not a source'))} not sources · {failed} not read · ledger {ledger}")
    return 1 if failed else 0


def add_generated(project, title, kind, text, turns):
    """Import text the script produced itself (history, tracker) as a source, appending to an earlier import."""
    tmp = Path(tempfile.mkdtemp(prefix="capture-gen-")) / f"{slug(title)}.txt"
    tmp.write_text(text, encoding="utf-8")
    try:
        return add_file(project, tmp, {"--title": title}, preset=(kind, turns))
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


def add_history(project):
    text, turns = git_history(project)
    return add_generated(project, "git history", "git-history", text, turns)


def add_tracker(project):
    text, turns = tracker_items(project)
    return add_generated(project, "issue tracker", "tracker", text, turns)


def add_inventory(project):
    inv = Path(project) / "docs/project/research/adoption/inventory.json"
    if not inv.is_file():
        raise Unreadable("no adoption inventory yet (adopt.py inventory)")
    files = json.loads(inv.read_text()).get("files", [])
    known = {rev["sha256"]: meta["id"] for _, meta in existing_sources(project) for rev in meta["revisions"]}
    rows, failed, bulk = {}, 0, []
    for f in files:
        cls = f["class"]
        if cls not in INVENTORY_KINDS and cls not in MAPPED_CLASSES and cls != "other":
            continue
        path = Path(project) / f["path"]
        if not path.is_file():
            rows[f["path"]] = ("todo", "missing on disk")
            continue
        if cls in MAPPED_CLASSES:
            rows[f["path"]] = ("mapped (code map)", "understood through the code map, the reading of its area where "
                                                    "its role is not settled by the map, and the characterization")
            continue
        size = path.stat().st_size
        if cls == "other" or (cls == "config" and size > SMALL_CONFIG) or \
                (BULK_DIRS.search(f["path"]) and not KEEP_IN_BULK.search(f["path"])):
            summary = bulk_summary(path)
            rows[f["path"]] = ("registered (bulk)", summary)
            bulk.append(f"| {f['path']} | {cls} | {summary} |")
            continue
        digest = sha(path.read_bytes())
        if digest in known:
            rows[f["path"]] = ("captured", known[digest])
            continue
        before = {m["id"] for _, m in existing_sources(project)}
        kind = INVENTORY_KINDS[f["class"]]
        try:
            code = add_file(project, path, {"--title": f["path"], **({"--kind": kind} if kind else {})})
        except Unreadable as exc:
            rows[f["path"]] = ("todo", f"NOT READ: {exc}")
            failed += 1
            print(f"FAIL   capture     {f['path']}: not read: {exc}")
            continue
        new = [m["id"] for _, m in existing_sources(project) if m["id"] not in before]
        if code == 0 and new:
            rows[f["path"]] = ("captured", new[0])
            known[digest] = new[0]
        else:
            rows[f["path"]] = ("todo", "import failed (see above)")
            failed += 1
    if bulk:
        (Path(project) / "docs/project/research/adoption/bulk.md").write_text(
            "# Registered, not read\n\nData, raw output, logs, and generated files, summarized by script. The files "
            "stay as they are; read one when a question points to it, and say so in the brief.\n\n"
            "| Path | Class | Summary |\n|---|---|---|\n" + "\n".join(bulk) + "\n", encoding="utf-8")
    ledger = Path(project) / "docs/project/research/adoption/coverage.md"
    if ledger.is_file():
        out = []
        for line in ledger.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0] in rows:
                status, note = rows[cells[0]]
                line = f"| {cells[0]} | {cells[1]} | {cells[2]} | {status} | {note} |"
            out.append(line)
        ledger.write_text("\n".join(out) + "\n", encoding="utf-8")
    done = sum(1 for s_, _ in rows.values() if s_ == "captured")
    mapped = sum(1 for s_, _ in rows.values() if s_.startswith("mapped"))
    print(f"inventory: {done} file(s) captured to read · {mapped} code file(s) mapped · {len(bulk)} registered "
          f"(research/adoption/bulk.md) · {failed} not read" +
          (" (named above; each stays todo in the coverage ledger)" if failed else ""))
    return 1 if failed else 0


def bulk_summary(path):
    """Size, lines, time range, error lines, and the shape of JSON or CSV, without a model."""
    size = path.stat().st_size
    try:
        with open(path, "rb") as fh:
            raw = fh.read(4_000_000 if size <= 4_000_000 else 1_000_000)
            if size > 4_000_000:
                fh.seek(-1_000_000, 2)
                raw += b"\n" + fh.read()
    except OSError as exc:
        return f"{size:,} bytes; unreadable ({exc.__class__.__name__})"
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    parts = [f"{size:,} bytes", f"{len(lines):,} lines" + ("+" if size > 4_000_000 else "")]
    if path.suffix.lower() == ".json" and size <= 4_000_000:
        try:
            obj = json.loads(text)
            parts.append("keys: " + ", ".join(list(obj)[:12]) if isinstance(obj, dict) else f"a list of {len(obj)}")
        except ValueError:
            pass
    elif path.suffix.lower() in (".csv", ".tsv") and lines:
        parts.append("header: " + lines[0][:120])
    stamps = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    if stamps:
        parts.append(f"{min(stamps)} to {max(stamps)}")
    errors = sum(1 for line in lines if re.search(r"\b(ERROR|FAIL(ED)?|Traceback|Exception)\b", line))
    if errors:
        parts.append(f"{errors} error line(s)")
    return "; ".join(parts).replace("|", "/")


def add_file(project, src, opts, preset=None):
    kind = opts.get("--kind", "auto")
    kind = preset[0] if preset else (detect_kind(src) if kind == "auto" else kind)
    raw = src.read_bytes()
    conversation, title, branches, skipped, notes = None, opts.get("--title") or src.stem, [], 0, []
    converter = None
    if preset:
        turns = preset[1]
    elif kind == "chatgpt-export":
        convs = load_export(src)
        want = opts.get("--chat")
        if want:
            convs = [c for c in convs if conv_id(c) == want or want.lower() in (c.get("title") or "").lower()]
        if len(convs) != 1:
            print(f"capture: {len(convs)} conversations match; name one with --chat (capture.py list {src})",
                  file=sys.stderr)
            return 1
        conv = convs[0]
        conversation, title = conv_id(conv), opts.get("--title") or conv.get("title") or title
        turns, branches, skipped, notes = chatgpt_turns(conv)
    elif kind == "chat-text":
        turns, warning = chat_text_turns(raw.decode("utf-8", errors="replace"))
        if turns is None:
            print("capture: no speaker markers found; import it with --kind doc", file=sys.stderr)
            return 1
        if warning:
            print(f"WARN   capture     {warning}")
    elif kind == "doc":
        turns = doc_turns(raw.decode("utf-8", errors="replace"), opts.get("--speaker", "document"))
    elif kind == "log":
        turns = log_turns(raw.decode("utf-8", errors="replace"))
    elif kind == "pdf":
        turns, notes, converter = pdf_turns(src)
    elif kind == "office":
        text, converter = office_text(src)
        turns = doc_turns(text, opts.get("--speaker", "document"))
    elif kind == "code":
        turns = code_turns(raw.decode("utf-8", errors="replace"))
    elif kind == "audio":
        turns, err = audio_turns(src, opts.get("--language"), opts.get("--model", "turbo"))
        if turns is None:
            print(f"capture: {err}", file=sys.stderr)
            return 1
    else:
        print(f"capture: unknown kind {kind}", file=sys.stderr)
        return 2
    if not turns:
        print("capture: nothing to import (no turns found)", file=sys.stderr)
        return 1

    target, meta, old = None, None, []
    for folder, m in existing_sources(project):
        prev = read_turns(folder)
        main_prev = [t for t in prev if not t["id"].startswith("B")]
        if conversation and m.get("conversation") == conversation:
            target, meta, old = folder, m, prev
            break
        if not conversation and kind == m["kind"] and main_prev and len(turns) > len(main_prev) and \
                all(norm(a["text"]) == norm(b["text"]) for a, b in zip(main_prev, turns)):
            target, meta, old = folder, m, prev
            break
        if kind in ("git-history", "tracker") and m["kind"] == kind:
            # A later import adds only what is new or changed (new commits, new issues, an issue with new
            # comments as a new version), keeping every earlier unit and its ID.
            target, meta, old = folder, m, prev
            break
    if target is None:
        n = len(existing_sources(project)) + 1
        meta = {"id": f"SRC-{n}", "title": title, "kind": kind, "conversation": conversation, "revisions": []}
        if converter:
            meta["converter"] = converter
        target = sources_dir(project) / f"SRC-{n}-{slug(title)}"
        all_turns = number(turns)
    else:
        main_old = [t for t in old if not t["id"].startswith("B")]
        known_nodes = {t["node"] for t in old if t.get("node")}
        if conversation or kind in ("git-history", "tracker"):
            new = [t for t in turns if t["node"] not in known_nodes]
            by_node = {t["node"]: t["id"] for t in old if t.get("node")}
        else:
            new = turns[len(main_old):]
            by_node = {}
        next_n = max((int(t["id"][1:]) for t in main_old), default=0) + 1
        for t in number(new, next_n):
            parent_id = by_node.get(t.get("parent"))
            if parent_id and main_old and parent_id != main_old[-1]["id"]:
                t["follows"] = parent_id
            by_node[t.get("node")] = t["id"]
        all_turns = old + new
        branches = [b for b in branches if all(t["node"] not in known_nodes for t in b["turns"])]
    node_ids = {t.get("node"): t["id"] for t in all_turns if t.get("node")}
    existing_b = {t["id"].split("-")[0] for t in all_turns if t["id"].startswith("B")}
    bn = len(existing_b)
    for b in branches:
        bn += 1
        for i, t in enumerate(b["turns"], 1):
            t["id"] = f"B{bn}-T{i:03d}"
            t["branch_of"] = node_ids.get(b["from_node"], "the start")
            all_turns.append(t)
    rev_dir = target / "raw"
    rev_dir.mkdir(parents=True, exist_ok=True)
    rev = len(meta["revisions"]) + 1
    (rev_dir / f"{rev:02d}{src.suffix or '.txt'}").write_bytes(raw)
    meta["revisions"].append({"at": now(), "file": f"raw/{rev:02d}{src.suffix or '.txt'}", "sha256": sha(raw),
                              "from": str(src)})
    meta["skipped"] = meta.get("skipped", 0) + skipped
    meta["unrendered"] = meta.get("unrendered", []) + notes
    write_source(target, meta, all_turns)
    write_index(project)
    added = len(all_turns) - len(old)
    print(f"{meta['id']} · {meta['title']} · {kind} · {added} turn(s) added · {meta['counts']['turns']} on the main line"
          + (f" · {len(notes)} part(s) without text" if notes else ""))
    return 0


def cmd_list(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    for c in load_export(argv[0]):
        main, branches, _, _ = chatgpt_turns(c)
        print(f"{conv_id(c)}  {iso(c.get('create_time'))} -> {iso(c.get('update_time'))}  {len(main)} turns  "
              f"{len(branches)} branches  {c.get('title')}")
    return 0


# ---------- checks ----------

def parse_dossier(text):
    units, problems, current = {}, [], None
    in_units = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_units = line.strip() == "## Units"
            current = None
            continue
        if not in_units:
            continue
        if line.startswith("- S-"):
            m = UNIT.match(line.strip())
            if not m:
                problems.append(f"unit line does not parse: {line.strip()[:90]}")
                current = None
                continue
            uid, cat, attr, status, refs = m.groups()
            if cat not in CATEGORIES:
                problems.append(f"{uid}: category '{cat}' is not one of {sorted(CATEGORIES)}")
            if attr not in ATTRIBUTION:
                problems.append(f"{uid}: attribution '{attr}' is not one of {sorted(ATTRIBUTION)}")
            current = units.setdefault(uid, {"category": cat, "attribution": attr, "status": status,
                                             "refs": parse_refs(refs), "quotes": [], "line": refs})
        elif current is not None and line.strip().startswith(">"):
            q = QUOTE.match(line)
            if q:
                current["quotes"].append((q.group(1), q.group(2), (q.group(3) or "") + q.group(4)))
            else:
                problems.append(f"quote line does not parse (want: > \"words\" (SRC-n Tnnn)): {line.strip()[:80]}")
    return units, problems


def parse_refs(text):
    refs = []
    for src, tail in REF.findall(text):
        for part in re.split(r",\s*", tail.strip().rstrip(",")):
            if not part:
                continue
            m = re.match(r"(B\d+-)?T(\d{3,})(?:-T(\d{3,}))?$", part)
            if not m:
                continue
            prefix, a, b = m.group(1) or "", int(m.group(2)), int(m.group(3) or m.group(2))
            refs += [(src, f"{prefix}T{i:03d}") for i in range(a, b + 1)]
    return refs


def no_content(text):
    sec = re.search(r"^## No-content turns\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    out = set()
    for src, tail in REF.findall(sec.group(1) if sec else ""):
        for ref in parse_refs(f"{src} {tail}"):
            out.add(ref)
    return out


def cmd_check(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    fails, warns = [], []
    srcs = {}
    for folder, meta in existing_sources(project):
        for rev in meta["revisions"]:
            p = folder / rev["file"]
            if not p.is_file() or sha(p.read_bytes()) != rev["sha256"]:
                fails.append(f"{meta['id']}: raw revision {rev['file']} is missing or changed")
        srcs[meta["id"]] = {t["id"]: t for t in read_turns(folder)}
    dossier_path = sources_dir(project) / "dossier.md"
    if not dossier_path.is_file():
        print("FAIL   capture     no docs/project/sources/dossier.md yet")
        return 1
    text = dossier_path.read_text(encoding="utf-8")
    units, parse_problems = parse_dossier(text)
    fails += parse_problems
    cited = set()
    for uid, u in units.items():
        if not u["refs"]:
            fails.append(f"{uid}: no source reference")
        for src, tid in u["refs"]:
            if tid not in srcs.get(src, {}):
                fails.append(f"{uid}: {src} {tid} does not exist")
            cited.add((src, tid))
        sup = re.match(r"superseded by (S-\d+)", u["status"])
        if sup and sup.group(1) not in units:
            fails.append(f"{uid}: superseded by {sup.group(1)}, which is not a unit")
        owner_quotes = 0
        for words, src, tid in u["quotes"]:
            turn = srcs.get(src, {}).get(tid)
            if turn is None:
                fails.append(f"{uid}: quote cites {src} {tid}, which does not exist")
                continue
            if norm(words) not in norm(turn["text"]):
                fails.append(f"{uid}: quote is not verbatim in {src} {tid}: \"{words[:50]}\"")
                continue
            if turn["role"].startswith("owner"):
                owner_quotes += 1
                if turn["role"] == "owner (transcribed)" and u["attribution"] == "owner":
                    warns.append(f"{uid}: quotes a machine-transcribed turn ({src} {tid}); attribute it as transcribed")
            elif u["attribution"] in ("owner", "transcribed"):
                fails.append(f"{uid}: attributed to the owner but quotes the {turn['role']}'s turn ({src} {tid})")
        if u["attribution"] in ("owner", "owner-agreed", "transcribed") and owner_quotes == 0:
            fails.append(f"{uid}: {u['attribution']} unit with no verbatim quote from an owner turn")
    skip = no_content(text)
    for src, turns in srcs.items():
        for tid, t in turns.items():
            # Branch turns count too: an owner message that was edited keeps its first wording on a branch, and a
            # position changed by editing is still a position the dossier must record (usually as superseded).
            if (t["role"].startswith("owner") or t["role"] in COVERED_ROLES) and (src, tid) not in cited \
                    and (src, tid) not in skip:
                where = "an edited-away owner turn (branch)" if tid.startswith("B") else \
                    {"document": "a document section", "record": "a record (log window, commit, issue)"}.get(
                        t["role"], "an owner turn")
                fails.append(f"{src} {tid}: {where} no unit cites and not listed as no-content: "
                             f"\"{t['text'][:60]}\"")
    round_fails, round_warns = check_rounds(project, srcs, units)
    fails += round_fails
    warns += round_warns
    fails += check_audits(project, srcs, units)
    ids_file = sources_dir(project) / ".unit-ids.json"
    known = set(json.loads(ids_file.read_text())) if ids_file.is_file() else set()
    for uid in sorted(known - set(units)):
        fails.append(f"{uid} existed at an earlier check and is gone (mark it superseded instead)")
    for f in fails:
        print(f"FAIL   capture     {f}")
    for w in warns:
        print(f"WARN   capture     {w}")
    if not fails:
        ids_file.write_text(json.dumps(sorted(known | set(units))))
        owner_total = sum(1 for s in srcs.values() for t in s.values() if t["role"].startswith("owner"))
        other = sum(1 for s in srcs.values() for t in s.values() if t["role"] in COVERED_ROLES)
        print(f"PASS   capture     {len(units)} unit(s) cover {owner_total} owner turn(s) and {other} document section(s) "
              f"or record(s) across {len(srcs)} source(s), each read by an independent extraction and cleared by an "
              "independent audit")
    return 1 if fails else 0


# ---------- rounds: independent extraction against the dossier ----------

ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")
RESOLUTION = re.compile(r"^(added (S-\d{3,})|in (S-\d{3,}) \(.+\)|not a point \(.+\)|owner \(.+\))$")


def rounds_dir(project):
    return sources_dir(project) / "rounds"


def content_words(text):
    return set(re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]", norm(text).lower()))


def last_json_block(text):
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", flags=re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except ValueError:
            continue
    return None


def parse_rounds(project):
    out = []
    for f in sorted(rounds_dir(project).glob("round-*.md"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)):
        text = f.read_text(encoding="utf-8")
        covered = dict((sid, int(n)) for sid, n in re.findall(r"(SRC-\d+) \((\d+) turns\)",
                                                             (re.search(r"^Sources:(.*)$", text, re.M) or [None, ""])[1]))
        rows = []
        for line in text.split("## To settle", 1)[-1].splitlines() if "## To settle" in text else []:
            m = ROW.match(line.strip())
            if m:
                cells = [c.strip() for c in m.group(2).split("|")]
                rows.append({"n": int(m.group(1)), "refs": parse_refs(cells[1] if len(cells) > 1 else ""),
                             "resolution": cells[-1]})
        out.append({"file": f, "n": int(re.sub(r"\D", "", f.stem)), "sources": covered, "rows": rows})
    return out


def cmd_reconcile(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project, result = Path(argv[0]).resolve(), Path(argv[1])
    data = last_json_block(result.read_text(encoding="utf-8")) if result.is_file() else None
    if not data or not isinstance(data.get("points"), list):
        print(f"FAIL   capture     {result}: no extraction JSON with a points list (cold reader, extraction mode)")
        return 1
    pack = result.with_name(result.name.replace(".result.md", ".pack.md"))
    read = sorted(set(re.findall(r"sources/(SRC-\d+)-", pack.read_text(encoding="utf-8")))) if pack.is_file() else []
    if not read:
        print(f"FAIL   capture     {pack}: the extraction's pack names no source, so its coverage cannot be credited")
        return 1
    turns = {meta["id"]: len(read_turns(folder)) for folder, meta in existing_sources(project)}
    dossier = sources_dir(project) / "dossier.md"
    units, _ = parse_dossier(dossier.read_text(encoding="utf-8")) if dossier.is_file() else ({}, [])
    missing = []
    for pt in data["points"]:
        refs = set(parse_refs(" ".join(pt.get("refs") or [])))
        quote = pt.get("quote") or pt.get("point") or ""
        words = content_words(quote)
        carried = False
        for u in units.values():
            if not refs & set(u["refs"]):
                continue
            unit_words = content_words(u["line"] + " " + " ".join(q[0] for q in u["quotes"]))
            quoted = norm(quote) and any(norm(quote) in norm(q[0]) or norm(q[0]) in norm(quote) for q in u["quotes"])
            if quoted or not words or len(words & unit_words) / len(words) >= 0.5:
                carried = True
                break
        if not carried:
            missing.append(pt)
    rounds_dir(project).mkdir(parents=True, exist_ok=True)
    n = max((r["n"] for r in parse_rounds(project)), default=0) + 1
    esc = lambda x: str(x).replace("|", "/").replace("\n", " ")
    lines = [f"# Round {n} · {now()} · independent extraction", "",
             "Sources: " + ", ".join(f"{sid} ({turns.get(sid, 0)} turns)" for sid in read),
             f"Extraction: {result}",
             f"Points: {len(data['points'])} · carried by the dossier: {len(data['points']) - len(missing)} · "
             f"to settle: {len(missing)}", "",
             "Settle each row: added S-<nnn> (a unit now carries it), in S-<nnn> (<why the match missed it>), not a "
             "point (<why>), or owner (<the question for the owner>).", "", "## To settle", "",
             "| # | Point | Refs | Quote | Resolution |", "|---|---|---|---|---|"]
    lines += [f"| {i} | {esc(pt.get('point', ''))[:160]} | {esc(', '.join(pt.get('refs') or []))} | "
              f"\"{esc(pt.get('quote', ''))[:200]}\" | open |" for i, pt in enumerate(missing, 1)]
    out = rounds_dir(project) / f"round-{n}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"round {n}: {len(data['points'])} point(s) from an independent extraction of {', '.join(read)}; "
          f"{len(missing)} not carried by the dossier, to settle in {out}")
    return 0


def check_rounds(project, srcs, units):
    fails, warns = [], []
    rounds = parse_rounds(project)
    for r in rounds:
        for row in r["rows"]:
            m = RESOLUTION.match(row["resolution"])
            if not m:
                fails.append(f"round {r['n']} row {row['n']} is not settled ({row['resolution'][:40] or 'empty'}): "
                             "added S-<nnn>, in S-<nnn> (...), not a point (...), or owner (...)")
            elif (m.group(2) or m.group(3)) and (m.group(2) or m.group(3)) not in units:
                fails.append(f"round {r['n']} row {row['n']} names {m.group(2) or m.group(3)}, which is not a unit")
    coverable = {sid for sid, turns in srcs.items()
                 if any(t["role"].startswith("owner") or t["role"] in COVERED_ROLES for t in turns.values())}
    for sid in sorted(coverable, key=lambda x: int(x.split("-")[1])):
        reading = [r for r in rounds if sid in r["sources"]]
        if not reading:
            fails.append(f"{sid} has not been read by an independent extraction (a cold reader in extraction mode, "
                         "then capture.py reconcile)")
            continue
        latest = reading[-1]
        size = len(srcs[sid])  # every turn, branches included, as reconcile counted them
        if size > latest["sources"][sid]:
            fails.append(f"{sid} grew after its last independent extraction (round {latest['n']}); extract it again")
        # One extraction per source: what the dossier still lacks or bends is the audit's to find (check_audits).
    return fails, warns


def turn_ranges(tids):
    """T001, T002, T003, T007 -> T001-T003, T007 (branch turns listed one by one)."""
    plain = sorted(int(t[1:]) for t in tids if re.match(r"^T\d+$", t))
    out, i = [], 0
    while i < len(plain):
        j = i
        while j + 1 < len(plain) and plain[j + 1] == plain[j] + 1:
            j += 1
        out.append(f"T{plain[i]:03d}" + (f"-T{plain[j]:03d}" if j > i else ""))
        i = j + 1
    return out + sorted(t for t in tids if not re.match(r"^T\d+$", t))


def pack_sources(result):
    pack = result.with_name(result.name.replace(".result.md", ".pack.md"))
    return sorted(set(re.findall(r"sources/(SRC-\d+)-", pack.read_text(encoding="utf-8")))) if pack.is_file() else []


def cmd_draft(argv):
    """An independent extraction becomes dossier units: the reader drafts, the builder edits."""
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project, result = Path(argv[0]).resolve(), Path(argv[1])
    data = last_json_block(result.read_text(encoding="utf-8")) if result.is_file() else None
    if not data or not isinstance(data.get("points"), list):
        print(f"FAIL   capture     {result}: no extraction JSON with a points list (cold reader, extraction mode)")
        return 1
    read = pack_sources(result)
    if not read:
        print(f"FAIL   capture     {result}: its pack names no source, so its coverage cannot be credited")
        return 1
    srcs = {meta["id"]: {t["id"]: t for t in read_turns(folder)} for folder, meta in existing_sources(project)}
    path = sources_dir(project) / "dossier.md"
    if not path.is_file():
        path.write_text(f"# Dossier: {project.name}\nStatus: exploring\nSources: see index.md\n\n## Where it stands\n"
                        "(to write once the sources are drafted)\n\n## Units\n\n## Open questions\n\n## Tensions\n\n"
                        "## No-content turns\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    units, _ = parse_dossier(text)
    ids_file = sources_dir(project) / ".unit-ids.json"
    taken = set(units) | (set(json.loads(ids_file.read_text())) if ids_file.is_file() else set())
    nxt = max((int(u[2:]) for u in taken), default=0) + 1
    good, bad, ids = [], [], {}
    for i, pt in enumerate(data["points"], 1):
        refs = parse_refs(" ".join(pt.get("refs") or []))
        quote = norm(pt.get("quote") or "")
        why = None
        if not refs or any(tid not in srcs.get(src, {}) for src, tid in refs):
            why = "cites a unit that does not exist"
        qref = next(((src, tid) for src, tid in refs if quote and quote in norm(srcs[src][tid]["text"])), None) \
            if not why else None
        if not why and not qref:
            why = "the quote is not verbatim in the unit it cites"
        attr = pt.get("attribution") if pt.get("attribution") in ATTRIBUTION else None
        if not why:
            role = srcs[qref[0]][qref[1]]["role"]
            attr = attr or ("owner" if role.startswith("owner") else role if role in ATTRIBUTION else "document")
            if attr == "owner" and role == "owner (transcribed)":
                attr = "transcribed"
            if attr in ("owner", "owner-agreed", "transcribed") and not role.startswith("owner"):
                why = f"attributed to the owner but quotes the {role}'s turn"
        if why:
            bad.append((i, pt, why))
            continue
        ids[i] = f"S-{nxt:03d}"
        nxt += 1
        good.append((i, pt, attr, qref, refs))
    blocks = []
    for i, pt, attr, qref, refs in good:
        status = pt.get("status") if pt.get("status") in ("current", "open", "not taken up", "rejected") else "current"
        if pt.get("status") == "superseded" and ids.get(pt.get("superseded_by")):
            status = f"superseded by {ids[pt['superseded_by']]}"
        by_src = {}
        for src, tid in refs:
            by_src.setdefault(src, set()).add(tid)
        refstr = "; ".join(f"{src} {', '.join(turn_ranges(t))}" for src, t in sorted(by_src.items()))
        cat = pt.get("category") if pt.get("category") in CATEGORIES else "other"
        blocks.append(f"- {ids[i]} · {cat} · {attr} · {status} · {refstr}\n  {norm(pt.get('point') or '')}\n"
                      f"  > \"{norm(pt.get('quote') or '')}\" ({qref[0]} {qref[1]})")
    m = re.search(r"^## Units[ \t]*\n", text, re.M)
    nxt_sec = re.search(r"^## ", text[m.end():], re.M) if m else None
    cut = m.end() + (nxt_sec.start() if nxt_sec else len(text) - m.end()) if m else len(text)
    body = text[:cut].rstrip("\n") + ("\n" + "\n".join(blocks) if blocks else "") + "\n\n" + text[cut:]
    # Turns the reader read and drew nothing load-bearing from: read, nothing to keep.
    new_units, _ = parse_dossier(body)
    cited = {r for u in new_units.values() for r in u["refs"]} | no_content(body)
    lines = []
    for sid in read:
        rest = [tid for tid, t in srcs.get(sid, {}).items()
                if (t["role"].startswith("owner") or t["role"] in COVERED_ROLES) and (sid, tid) not in cited]
        if rest:
            lines.append(f"{sid} {', '.join(turn_ranges(rest))}")
    if lines:
        if not re.search(r"^## No-content turns[ \t]*$", body, re.M):
            body = body.rstrip("\n") + "\n\n## No-content turns\n"
        body = body.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    path.write_text(body, encoding="utf-8")
    rounds_dir(project).mkdir(parents=True, exist_ok=True)
    n = max((r["n"] for r in parse_rounds(project)), default=0) + 1
    esc = lambda x: str(x).replace("|", "/").replace("\n", " ")
    rec = [f"# Round {n} · {now()} · independent extraction, drafted into the dossier", "",
           "Sources: " + ", ".join(f"{sid} ({len(srcs.get(sid, {}))} turns)" for sid in read),
           f"Extraction: {result}",
           f"Points: {len(data['points'])} · drafted: {len(good)} · to settle: {len(bad)}", "",
           "Settle each row: added S-<nnn> (a unit now carries it), in S-<nnn> (<why>), not a point (<why>), or owner "
           "(<the question>).", "", "## To settle", "", "| # | Point | Refs | Quote | Resolution |", "|---|---|---|---|---|"]
    rec += [f"| {i} | {esc(pt.get('point', ''))[:160]} ({why}) | {esc(', '.join(pt.get('refs') or []))} | "
            f"\"{esc(pt.get('quote', ''))[:200]}\" | open |" for i, pt, why in bad]
    (rounds_dir(project) / f"round-{n}.md").write_text("\n".join(rec) + "\n", encoding="utf-8")
    print(f"draft: {len(good)} unit(s) from {len(data['points'])} point(s) of {', '.join(read)}; {len(bad)} to settle in "
          f"rounds/round-{n}.md; next, edit the dossier (merge, link supersessions, check attribution), then audit")
    return 0


AUDIT_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")
AUDIT_RESOLUTION = re.compile(r"^(fixed (S-\d{3,})(?: \(.+\))?|not an issue \(.+\)|owner \(.+\))$")


def audits_dir(project):
    return sources_dir(project) / "audits"


def cmd_audit(argv):
    """An independent fidelity read of some sources against the units citing them, recorded to be settled."""
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project, result = Path(argv[0]).resolve(), Path(argv[1])
    data = last_json_block(result.read_text(encoding="utf-8")) if result.is_file() else None
    if not data or not isinstance(data.get("fidelity"), list):
        print(f"FAIL   capture     {result}: no fidelity JSON (cold reader, fidelity mode)")
        return 1
    read = pack_sources(result)
    if not read:
        print(f"FAIL   capture     {result}: its pack names no source, so the audit cannot be credited")
        return 1
    turns = {meta["id"]: len(read_turns(folder)) for folder, meta in existing_sources(project)}
    items = data["fidelity"]
    material = [i for i in items if str(i.get("severity", "")).lower() == "material"]
    minor = [i for i in items if i not in material]
    audits_dir(project).mkdir(parents=True, exist_ok=True)
    n = max((a["n"] for a in parse_audits(project)), default=0) + 1
    esc = lambda x: str(x).replace("|", "/").replace("\n", " ")
    row = lambda k, i: (f"| {k} | {esc(i.get('kind', ''))} | {esc(i.get('turn', ''))} | \"{esc(i.get('quote', ''))[:160]}\" | "
                        f"{esc(i.get('unit', ''))} | {esc(i.get('dossier_says', ''))[:160]} |")
    lines = [f"# Audit {n} · {now()} · independent fidelity read", "",
             "Sources: " + ", ".join(f"{sid} ({turns.get(sid, 0)} turns)" for sid in read), f"Read: {result}",
             f"Material: {len(material)} · minor: {len(minor)}", "",
             "Settle each material row: fixed S-<nnn> (<what changed>), not an issue (<why>), or owner (<the question>).",
             "", "## Material", "", "| # | Kind | Turn | Quote | Unit | Dossier says | Resolution |",
             "|---|---|---|---|---|---|---|"]
    lines += [row(k, i) + " open |" for k, i in enumerate(material, 1)]
    lines += ["", "## Minor (listed; fixed when it costs little, no settling needed)", "",
              "| # | Kind | Turn | Quote | Unit | Dossier says |", "|---|---|---|---|---|---|"]
    lines += [row(k, i) for k, i in enumerate(minor, 1)]
    out = audits_dir(project) / f"audit-{n}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"audit {n}: {len(material)} material and {len(minor)} minor problem(s) in {', '.join(read)} -> {out}")
    return 0


def parse_audits(project):
    out = []
    d = audits_dir(project)
    for f in sorted(d.glob("audit-*.md"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)) if d.is_dir() else []:
        text = f.read_text(encoding="utf-8")
        covered = dict((sid, int(k)) for sid, k in re.findall(r"(SRC-\d+) \((\d+) turns\)",
                                                             (re.search(r"^Sources:(.*)$", text, re.M) or [None, ""])[1]))
        rows = []
        sec = re.search(r"^## Material\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
        for line in (sec.group(1) if sec else "").splitlines():
            m = AUDIT_ROW.match(line.strip())
            if m:
                cells = [c.strip() for c in m.group(2).split("|")]
                rows.append({"n": int(m.group(1)), "turn": cells[1] if len(cells) > 1 else "",
                             "resolution": cells[-1]})
        out.append({"n": int(re.sub(r"\D", "", f.stem)), "sources": covered, "material": rows})
    return out


def check_audits(project, srcs, units):
    fails = []
    audits = parse_audits(project)
    for a in audits:
        for row in a["material"]:
            m = AUDIT_RESOLUTION.match(row["resolution"])
            if not m:
                fails.append(f"audit {a['n']} row {row['n']} is not settled ({row['resolution'][:40] or 'empty'}): fixed "
                             "S-<nnn> (...), not an issue (...), or owner (...)")
            elif m.group(2) and m.group(2) not in units:
                fails.append(f"audit {a['n']} row {row['n']} names {m.group(2)}, which is not a unit")
    auditable = {sid for sid, turns in srcs.items()
                 if any(t["role"].startswith("owner") or t["role"] in COVERED_ROLES for t in turns.values())}
    for sid in sorted(auditable, key=lambda x: int(x.split("-")[1])):
        reading = [a for a in audits if sid in a["sources"]]
        if not reading:
            fails.append(f"{sid} has not been audited (cold reader in fidelity mode on it, then capture.py audit)")
            continue
        latest = reading[-1]
        if len(srcs[sid]) > latest["sources"][sid]:
            fails.append(f"{sid} grew after its last audit (audit {latest['n']}); audit it again")
            continue
        own = [r for r in latest["material"] if sid in r["turn"] or not re.search(r"SRC-\d+", r["turn"])]
        if own:
            how = (" Audits keep finding material problems here: audit smaller portions, or ask the owner what the "
                   "source means." if len(reading) > AUDIT_METHOD_AFTER else "")
            fails.append(f"{sid}: its latest audit (audit {latest['n']}) found {len(own)} material problem(s); once "
                         f"settled, audit it again with --previous, until an audit finds none.{how}")
    return fails


CLOSURE_STATE = re.compile(r"^(intent \(.+\)|brief \(.+\)|interfaces \(.+\)|milestone M\d+|named non-goal \(.+\)|"
                           r"unknown U-\d+|not adopted \(.+\))$", re.I)


def cmd_closure(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    project = Path(argv[0]).resolve()
    dossier = sources_dir(project) / "dossier.md"
    brief = project / "docs/project/brief.md"
    if not dossier.is_file() or not brief.is_file():
        print("FAIL   closure     needs docs/project/sources/dossier.md and docs/project/brief.md")
        return 1
    units, _ = parse_dossier(dossier.read_text(encoding="utf-8"))
    sec = re.search(r"^## Source closure\s*$(.*?)(?=^## |\Z)", brief.read_text(encoding="utf-8"), flags=re.M | re.S)
    rows = {}
    for line in (sec.group(1) if sec else "").splitlines():
        m = re.match(r"^\|\s*(S-\d+)\s*\|(.*)\|\s*$", line.strip())
        if m:
            rows[m.group(1)] = [c.strip() for c in m.group(2).split("|")][-1]
    fails = []
    for uid, u in units.items():
        if u["status"].startswith("superseded") or u["category"] in ("term", "rejected"):
            continue
        where = rows.get(uid)
        if where is None:
            fails.append(f"{uid} ({u['category']}) has no row in brief.md '## Source closure'")
        elif not CLOSURE_STATE.match(where):
            fails.append(f"{uid}: '{where[:60]}' is not intent (...), brief (...), milestone M<k>, named non-goal "
                         "(...), unknown U-<nn>, or not adopted (...)")
    for f in fails:
        print(f"FAIL   closure     {f}")
    if not fails:
        print(f"PASS   closure     every live unit ({len([u for u in units.values() if not u['status'].startswith('superseded')])}) lands in the plan")
    return 1 if fails else 0


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    cmd = {"add": cmd_add, "list": cmd_list, "check": cmd_check, "closure": cmd_closure,
           "reconcile": cmd_reconcile, "draft": cmd_draft, "audit": cmd_audit}.get(argv[0])
    if cmd is None:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
