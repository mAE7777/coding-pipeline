"""Tests for spend.py: a phase's spend is measured from what actually ran, and only the owner raises its cap."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
SPEND = SCRIPTS / "spend.py"
SID = "77777777-2222-3333-4444-555555555555"
sys.path.insert(0, str(SCRIPTS))
import spend  # noqa: E402


OPUS, SONNET, HAIKU = "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"
MTOK = {"input": 1e6, "cache_write": 1e6, "cache_read": 1e6, "output": 1e6}


def call(ts, cwd, mid, out=1000, cache_read=0, cache_write=0, model=None):
    msg = {"id": mid, "usage": {"input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": cache_read,
                                "cache_creation_input_tokens": cache_write}}
    if model:
        msg["model"] = model
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": cwd, "message": msg})


def summary(folder, name, mtime=None, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}.summary.json"
    f.write_text(json.dumps(fields))
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return f


class SpendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name).resolve()
        self.home, self.project = d / "home", d / "work/proj"
        self.project.mkdir(parents=True)
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_CODE_SESSION_ID": SID}
        self.projects = self.home / ".claude/projects"

    def tearDown(self):
        self.tmp.cleanup()

    def spend(self, *args):
        return subprocess.run([sys.executable, str(SPEND), *args], capture_output=True, text=True, env=self.env)

    def transcript(self, folder, name, lines):
        f = self.projects / folder / f"{name}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(lines) + "\n")
        return f

    def start(self, cap="10"):
        r = self.spend("start", str(self.project), "--phase", "adopt", "--cap", cap)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads((self.project / ".evidence/spend/active.json").read_text())["started"]

    def test_what_counts(self):
        started = self.start()
        key = spend.claude_folder_key(self.project)
        after, before = "2099-01-01T00:00:00Z", "2000-01-01T00:00:00Z"
        # This project's own conversation, a helper it started, and a call from before the phase.
        main = self.transcript(key, "s1", [call(before, str(self.project), "m0", out=10**9),
                                           call(after, str(self.project), "m1", out=1000),
                                           call(after, str(self.project), "m1", out=1000)])
        (main.parent / "s1/subagents").mkdir(parents=True)
        (main.parent / "s1/subagents/a.jsonl").write_text(call(after, str(self.project), "h1", cache_read=100000) + "\n")
        # A conversation from a parent folder working inside the project, and one working elsewhere.
        self.transcript("-parent", "s2", [call(after, str(self.project / "src"), "p1", out=2000)])
        self.transcript("-other", "s3", [call(after, "/somewhere/else", "o1", out=10**8)])
        # Isolated runs: one with usage recorded, an older one whose stream holds it, and a Codex one.
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 3000, "cache_write": 8000}}))
        old = self.project / ".evidence/capture/extract-2"
        old.mkdir(parents=True)
        (old / "cold-reader.summary.json").write_text(json.dumps({"status": "OK"}))
        (old / "cold-reader.jsonl").write_text(json.dumps({"type": "result", "usage": {"output_tokens": 1000}}) + "\n")
        cx = self.project / ".evidence/gate/M1/r1"
        cx.mkdir(parents=True)
        (cx / "code-verifier.summary.json").write_text(json.dumps({"family": "codex", "usage": {"output": 500000}}))
        # A Codex conversation in the project (its turns' token counts), and one elsewhere.
        rollouts = self.home / ".codex/sessions/2099/01/01"
        rollouts.mkdir(parents=True)
        turn = lambda ts: json.dumps({"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 100}}}})
        (rollouts / "rollout-a.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "payload": {"cwd": str(self.project)}}), turn(before), turn(after)]) + "\n")
        (rollouts / "rollout-b.jsonl").write_text("\n".join([
            json.dumps({"type": "session_meta", "payload": {"cwd": "/somewhere/else"}}), turn(after)]) + "\n")
        home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            m = spend.measure(self.project, spend.parse_time(started))
        finally:
            os.environ["HOME"] = home
        # conversations: the main call, the helper's call, and the parent folder's call (1000 + 1000 + 2000 output,
        # x5) and the helper's 100000 cache reads (x0.1); the repeated message id counts once
        self.assertEqual(m["conversations"], 4000 * 5 + 100000 * 0.1)
        self.assertEqual(m["isolated"], 3000 * 5 + 8000 * 1.25 + 1000 * 5)
        # the Codex run, and the one Codex turn after the start: 200 uncached input, 800 cached, 100 output
        self.assertEqual(m["codex"], 500000 * 5 + 200 + 800 * 0.1 + 100 * 5, "Codex is shown apart: its own allowance")
        self.assertEqual(m["runs"], 3)

    def test_over_the_cap_stops_and_only_the_owner_raises_it(self):
        self.start(cap="0.000001")
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 100000}}))
        r = self.spend("status", str(self.project))
        self.assertEqual(r.returncode, 1)
        self.assertIn("OVER THE CAP", r.stdout)
        r = self.spend("raise", str(self.project), "--cap", "15", "--quote", "Go up to fifteen percent.")
        self.assertEqual(r.returncode, 1, "words the owner never typed raise nothing")
        self.transcript("-p", SID, [json.dumps({"type": "user", "uuid": "u1", "timestamp": "t",
                                                "message": {"content": "Go up to fifteen percent."}})])
        r = self.spend("raise", str(self.project), "--cap", "15", "--quote", "Go up to fifteen percent.")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.spend("status", str(self.project)).returncode, 0)
        r = self.spend("stop", str(self.project))
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.project / ".evidence/spend/active.json").exists())
        closed = list((self.project / ".evidence/spend").glob("adopt-*.json"))
        self.assertEqual(len(closed), 1)
        self.assertEqual(json.loads(closed[0].read_text())["raises"][0]["quote"], "Go up to fifteen percent.")

    def in_home(self, fn, *args):
        home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            return fn(*args)
        finally:
            os.environ["HOME"] = home

    def test_price_table(self):
        # Per million tokens, by the model that served them.
        self.assertEqual(spend.dollars(OPUS, MTOK), (4.00 + 5.00 + 0.20 + 20.00, True))
        self.assertEqual(spend.dollars(SONNET, MTOK), (2.00 + 2.50 + 0.20 + 10.00, True))
        self.assertAlmostEqual(spend.dollars(HAIKU, MTOK)[0], 0.10 + 0.125 + 0.01 + 0.50)
        # Haiku's cache prices are its input price times 1.25 (write) and 0.1 (read).
        self.assertAlmostEqual(spend.PRICES[HAIKU]["cache_write"], 1.25 * spend.PRICES[HAIKU]["input"])
        self.assertAlmostEqual(spend.PRICES[HAIKU]["cache_read"], 0.1 * spend.PRICES[HAIKU]["input"])
        # A context-window or date suffix names the same model.
        self.assertEqual(spend.dollars(SONNET + "[1m]", MTOK), spend.dollars(SONNET, MTOK))
        self.assertEqual(spend.dollars(SONNET + "-20261001", MTOK), spend.dollars(SONNET, MTOK))
        # An unknown or missing model costs what Opus would, never nothing, and says it was not priced.
        for unknown in ("claude-fable-9", None, ""):
            self.assertEqual(spend.dollars(unknown, MTOK), (spend.dollars(OPUS, MTOK)[0], False), unknown)
        # The units stay model-blind: the allowance and its caps keep their meaning.
        self.assertEqual(spend.WEIGHTS, {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0})

    def test_one_hour_cache_writes_and_haikus_long_prompts_are_priced(self):
        # A 1-hour cache write costs twice the input price; the rest of the writes the cache write price.
        u = {"cache_write": 1_000_000, "cache_write_1h": 400_000}
        self.assertAlmostEqual(spend.dollars(OPUS, u)[0], 0.6 * 5.00 + 0.4 * 8.00)
        self.assertAlmostEqual(spend.dollars(SONNET, u)[0], 0.6 * 2.50 + 0.4 * 4.00)
        self.assertAlmostEqual(spend.dollars(HAIKU, u)[0], 0.6 * 0.125 + 0.4 * 0.20)
        self.assertEqual(spend.dollars(OPUS, {"cache_write": 1_000_000}), (5.00, True), "no breakdown: as before")
        self.assertAlmostEqual(spend.dollars(OPUS, {"cache_write": 10, "cache_write_1h": 50})[0], 10 * 8.00 / 1e6,
                               "a breakdown larger than the writes counts no more than the writes")
        # Haiku's rate for a call whose prompt is over 100K tokens, when the prompt's size is known.
        self.assertAlmostEqual(spend.dollars(HAIKU, MTOK, prompt=100_001)[0], 0.50 + 0.625 + 0.05 + 2.50)
        self.assertAlmostEqual(spend.dollars(HAIKU, MTOK, prompt=100_000)[0], 0.10 + 0.125 + 0.01 + 0.50)
        self.assertAlmostEqual(spend.dollars(HAIKU, MTOK)[0], 0.10 + 0.125 + 0.01 + 0.50, "size unknown: base rate")
        self.assertEqual(spend.dollars(OPUS, MTOK, prompt=900_000), spend.dollars(OPUS, MTOK), "only Haiku has one")
        self.assertEqual(spend.dollars("claude-mystery-1", MTOK, prompt=900_000), (spend.dollars(OPUS, MTOK)[0], False))
        self.assertAlmostEqual(spend.LONG_PRICES[HAIKU]["cache_write"], 1.25 * spend.LONG_PRICES[HAIKU]["input"])
        self.assertAlmostEqual(spend.LONG_PRICES[HAIKU]["cache_read"], 0.1 * spend.LONG_PRICES[HAIKU]["input"])
        # The API's usage object: the breakdown is read when it is there, and only then.
        self.assertEqual(spend.api_usage({"input_tokens": 5, "cache_creation_input_tokens": 10, "output_tokens": 2,
                                          "cache_creation": {"ephemeral_5m_input_tokens": 4,
                                                             "ephemeral_1h_input_tokens": 6}}),
                         {"input": 5, "cache_write": 10, "cache_read": 0, "output": 2, "cache_write_1h": 6})
        self.assertNotIn("cache_write_1h", spend.api_usage({"cache_creation_input_tokens": 10}))
        self.assertNotIn("cache_write_1h", spend.api_usage({"cache_creation": "odd", "input_tokens": None}))
        self.assertEqual(spend.WEIGHTS["cache_write"], 1.25, "units do not change")

    def test_transcripts_are_priced_call_by_call_and_summed_runs_keep_the_base_rate(self):
        started = self.start()
        key = spend.claude_folder_key(self.project)
        after = "2099-01-01T00:00:00Z"

        def line(mid, model, inp=0, out=0, write=0, hour=None):
            u = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": write}
            if hour is not None:
                u["cache_creation"] = {"ephemeral_5m_input_tokens": write - hour, "ephemeral_1h_input_tokens": hour}
            return json.dumps({"type": "assistant", "timestamp": after, "cwd": str(self.project),
                               "message": {"id": mid, "model": model, "usage": u}})

        main = self.transcript(key, "s1", [line("m1", HAIKU, inp=50_000, out=1000),
                                           line("m2", OPUS, write=1_000_000, hour=400_000),
                                           line("m3", OPUS, write=1_000_000)])
        (main.parent / "s1/subagents").mkdir(parents=True)
        (main.parent / "s1/subagents/a.jsonl").write_text(line("h1", HAIKU, inp=150_000, out=1000) + "\n")
        summary(self.project / ".evidence/scout/r1", "scout", served_model=HAIKU, usage={"input": 300_000})
        m = self.in_home(spend.measure, self.project, spend.parse_time(started))
        long_call = 150_000 * 0.50 / 1e6 + 1000 * 2.50 / 1e6  # a helper's call, carried through the merge
        short_call = 50_000 * 0.10 / 1e6 + 1000 * 0.50 / 1e6
        self.assertAlmostEqual(m["dollars"]["conversations"], long_call + short_call + (0.6 * 5.00 + 0.4 * 8.00) + 5.00)
        self.assertAlmostEqual(m["dollars"]["isolated"], 300_000 * 0.10 / 1e6, "a run's summed usage: base rate")
        self.assertEqual(m["conversations"], 200_000 + 2_000_000 * 1.25 + 2000 * 5, "units are unchanged")
        rep = self.in_home(spend.report, self.project, None, spend.parse_time(started))
        self.assertAlmostEqual(rep["sessions"]["dollars"], m["dollars"]["conversations"])
        self.assertAlmostEqual(rep["total"]["dollars"], m["dollars"]["conversations"] + m["dollars"]["isolated"])

    def test_dollars_by_the_model_each_call_came_from(self):
        started = self.start()
        key = spend.claude_folder_key(self.project)
        after = "2099-01-01T00:00:00Z"
        self.transcript(key, "s1", [call(after, str(self.project), "m1", out=1_000_000, model=OPUS),
                                    call(after, str(self.project), "m2", out=1_000_000, model=SONNET),
                                    call(after, str(self.project), "m3", out=1_000_000),  # no model named
                                    call(after, str(self.project), "m4", out=0, model="<synthetic>")])
        ev = self.project / ".evidence/gate/M1/r1"
        summary(ev, "gate-judge", served_model=HAIKU, model=OPUS, usage={"output": 1_000_000})
        summary(ev, "loyal-evaluator", model=SONNET, usage={"cache_read": 1_000_000})
        summary(ev, "claim-verifier", model="claude-mystery-1", usage={"input": 1_000_000})
        summary(ev, "code-verifier", family="codex", model="gpt-x", usage={"output": 1_000_000})
        m = self.in_home(spend.measure, self.project, spend.parse_time(started))
        self.assertEqual(m["conversations"], 3_000_000 * 5, "units are unchanged by the model")
        self.assertAlmostEqual(m["dollars"]["conversations"], 20.00 + 10.00 + 20.00)
        # the served model counts, not the requested one; Codex is never priced
        self.assertAlmostEqual(m["dollars"]["isolated"], 0.50 + 0.20 + 4.00)
        self.assertEqual(m["unpriced_model"], 2, "the call with no model and the unknown run; a call with no tokens "
                                                 "is not counted")
        self.assertEqual(m["unpriced_models"], ["claude-mystery-1", "missing"])
        self.assertEqual(m["codex"], 1_000_000 * 5)
        r = self.spend("status", str(self.project))
        self.assertIn("$54.70 at list prices", r.stdout)
        self.assertIn("unpriced_model: 2 usage entries", r.stdout)
        self.assertIn("claude-mystery-1, missing", r.stdout)

    def test_report_groups_by_milestone_round_and_role(self):
        t0 = time.time() - 1000
        baseline = self.project / ".evidence/baseline-M2.txt"
        baseline.parent.mkdir(parents=True)
        baseline.write_text("fingerprint\n")
        os.utime(baseline, (t0, t0))
        ev = self.project / ".evidence"
        u = {"input": 100, "cache_write": 900, "cache_read": 9000, "output": 1000}
        summary(ev / "gate/M1/r1", "code-verifier", mtime=t0 - 500, model=OPUS, usage=u)  # another milestone
        summary(ev / "gate/M2/r1", "code-verifier", model=OPUS, usage=u)
        summary(ev / "gate/M2/r1", "code-verifier-demo", served_model=SONNET, usage=u)
        summary(ev / "gate/M2/r2", "code-verifier", model=OPUS, usage=u)
        summary(ev / "gate/M2/r10", "gate-judge", model=OPUS, usage=u)
        summary(ev / "loyal/M2/r1", "loyal-evaluator-pass2", model=OPUS, usage=u)
        summary(ev / "dev", "cold-reader", model=HAIKU, usage=u)  # no milestone, in the window
        summary(ev / "plan-r2", "cold-reader", mtime=t0 - 500, model=OPUS, usage=u)  # before the window
        summary(ev / "gate/M2/r2", "code-verifier-codex", family="codex", model="gpt-x", usage=u)
        summary(ev / "gate/M2/r2", "gate-judge", status="BLOCKED")  # no model call was made
        key = spend.claude_folder_key(self.project)
        self.transcript(key, "s1", [call("2099-01-01T00:00:00Z", str(self.project), "m1", out=1000, model=SONNET),
                                    call("2000-01-01T00:00:00Z", str(self.project), "m0", out=10**9, model=OPUS)])
        r = self.spend("report", str(self.project), "--json", "--milestone", "M2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["since_from"], "when M2's baseline was recorded")
        got = [(g["milestone"], g["area"], g["round"], g["role"], g["runs"]) for g in rep["groups"]]
        self.assertEqual(got, [("M2", "gate", "r1", "code-verifier", 1), ("M2", "gate", "r1", "code-verifier-demo", 1),
                               ("M2", "gate", "r2", "code-verifier", 1), ("M2", "gate", "r2", "code-verifier-codex", 1),
                               ("M2", "gate", "r10", "gate-judge", 1), ("M2", "loyal", "r1", "loyal-evaluator-pass2", 1),
                               ("-", "dev", "-", "cold-reader", 1)])
        demo = rep["groups"][1]
        self.assertEqual(demo["models"], [SONNET])
        self.assertAlmostEqual(demo["dollars"], (100 * 2 + 900 * 2.5 + 9000 * 0.2 + 1000 * 10) / 1e6)
        self.assertEqual(demo["units"], spend.units(u))
        self.assertAlmostEqual(demo["cache_read_share"], 9000 / 10000)
        self.assertEqual(demo["tokens"], u)
        codex = rep["groups"][3]
        self.assertEqual((codex["dollars"], codex["models"]), (0, ["codex:gpt-x"]), "Codex is shown, never priced")
        self.assertEqual(rep["isolated"]["runs"], 6)
        self.assertEqual(rep["isolated_without_usage"], 1)
        self.assertEqual(rep["codex"]["runs"], 1)
        self.assertEqual(rep["sessions"]["conversations"], 1)
        self.assertAlmostEqual(rep["sessions"]["dollars"], 1000 * 10 / 1e6, msg="only the call inside the window")
        self.assertAlmostEqual(rep["total"]["dollars"], rep["isolated"]["dollars"] + rep["sessions"]["dollars"])
        # The table, by default.
        r = self.spend("report", str(self.project), "--milestone", "M2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("milestone area", r.stdout)
        self.assertRegex(r.stdout, r"M2\s+gate\s+r1\s+code-verifier-demo\s+1\s")
        self.assertIn("Codex (its own allowance, not priced): 1 run(s)", r.stdout)
        self.assertIn("1 run(s) recorded no usage", r.stdout)
        # --since sets the window: the earlier milestone and the first plan re-read come in.
        r = self.spend("report", str(self.project), "--since", "1970-01-01T00:00:00Z", "--json")
        rows = {(g["milestone"], g["area"], g["round"], g["role"]) for g in json.loads(r.stdout)["groups"]}
        self.assertIn(("M1", "gate", "r1", "code-verifier"), rows)
        self.assertIn(("-", "plan", "r2", "cold-reader"), rows)
        # No window is bad usage, and so is a milestone whose start is not recorded.
        self.assertEqual(self.spend("report", str(self.project)).returncode, 2)
        r = self.spend("report", str(self.project), "--milestone", "M7")
        self.assertEqual(r.returncode, 2)
        self.assertIn("pass --since", r.stderr)
        self.assertEqual(self.spend("report", str(self.project), "--milestone", "seven").returncode, 2)

    def test_a_shadow_runs_cost_shows_apart(self):
        ev = self.project / ".evidence/gate/M1/r3"
        u = {"input": 10, "cache_write": 0, "cache_read": 0, "output": 100}
        summary(ev, "gate-judge", model=OPUS, usage=u)
        summary(ev / "shadow", "gate-judge", served_model=SONNET, usage=u)
        summary(ev / "shadow", "code-verifier-demo", served_model=SONNET, usage=u)
        roles = {r["path"]: r["role"] for r in spend.run_summaries(self.project)}
        self.assertEqual(roles, {"gate/M1/r3/gate-judge.summary.json": "gate-judge",
                                 "gate/M1/r3/shadow/gate-judge.summary.json": "gate-judge (shadow)",
                                 "gate/M1/r3/shadow/code-verifier-demo.summary.json": "code-verifier-demo (shadow)"})
        r = self.spend("report", str(self.project), "--since", "1970-01-01T00:00:00Z", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = {(g["round"], g["role"]): (g["runs"], g["models"]) for g in json.loads(r.stdout)["groups"]}
        self.assertEqual(got[("r3", "gate-judge")], (1, [OPUS]))
        self.assertEqual(got[("r3", "gate-judge (shadow)")], (1, [SONNET]), "the shadow is its own row")
        r = self.spend("report", str(self.project), "--since", "1970-01-01T00:00:00Z")
        self.assertRegex(r.stdout, r"M1\s+gate\s+r3\s+code-verifier-demo \(shadow\)\s+1\s")

    def test_estimate_and_calibrate(self):
        src = self.project / "docs/project/sources/SRC-1-notes"
        src.mkdir(parents=True)
        (src / "meta.json").write_text(json.dumps({"id": "SRC-1", "kind": "doc"}))
        (src / "transcript.md").write_text("x" * 400000)
        r = self.spend("estimate", str(self.project))
        self.assertIn("1 source(s) to read, about 100k tokens", r.stdout)
        ev = self.project / ".evidence/capture/extract-1"
        ev.mkdir(parents=True)
        (ev / "cold-reader.summary.json").write_text(json.dumps({"usage": {"output": 1_000_000}}))
        r = self.spend("calibrate", "10", str(self.project))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads((self.home / ".claude/.pipeline-budget.json").read_text())["weekly_units"], 50_000_000)


if __name__ == "__main__":
    unittest.main()
