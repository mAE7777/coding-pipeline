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
        self.assertEqual(out.returncode, 0, out.stdout)

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
