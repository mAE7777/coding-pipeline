#!/usr/bin/env python3
"""Keep idea conversations and documents whole: import them verbatim, and check the organized dossier
against them.

Usage:
  capture.py add <project> <input> [--kind auto|chatgpt-export|chat-text|doc|audio] [--chat <id or title>]
                 [--title <title>] [--speaker owner|document] [--language <code>] [--model <whisper model>]
  capture.py list <conversations.json>          the conversations in a ChatGPT export
  capture.py check <project>                    coverage, quotes, attribution, references, stable IDs
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
A second import of the same conversation (same conversation id, or pasted text whose turns begin with an
existing source's turns) appends only the new turns to that source, keeping every earlier turn ID.

check FAILs when: a raw file's sha256 no longer matches; an owner turn on a main line is neither cited by a
unit nor listed under "## No-content turns"; a quote is not verbatim in the turn it cites, or an owner or
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
ATTRIBUTION = {"owner", "owner-agreed", "assistant", "document", "transcribed"}
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
    if path.suffix.lower() in (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm"):
        return "audio"
    if path.suffix.lower() == ".json":
        return "chatgpt-export"
    text = path.read_text(encoding="utf-8", errors="replace")
    return "chat-text" if MARK.search(text) else "doc"


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
    if not src.is_file():
        print(f"capture: no such file: {src}", file=sys.stderr)
        return 2
    kind = opts.get("--kind", "auto")
    kind = detect_kind(src) if kind == "auto" else kind
    raw = src.read_bytes()
    conversation, title, branches, skipped, notes = None, opts.get("--title") or src.stem, [], 0, []
    if kind == "chatgpt-export":
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
    if target is None:
        n = len(existing_sources(project)) + 1
        meta = {"id": f"SRC-{n}", "title": title, "kind": kind, "conversation": conversation, "revisions": []}
        target = sources_dir(project) / f"SRC-{n}-{slug(title)}"
        all_turns = number(turns)
    else:
        main_old = [t for t in old if not t["id"].startswith("B")]
        known_nodes = {t["node"] for t in old if t.get("node")}
        if conversation:
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
                                             "refs": parse_refs(refs), "quotes": []})
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
            if t["role"].startswith("owner") and (src, tid) not in cited and (src, tid) not in skip:
                where = "an edited-away owner turn (branch)" if tid.startswith("B") else "an owner turn"
                fails.append(f"{src} {tid}: {where} no unit cites and not listed as no-content: "
                             f"\"{t['text'][:60]}\"")
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
        print(f"PASS   capture     {len(units)} unit(s) cover {owner_total} owner turn(s) across {len(srcs)} source(s)")
    return 1 if fails else 0


CLOSURE_STATE = re.compile(r"^(intent \(.+\)|brief \(.+\)|milestone M\d+|named non-goal \(.+\)|unknown U-\d+|"
                           r"not adopted \(.+\))$", re.I)


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
    cmd = {"add": cmd_add, "list": cmd_list, "check": cmd_check, "closure": cmd_closure}.get(argv[0])
    if cmd is None:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
