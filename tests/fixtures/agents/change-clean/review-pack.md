# Change review

Base: 264d90c95b4e03ebd60cbb1c1516e679ee3155fc
Head: 011d38a734667491650a5c7f920cf1ec90778e3a
The folder you are in holds the head commit's tree.

## The change record
# CHG-0001 · list inbox items whose words contain a colon

Incidents: INC-0001
Kind: fix
Base: 264d90c95b4e03ebd60cbb1c1516e679ee3155fc
Branch: evolve/chg-0001
Suites: selftest;repro:test:tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole

## Root cause
inbox_list.py:18 unpacks rest.split(": ") into two names. The item format puts the proposer's name before the
first ": " and their words after it; the words may themselves contain ": ", so splitting on every occurrence
breaks the format's own rule.

## Options
- A, the session's workaround: edit the item's words so they carry no colon. Works for one item at a time and
  changes the proposer's words, which the inbox must keep verbatim; measured: not a pipeline change.
- B: skip any line that does not parse. The crash goes away, but the item silently disappears from the
  listing, which loses someone's input without a trace.
- C: split once, on the first ": ", which is the format's rule (a name never contains ": ").

Chosen: C, because it implements the format as written, keeps every item and its words whole, and hides
nothing; B trades a loud failure for a silent loss.
Session workaround: replaced (the listing shows the item with its original words, so no edit is needed)

## Review
Result: <filled by evolve.py review>

## Owner
Ruling: not needed (a fix or a document change inside the pipeline's rules)


## The incidents it answers
# INC-0001 · the inbox listing crashes on words that contain a colon

Status: confirmed
Kind: defect
Where: skills/_shared/scripts/inbox_list.py
Signature: traceback: inbox_list.py ValueError: too many values to unpack (expected <n>, got <n>)
Pipeline version: 264d90c

## Symptom
Candidate 3 (traceback x1) at 41c2e0a7-5b1d-4f0e-9d3a-7f2a61c0b8e4:
```
Traceback (most recent call last):
  File "~/.claude/skills/_shared/scripts/inbox_list.py", line 33, in <module>
    sys.exit(main(sys.argv[1:]))
             ~~~~^^^^^^^^^^^^^^
  File "~/.claude/skills/_shared/scripts/inbox_list.py", line 27, in main
    for ident, who, words in items(Path(argv[0]).read_text(encoding="utf-8")):
                             ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "~/.claude/skills/_shared/scripts/inbox_list.py", line 18, in items
    who, words = rest.split(": ")
    ^^^^^^^^^^
ValueError: too many values to unpack (expected 2, got 3)
```

## Impact
The inbox listing stopped with a traceback once item IN-004 ("Maya: Idea: keep the dates when exporting.")
arrived, so the open items could not be shown to the owner at the stop, and the session had to work around it.

## What the session did
It edited IN-004 in inbox.md to read "Idea - keep the dates when exporting." and the listing ran again. That
worked for this item, but it changed the proposer's words, which the inbox must keep verbatim.

## Occurrences
- 2026-09-29 · harvest 2026-09-29-5e0c11a2f7b3 · a project session

## Reproduction
repro:test:tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole: fails at base by an assertion (the listing exits 1 with the traceback above).


## The comparison (computed by script from the stored measurements)
- selftest: base 2/2 suites pass | head 2/2 suites pass
- repro:test:tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole: base fail | head pass
Verdict: BETTER: every reproduction flipped: test tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole: base fail, head pass

## The reproductions' output
### repro:test:tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole at base
```

======================================================================
FAIL: test_words_with_a_colon_are_listed_whole (__main__.InboxList.test_words_with_a_colon_are_listed_whole)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "<tree>/tests/test_inbox_list.py", line 35, in test_words_with_a_colon_are_listed_whole
    self.assertEqual(r.returncode, 0, r.stderr)
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: 1 != 0 : Traceback (most recent call last):
  File "<tree>/skills/_shared/scripts/inbox_list.py", line 33, in <module>
    sys.exit(main(sys.argv[1:]))
             ~~~~^^^^^^^^^^^^^^
  File "<tree>/skills/_shared/scripts/inbox_list.py", line 27, in main
    for ident, who, words in items(Path(argv[0]).read_text(encoding="utf-8")):
                             ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<tree>/skills/_shared/scripts/inbox_list.py", line 18, in items
    who, words = rest.split(": ")
    ^^^^^^^^^^
ValueError: too many values to unpack (expected 2, got 3)


----------------------------------------------------------------------
Ran 1 test in 0.033s

FAILED (failures=1)

```
### repro:test:tests/test_inbox_list.py::InboxList.test_words_with_a_colon_are_listed_whole at head
```
.
----------------------------------------------------------------------
Ran 1 test in 0.022s

OK

```

## The diff (base..head)
```diff
diff --git a/skills/_shared/scripts/inbox_list.py b/skills/_shared/scripts/inbox_list.py
index 0b7e553..4dda2d6 100644
--- a/skills/_shared/scripts/inbox_list.py
+++ b/skills/_shared/scripts/inbox_list.py
@@ -15,7 +15,8 @@ def items(text):
         if not line.startswith("- IN-"):
             continue
         ident, rest = line[2:].split(" · ", 1)
-        who, words = rest.split(": ")
+        # The proposer's name never contains ": "; their words may.
+        who, words = rest.split(": ", 1)
         out.append((ident, who, words))
     return out
 
diff --git a/tests/test_inbox_list.py b/tests/test_inbox_list.py
index 8612c12..5200d21 100644
--- a/tests/test_inbox_list.py
+++ b/tests/test_inbox_list.py
@@ -30,6 +30,12 @@ class InboxList(unittest.TestCase):
         r = self.run_list(SAMPLE)
         self.assertIn("IN-002 · Priya: The share link should expire after a week.", r.stdout)
 
+    def test_words_with_a_colon_are_listed_whole(self):
+        r = self.run_list(SAMPLE + "- IN-004 · Maya: Idea: keep the dates when exporting.\n")
+        self.assertEqual(r.returncode, 0, r.stderr)
+        self.assertIn("IN-004 · Maya: Idea: keep the dates when exporting.", r.stdout)
+        self.assertEqual(r.stdout.count("IN-"), 4)
+
 
 if __name__ == "__main__":
     unittest.main()

```

## The pipeline's charter
{repo:skills/_shared/references/pipeline-constitution.md}