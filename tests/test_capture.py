"""Tests for capture.py: lossless import (ChatGPT export, pasted chat, documents), re-import, and the checks."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "skills/_shared/scripts/capture.py"


def node(nid, parent, children, role=None, text=None, parts=None, hidden=False, t=1790000000):
    msg = None
    if role:
        content = {"content_type": "text", "parts": parts if parts is not None else [text]}
        if parts is not None and any(isinstance(p, dict) for p in parts):
            content["content_type"] = "multimodal_text"
        msg = {"author": {"role": role}, "content": content, "create_time": t,
               "metadata": {"is_visually_hidden_from_conversation": hidden}}
    return nid, {"id": nid, "parent": parent, "children": children, "message": msg}


def export(extra_turn=False):
    nodes = dict([
        node("root", None, ["sys"]),
        node("sys", "root", ["u1"], "system", "You are ChatGPT", hidden=True),
        node("u1", "sys", ["a1"], "user", "I keep losing grocery lists between my phone and my partner's phone."),
        node("a1", "u1", ["u2", "u2b"], "assistant", "You could build a shared list that syncs instantly."),
        node("u2b", "a1", ["a2b"], "user", "Actually, what about a fridge magnet?"),
        node("a2b", "u2b", [], "assistant", "A magnet cannot sync."),
        node("u2", "a1", ["a2"], "user", None, parts=[{"content_type": "audio_transcription",
                                                        "text": "yes, a shared list, and deleting must reach both phones"},
                                                       {"content_type": "image_asset_pointer", "asset_pointer": "x"}]),
        node("a2", "u2", ["u3"] if extra_turn else [], "assistant", "Got it: deletions propagate."),
    ])
    current = "a2"
    if extra_turn:
        nodes.update(dict([node("u3", "a2", ["a3"], "user", "and it must work offline too"),
                           node("a3", "u3", [], "assistant", "Offline queue noted.")]))
        current = "a3"
    return [{"conversation_id": "conv-123", "title": "Grocery brainstorm", "create_time": 1790000000,
             "update_time": 1790000100, "mapping": nodes, "current_node": current},
            {"conversation_id": "conv-999", "title": "Unrelated", "mapping": {}, "current_node": None}]


DOSSIER = """# Dossier

## Units
- S-001 · problem · owner · current · SRC-1 T001
  Lists drift between two phones.
  > "I keep losing grocery lists" (SRC-1 T001)
- S-002 · product · owner-agreed · current · SRC-1 T002-T003
  A shared list that syncs; deletions reach both phones.
  > "deleting must reach both phones" (SRC-1 T003)
- S-003 · implementation · assistant · not taken up · SRC-1 T004
  Propagate deletions.
- S-004 · product · owner · superseded by S-002 · SRC-1 B1-T001
  A fridge magnet, raised in the wording the owner then edited away.
  > "Actually, what about a fridge magnet?" (SRC-1 B1-T001)

## No-content turns
none
"""


def tiny_pdf(pages):
    """A valid PDF with one line of text per page (Helvetica), built by hand so the test needs no PDF library."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {content} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = "%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out.encode()))
        out += f"{i} 0 obj\n{body}\nendobj\n"
    xref = len(out.encode())
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode()


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.project = self.d / "proj"
        self.project.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def cap(self, *args):
        return subprocess.run([sys.executable, str(CAP), *args], capture_output=True, text=True)

    def extract(self, points, sources=("SRC-1",), n=1):
        """Stand in for the isolated reader in extraction mode: its pack names the sources it read."""
        d = self.project / f".evidence/capture/extract-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "cold-reader.pack.md").write_text("".join(f"## Document: docs/project/sources/{sid}-x/transcript.md\n"
                                                       for sid in sources))
        (d / "cold-reader.result.md").write_text("Read.\n```json\n" + json.dumps({"mode": "extraction",
                                                                                 "points": points}) + "\n```\n")
        out = self.cap("reconcile", str(self.project), str(d / "cold-reader.result.md"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def audit(self, items, sources=("SRC-1",), n=1):
        """Stand in for the isolated reader in fidelity mode: its pack names the transcripts it read."""
        d = self.project / f".evidence/capture/audit-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "cold-reader.pack.md").write_text("".join(f"## Transcript: docs/project/sources/{sid}-x/transcript.md\n"
                                                       for sid in sources))
        (d / "cold-reader.result.md").write_text("Read.\n```json\n" + json.dumps({"mode": "fidelity",
                                                                                 "fidelity": items}) + "\n```\n")
        out = self.cap("audit", str(self.project), str(d / "cold-reader.result.md"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def settle_audit(self, n, row, resolution):
        f = self.project / f"docs/project/sources/audits/audit-{n}.md"
        lines = f.read_text().splitlines()
        lines = [l[:l.rstrip().rstrip("|").rstrip().rfind("|") + 1] + f" {resolution} |"
                 if l.startswith(f"| {row} |") and l.rstrip().endswith("open |") else l for l in lines]
        f.write_text("\n".join(lines) + "\n")

    DROPPED = {"kind": "dropped", "turn": "SRC-1 T003", "quote": "and an image of the list", "unit": "",
               "dossier_says": "nothing", "severity": "material"}
    WORDING = {"kind": "distorted", "turn": "SRC-1 T001", "quote": "I keep losing", "unit": "S-001",
               "dossier_says": "drift", "severity": "minor"}

    def settle(self, n, row, resolution):
        f = self.project / f"docs/project/sources/rounds/round-{n}.md"
        lines = f.read_text().splitlines()
        lines = [l[:l.rstrip().rstrip("|").rstrip().rfind("|") + 1] + f" {resolution} |"
                 if l.startswith(f"| {row} |") else l for l in lines]
        f.write_text("\n".join(lines) + "\n")

    CARRIED = [{"refs": ["SRC-1 T001"], "quote": "I keep losing grocery lists", "point": "lists get lost"},
               {"refs": ["SRC-1 T003"], "quote": "deleting must reach both phones", "point": "deletion syncs"}]

    def add_export(self, extra=False, name="conversations.json"):
        f = self.d / name
        f.write_text(json.dumps(export(extra)))
        return self.cap("add", str(self.project), str(f), "--chat", "conv-123")

    def turns(self):
        folder = next((self.project / "docs/project/sources").glob("SRC-1-*"))
        return [json.loads(l) for l in (folder / "turns.jsonl").read_text().splitlines()], folder

    def test_a_pasted_reply_that_quotes_user_lines_stays_one_reply(self):
        paste = self.d / "chat.txt"
        paste.write_text("You said:\nwrite a cocktail menu dialogue\n\nChatGPT said:\nHere is a sample.\n"
                         "User: make me something sweet but not too strong\nBartender: a spritz, then.\n\n"
                         "You said:\nnice, keep the spritz\n")
        out = self.cap("add", str(self.project), str(paste), "--kind", "chat-text")
        self.assertEqual(out.returncode, 0, out.stderr)
        turns, _ = self.turns()
        owner = [t["text"] for t in turns if t["role"] == "owner"]
        self.assertEqual(owner, ["write a cocktail menu dialogue", "nice, keep the spritz"],
                         "the sample dialogue inside the reply is the assistant's text, not the owner's")
        self.assertNotIn("WARN", out.stdout)

    def test_short_markers_only_import_with_a_warning(self):
        paste = self.d / "chat2.txt"
        paste.write_text("Me: a list app\nAI: sure\n")
        out = self.cap("add", str(self.project), str(paste), "--kind", "chat-text")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("speaker breaks were read from short markers", out.stdout)

    def test_an_edited_away_owner_turn_must_be_recorded(self):
        self.add_export()
        self.write_dossier(DOSSIER.split("- S-004")[0] + "\n## No-content turns\nnone\n")
        out = self.cap("check", str(self.project))
        self.assertEqual(out.returncode, 1)
        self.assertIn("SRC-1 B1-T001: an edited-away owner turn (branch)", out.stdout)

    def test_export_import_is_lossless(self):
        out = self.add_export()
        self.assertEqual(out.returncode, 0, out.stderr)
        turns, folder = self.turns()
        main = [t for t in turns if not t["id"].startswith("B")]
        self.assertEqual([t["role"] for t in main], ["owner", "assistant", "owner (transcribed)", "assistant"])
        self.assertIn("deleting must reach both phones", main[2]["text"], "voice transcription kept")
        self.assertEqual(main[2]["role"], "owner (transcribed)", "a voice turn is not a verbatim record")
        self.assertIn("image asset pointer", main[2]["text"], "a part without text is named, not dropped")
        branch = [t for t in turns if t["id"].startswith("B")]
        self.assertTrue(any("fridge magnet" in t["text"] for t in branch), "the abandoned branch is kept")
        meta = json.loads((folder / "meta.json").read_text())
        self.assertEqual(meta["skipped"], 1, "the hidden system message is counted")
        self.assertTrue((folder / "transcript.md").read_text().count("### T00") >= 4)

    def test_ambiguous_export_needs_a_choice(self):
        f = self.d / "c.json"
        f.write_text(json.dumps(export()))
        out = self.cap("add", str(self.project), str(f))
        self.assertEqual(out.returncode, 1)
        self.assertIn("--chat", out.stderr)

    def test_reimport_appends_only_new_turns(self):
        self.add_export()
        out = self.add_export(extra=True, name="later.json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("2 turn(s) added", out.stdout)
        turns, folder = self.turns()
        ids = [t["id"] for t in turns if not t["id"].startswith("B")]
        self.assertEqual(ids, ["T001", "T002", "T003", "T004", "T005", "T006"])
        self.assertEqual(len(json.loads((folder / "meta.json").read_text())["revisions"]), 2)
        self.assertEqual(len(list((self.project / "docs/project/sources").glob("SRC-*"))), 1)

    def test_pasted_chat_and_extension(self):
        f = self.d / "paste.txt"
        f.write_text("You said:\nI want a list app\nChatGPT said:\nWhat kind?\nYou said:\nshared\n")
        self.assertEqual(self.cap("add", str(self.project), str(f)).returncode, 0)
        f.write_text("You said:\nI want a list app\nChatGPT said:\nWhat kind?\nYou said:\nshared\n"
                     "ChatGPT said:\nOk.\nYou said:\nwith offline mode\n")
        out = self.cap("add", str(self.project), str(f))
        self.assertIn("2 turn(s) added", out.stdout)
        turns, _ = self.turns()
        self.assertEqual(turns[-1]["text"], "with offline mode")

    def test_document_import(self):
        f = self.d / "notes.md"
        f.write_text("# Vision\nOne list.\n\n# Risks\nSync conflicts.\n")
        self.assertEqual(self.cap("add", str(self.project), str(f), "--speaker", "owner").returncode, 0)
        turns, _ = self.turns()
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["role"], "owner")

    def write_dossier(self, text):
        (self.project / "docs/project/sources/dossier.md").write_text(text)

    def test_check_passes_a_faithful_dossier(self):
        self.add_export()
        self.write_dossier(DOSSIER)
        out = self.cap("check", str(self.project))
        self.assertEqual(out.returncode, 1, "no independent extraction has read the source yet")
        self.assertIn("SRC-1 has not been read by an independent extraction", out.stdout)
        self.assertIn("to settle: 0", self.extract(self.CARRIED) + (self.project /
                      "docs/project/sources/rounds/round-1.md").read_text())
        out = self.cap("check", str(self.project))
        self.assertIn("SRC-1 has not been audited", out.stdout, "an extraction alone does not clear a source")
        self.audit([self.WORDING])
        out = self.cap("check", str(self.project))
        self.assertEqual(out.returncode, 0, out.stdout + "(a minor problem is listed, never a blocker)")

    def test_audits_run_until_one_finds_nothing_material(self):
        self.add_export()
        self.write_dossier(DOSSIER)
        self.extract(self.CARRIED)
        self.assertIn("1 material", self.audit([self.DROPPED, self.WORDING]))
        out = self.cap("check", str(self.project))
        self.assertIn("audit 1 row 1 is not settled", out.stdout)
        self.write_dossier(DOSSIER.replace("## No-content turns", "- S-005 · product · owner · open · SRC-1 T003\n"
                                           "  The owner attached a picture of the list.\n"
                                           "  > \"deleting must reach both phones\" (SRC-1 T003)\n\n## No-content turns"))
        self.settle_audit(1, 1, "fixed S-005 (the photo is a unit now)")
        out = self.cap("check", str(self.project))
        self.assertIn("found 1 material problem(s); once settled, audit it again", out.stdout,
                      "a settled problem is proven fixed only by the next audit")
        self.audit([self.WORDING], n=2)
        self.assertEqual(self.cap("check", str(self.project)).returncode, 0, "an audit with nothing material ends it")
        for n in (3, 4, 5):
            self.audit([dict(self.DROPPED, quote=f"missed point {n}")], n=n)
            self.settle_audit(n, 1, "not an issue (the transcript repeats S-002)")
        out = self.cap("check", str(self.project))
        self.assertIn("audit smaller portions", out.stdout, "a count never ends the checking; it changes how it is done")
        self.assertEqual(out.returncode, 1)

    def test_the_reader_drafts_the_dossier(self):
        self.add_export()
        self.write_dossier("# Dossier\n\n## Units\n- S-007 · other · owner · superseded by S-008 · SRC-1 T001\n"
                           "  An earlier reading, kept.\n  > \"I keep losing grocery lists\" (SRC-1 T001)\n\n"
                           "## No-content turns\n")
        points = [
            {"refs": ["SRC-1 T001"], "quote": "I keep losing grocery lists", "point": "lists get lost",
             "category": "problem", "attribution": "owner", "status": "current"},
            {"refs": ["SRC-1 T002"], "quote": "build a shared list that syncs", "point": "a synced shared list",
             "category": "product", "attribution": "assistant", "status": "not taken up"},
            {"refs": ["SRC-1 T003"], "quote": "deleting must reach both phones", "point": "deletion reaches both",
             "category": "constraint", "attribution": "owner", "status": "current"},
            {"refs": ["SRC-1 B1-T001"], "quote": "Actually, what about a fridge magnet?", "point": "a fridge magnet",
             "category": "product", "attribution": "owner", "status": "superseded", "superseded_by": 3},
            {"refs": ["SRC-1 T001"], "quote": "words the owner never typed", "point": "an invented quote"},
            {"refs": ["SRC-1 T002"], "quote": "build a shared list that syncs", "point": "claimed as the owner's",
             "attribution": "owner"},
        ]
        out = self.extract_draft(points)
        self.assertIn("draft: 4 unit(s) from 6 point(s)", out)
        dossier = (self.project / "docs/project/sources/dossier.md").read_text()
        self.assertIn("- S-008 · problem · owner · current · SRC-1 T001", dossier, "a retired ID is never reused")
        self.assertIn("- S-009 · product · assistant · not taken up · SRC-1 T002", dossier)
        self.assertIn("- S-011 · product · owner · superseded by S-010 · SRC-1 B1-T001", dossier)
        self.assertNotIn("an invented quote", dossier)
        rnd = (self.project / "docs/project/sources/rounds/round-1.md").read_text()
        self.assertIn("the quote is not verbatim", rnd)
        self.assertIn("attributed to the owner but quotes the assistant's turn", rnd)
        units = [l for l in dossier.splitlines() if l.startswith("- S-")]
        self.assertEqual(len(units), 5, "the four drafted and the one already there")
        self.settle(1, 5, "not a point (the reader misquoted T001, which S-008 carries)")
        self.settle(1, 6, "in S-009 (the assistant's proposal)")
        self.audit([])
        out = self.cap("check", str(self.project))
        self.assertEqual(out.returncode, 0, out.stdout)

    def extract_draft(self, points, n=1):
        d = self.project / f".evidence/capture/extract-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "cold-reader.pack.md").write_text("## Document: docs/project/sources/SRC-1-x/transcript.md\n")
        (d / "cold-reader.result.md").write_text("Read.\n```json\n" + json.dumps({"mode": "extraction",
                                                                                 "points": points}) + "\n```\n")
        out = self.cap("draft", str(self.project), str(d / "cold-reader.result.md"))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        return out.stdout

    def test_a_source_that_grew_is_extracted_again(self):
        self.add_export()
        self.write_dossier(DOSSIER)
        self.extract(self.CARRIED)
        self.add_export(extra=True)
        self.write_dossier(DOSSIER.replace("## No-content turns\nnone", "## No-content turns\nSRC-1 T005-T006"))
        self.assertIn("grew after its last independent extraction", self.cap("check", str(self.project)).stdout)

    def test_a_folder_of_documents_logs_and_office_files(self):
        docs = self.d / "pile"
        (docs / "notes").mkdir(parents=True)
        (docs / "notes/plan.md").write_text("# Goal\nShared lists.\n\n# Risks\nOffline edits.\n")
        (docs / "server.log").write_text("\n".join(f"2026-09-2{i % 9} 10:00 event {i}" for i in range(250)) + "\n")
        (docs / "config.json").write_text('{"retries": 3}')
        (docs / "app.py").write_text("print('hi')\n")
        (docs / "logo.png").write_bytes(b"\x89PNG\0\0binary")
        (docs / "spec.pdf").write_bytes(tiny_pdf(["Deletes reach both phones", "Works offline"]))
        (docs / "memo.txt").write_text("The memo says keep it simple.\n")
        subprocess.run(["textutil", "-convert", "docx", str(docs / "memo.txt"), "-output", str(docs / "memo.docx")],
                       check=True, capture_output=True)
        (docs / "memo.txt").unlink()
        out = self.cap("add", str(self.project), str(docs))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        ledger = (self.project / "docs/project/sources/import-ledger.md").read_text()
        for name, result in (("app.py", "code"), ("logo.png", "binary"), ("server.log", "imported"),
                             ("spec.pdf", "imported"), ("memo.docx", "imported"), ("config.json", "imported")):
            row = next(l for l in ledger.splitlines() if l.startswith(f"| {name} "))
            self.assertIn(result, row)
        metas = {json.loads(m.read_text())["title"]: json.loads(m.read_text())
                 for m in (self.project / "docs/project/sources").glob("SRC-*/meta.json")}
        self.assertEqual(metas["server"]["kind"], "log")
        self.assertEqual(metas["server"]["counts"]["turns"], 2, "250 lines in windows of 200")
        self.assertEqual(metas["spec"]["counts"]["turns"], 2, "one turn per page")
        self.assertIn("pandoc", metas["memo"]["converter"])
        again = self.cap("add", str(self.project), str(docs))
        self.assertIn("0 imported", again.stdout, "unchanged files are not imported twice")
        self.write_dossier("# Dossier\n\n## Units\n\n## No-content turns\nnone\n")
        out = self.cap("check", str(self.project)).stdout
        for where in ("a document section", "a record (log window"):
            self.assertIn(where, out, "every section and record is accounted for, not only the owner's words")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

    def test_history_is_read_commit_by_commit_and_grows_by_appending(self):
        self.git("init", "-q")
        for i, msg in enumerate(("start the list store", "keep deletes on both phones because Mia lost data")):
            (self.project / f"f{i}.txt").write_text(str(i))
            self.git("add", "-A")
            self.git("-c", "user.name=Eric", "-c", "user.email=e@example.com", "commit", "-q", "-m", msg)
        out = self.cap("add", str(self.project), "--git-log")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        folder = next((self.project / "docs/project/sources").glob("SRC-*"))
        turns = [json.loads(l) for l in (folder / "turns.jsonl").read_text().splitlines()]
        self.assertEqual([t["role"] for t in turns], ["record", "record"])
        self.assertIn("because Mia lost data", turns[1]["text"], "the reason in a commit message is kept verbatim")
        (self.project / "f2.txt").write_text("2")
        self.git("add", "-A")
        self.git("-c", "user.name=Eric", "-c", "user.email=e@example.com", "commit", "-q", "-m", "add offline queue")
        self.cap("add", str(self.project), "--git-log")
        turns = [json.loads(l) for l in (folder / "turns.jsonl").read_text().splitlines()]
        self.assertEqual([t["id"] for t in turns], ["T001", "T002", "T003"], "new commits append; earlier IDs stay")
        self.assertEqual(len(list((self.project / "docs/project/sources").glob("SRC-*"))), 1)

    def test_a_tracker_that_cannot_be_read_says_so(self):
        self.git("init", "-q")
        out = self.cap("add", str(self.project), "--tracker")
        self.assertEqual(out.returncode, 1)
        self.assertIn("tracker: not read", out.stdout)

    def test_the_inventory_is_read_by_tier_and_the_ledger_updated(self):
        (self.project / "src").mkdir()
        (self.project / "src/store.py").write_text("\n".join(f"line {i}" for i in range(320)) + "\n")
        (self.project / "README.md").write_text("# Lists\nShared lists.\n")
        (self.project / "package-lock.json").write_text("{}")
        (self.project / "config.toml").write_text("provider = 'x'\n")
        (self.project / "data").mkdir()
        (self.project / "data/rows.json").write_text(json.dumps({"rows": [1, 2], "at": "2026-09-01T10:00"}))
        (self.project / "runs").mkdir()
        (self.project / "runs/out.md").write_text("# raw output\nERROR once\n")
        (self.project / "runs/report.md").write_text("# What the run found\n")
        adoption = self.project / "docs/project/research/adoption"
        adoption.mkdir(parents=True)
        files = [("src/store.py", "code"), ("README.md", "doc"), ("package-lock.json", "lockfile"),
                 ("config.toml", "config"), ("data/rows.json", "config"), ("runs/out.md", "doc"),
                 ("runs/report.md", "doc")]
        (adoption / "inventory.json").write_text(json.dumps({"files": [{"path": p, "class": c} for p, c in files]}))
        (adoption / "coverage.md").write_text("| Path | Class | Lines | Status | Note |\n|---|---|---|---|---|\n" +
                                              "".join(f"| {p} | {c} | 1 | todo | |\n" for p, c in files if c != "lockfile"))
        out = self.cap("add", str(self.project), "--inventory")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        ledger = (adoption / "coverage.md").read_text()
        self.assertRegex(ledger, r"\| src/store\.py \| code \| 1 \| mapped \(code map\) \|")
        self.assertRegex(ledger, r"\| README\.md \| doc \| 1 \| captured \| SRC-\d+ \|")
        self.assertRegex(ledger, r"\| config\.toml \| config \| 1 \| captured \| SRC-\d+ \|")
        self.assertRegex(ledger, r"\| data/rows\.json \| config \| 1 \| registered \(bulk\) \| .*keys: rows, at")
        self.assertRegex(ledger, r"\| runs/out\.md \| doc \| 1 \| registered \(bulk\) \| .*1 error line")
        self.assertRegex(ledger, r"\| runs/report\.md \| doc \| 1 \| captured \| SRC-\d+ \|", "a report is read")
        self.assertIn("data/rows.json", (adoption / "bulk.md").read_text())
        metas = {json.loads(m.read_text())["title"] for m in (self.project / "docs/project/sources").glob("SRC-*/meta.json")}
        self.assertEqual(metas, {"README.md", "config.toml", "runs/report.md"}, "code is mapped, bulk registered")

    def test_an_unreadable_file_is_named_not_skipped(self):
        docs = self.d / "pile"
        docs.mkdir()
        (docs / "scan.pdf").write_bytes(tiny_pdf([]))
        out = self.cap("add", str(self.project), str(docs))
        self.assertEqual(out.returncode, 1)
        self.assertIn("scan.pdf: not read", out.stdout)
        self.assertIn("NOT READ", (self.project / "docs/project/sources/import-ledger.md").read_text())

    def test_check_catches_an_uncovered_owner_turn(self):
        self.add_export()
        self.write_dossier(DOSSIER.replace("SRC-1 T002-T003", "SRC-1 T002").replace(
            '  > "deleting must reach both phones" (SRC-1 T003)\n', '  > "You could build" (SRC-1 T002)\n'))
        out = self.cap("check", str(self.project))
        self.assertEqual(out.returncode, 1)
        self.assertIn("SRC-1 T003", out.stdout)

    def test_check_catches_paraphrase_and_misattribution(self):
        self.add_export()
        self.write_dossier(DOSSIER.replace('"I keep losing grocery lists"', '"I always lose my lists"'))
        self.assertIn("not verbatim", self.cap("check", str(self.project)).stdout)
        self.write_dossier(DOSSIER.replace('  > "I keep losing grocery lists" (SRC-1 T001)',
                                           '  > "build a shared list that syncs" (SRC-1 T002)'))
        out = self.cap("check", str(self.project)).stdout
        self.assertIn("attributed to the owner but quotes the assistant's turn", out)

    def test_no_content_turns_and_removed_units(self):
        self.add_export()
        self.write_dossier(DOSSIER)
        self.extract(self.CARRIED)
        self.audit([])
        self.assertEqual(self.cap("check", str(self.project)).returncode, 0)
        without = DOSSIER.split("- S-003")[0] + "\n## No-content turns\nnone\n"
        self.write_dossier(without)
        out = self.cap("check", str(self.project))
        self.assertIn("S-003 existed at an earlier check", out.stdout)

    def test_closure(self):
        self.add_export()
        self.write_dossier(DOSSIER)
        (self.project / "docs/project/brief.md").write_text(
            "# Brief\n## Source closure\n| Unit | What | Where it lands |\n|---|---|---|\n"
            "| S-001 | drift | intent (Goal) |\n| S-002 | shared list | milestone M1 |\n")
        out = self.cap("closure", str(self.project))
        self.assertEqual(out.returncode, 1)
        self.assertIn("S-003", out.stdout)
        with open(self.project / "docs/project/brief.md", "a") as f:
            f.write("| S-003 | propagate | not adopted (the owner did not take it up) |\n")
        self.assertEqual(self.cap("closure", str(self.project)).returncode, 0)


if __name__ == "__main__":
    unittest.main()
