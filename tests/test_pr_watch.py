"""Tests for pr_watch.py: the port of pstack's watch-pr (policy, GitHub reads, command line) and land-check.

No test reaches the network: the GitHub reader is a fake, or GhReader runs over a fake gh runner; land-check runs
real git on temporary repositories with gh replaced.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/_shared/scripts"
WATCH = SCRIPTS / "pr_watch.py"
sys.path.insert(0, str(SCRIPTS))
import fingerprint as fingerprint_mod  # noqa: E402
import pr_watch as pw  # noqa: E402

OBSERVED = "2026-07-26T00:00:00.000Z"
OPTIONS = {"interval": 10, "sweep_interval": 300, "timeout": 0, "max_query_errors": 5, "allow_draft": False}
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def ctx(number):
    return {"owner": "owner", "repo": "repo", "number": number}


def check(kind, name="ci", state=None):
    states = {"passed": "SUCCESS", "pending": "PENDING", "failed": "FAILURE"}
    return {"name": name, "description": "", "link": "", "workflow": "", "kind": kind,
            "reportedState": state or states[kind]}


def passing(name="ci"):
    return check("passed", name)


def pending(name="ci"):
    return check("pending", name)


def failed(name="ci"):
    return check("failed", name)


def comment(author="someone", body="please fix", path="a.ts", line=1):
    return {"authorLogin": author, "body": body, "path": path, "line": line, "createdAt": "now"}


def raw_thread(thread_id, first=None, resolved=False):
    return {"id": thread_id, "firstComment": first if first is not None else comment(), "resolved": resolved}


class FakeReader(pw.GitHubReader):
    """The port of fakes.test-helper.ts: canned reads, and every call recorded in order."""

    def __init__(self, facts=None, fast_path=None, rollup_pages=None, threads=None, thread_pages=None,
                 commit_rollups=None, open_prs=None, origin="default", current=None):
        self.calls = []
        self.facts = facts or {}
        self.fast_path = fast_path or {"kind": "checks", "checks": [passing()]}
        self.rollup_pages = list(rollup_pages or [])
        self.threads = threads or []
        self.thread_pages = list(thread_pages or [])
        self.rollups = commit_rollups if commit_rollups is not None else [{"oid": "head", "state": "SUCCESS"}]
        self.open_prs = open_prs or []
        self.origin = {"owner": "owner", "repo": "repo"} if origin == "default" else origin
        self.current = current or ctx(1)

    def origin_repo(self):
        self.calls.append("originRepo")
        return self.origin

    def current_pr(self, pr):
        self.calls.append("currentPr")
        return {**self.current, "number": pr if pr is not None else self.current["number"]}

    def pull_request(self, context):
        self.calls.append("pullRequest")
        defaults = {"mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED",
                    "headRefOid": "head", "headRefName": "feature", "baseRefName": "main", "state": "OPEN",
                    "mergedAt": None, "isDraft": False}
        return {"context": context, **defaults, **self.facts}

    def open_pull_requests(self, repository):
        self.calls.append("openPullRequests")
        return self.open_prs

    def checks_fast_path(self, context):
        self.calls.append("checksFastPath")
        return self.fast_path

    def check_rollup_page(self, context, after):
        self.calls.append(f"checkRollupPage:{after if after is not None else 'null'}")
        return self.rollup_pages.pop(0) if self.rollup_pages else {"checks": [], "endCursor": None}

    def review_thread_page(self, context, after):
        self.calls.append(f"reviewThreadPage:{after if after is not None else 'null'}")
        if self.thread_pages:
            return self.thread_pages.pop(0)
        return {"threads": [raw_thread(t["id"], t["firstComment"]) for t in self.threads], "endCursor": None}

    def commit_rollups(self, context):
        self.calls.append("commitRollups")
        return self.rollups


class StopProof(Exception):
    pass


class FakeClock:
    def __init__(self, stop_after_sleeps=None, timeline=None):
        self.t, self.sleeps, self.stop_after, self.timeline = 0, [], stop_after_sleeps, timeline

    def now(self):
        return self.t

    def observed_at(self):
        return OBSERVED

    def sleep(self, seconds):
        if self.timeline is not None:
            self.timeline.append("sleep")
        self.t += seconds
        self.sleeps.append(seconds)
        if self.stop_after is not None and len(self.sleeps) >= self.stop_after:
            raise StopProof("stop after proof")


def deps(reader, clock=None, emitted=None, timeline=None, config=pw.DEFAULT_CONFIG):
    def emit(verdict):
        if emitted is not None:
            emitted.append(verdict)
        if timeline is not None:
            timeline.append(f"emit:{verdict['kind']}")
    return pw.Dependencies(reader, clock or FakeClock(), emit, config)


def snapshot(reader, number, history="omit", config=pw.DEFAULT_CONFIG):
    return pw.read_snapshot(reader, ctx(number), history, config)


# ---------------------------------------------------------------------------------------------------------------
# policy.test.ts


class ReadinessTest(unittest.TestCase):
    def test_truth_table_covers_every_row_and_unknown_rollup(self):
        cases = [("BLOCKED", "FAILURE", "refused"), ("BLOCKED", "ERROR", "refused"), ("BLOCKED", "PENDING", "allowed"),
                 ("UNSTABLE", "FAILURE", "allowed"), ("UNKNOWN", "ERROR", "allowed"),
                 ("UNKNOWN", "EXPECTED", "allowed"), ("UNKNOWN", "FAILURE", "allowed"),
                 ("UNKNOWN", "PENDING", "allowed"), ("UNKNOWN", "SUCCESS", "allowed"), ("UNKNOWN", None, "allowed"),
                 ("CLEAN", "SUCCESS", "allowed")]
        for merge_state, rollup, expected in cases:
            self.assertEqual(pw.assess_github_merge(merge_state, rollup)["kind"], expected, (merge_state, rollup))
        self.assertEqual(pw.assess_github_merge("BLOCKED", None)["basis"], "rollup")
        self.assertEqual(pw.assess_github_merge("CLEAN", None)["basis"], "merge-state")

    def test_a_green_list_with_a_github_refusal_is_a_ci_blocker(self):
        reader = FakeReader(facts={"mergeStateStatus": "BLOCKED"}, commit_rollups=[{"oid": "head", "state": "FAILURE"}])
        row = snapshot(reader, 1, "include")
        self.assertEqual(row["kind"], "open")
        self.assertEqual(row["ci"]["kind"], "ci-github-rejected")
        self.assertEqual(row["ci"]["github"], {"kind": "refused", "mergeStateStatus": "BLOCKED",
                                               "headRollupState": "FAILURE"})
        decision = pw.classify_pr(row)
        self.assertEqual((decision["kind"], decision["blocker"]["kind"]), ("blocker", "failing-checks"))

    def test_earlier_passing_ci_is_remembered(self):
        reader = FakeReader(fast_path={"kind": "checks", "checks": [failed()]},
                            commit_rollups=[{"oid": "old", "state": "SUCCESS"}, {"oid": "head", "state": "FAILURE"}])
        self.assertTrue(snapshot(reader, 1, "include")["ci"]["hadPreviousPassingCi"])

    def test_a_pending_review_automation_is_noticed(self):
        reader = FakeReader(fast_path={"kind": "checks", "checks": [passing(), pending("Cursor Bugbot")]})
        self.assertTrue(snapshot(reader, 1)["reviewAutomationRunning"])
        self.assertFalse(snapshot(FakeReader(), 1)["reviewAutomationRunning"])


class SnapshotPlanningTest(unittest.TestCase):
    def test_no_commit_rollups_while_queued_checks_are_pending(self):
        reader = FakeReader(fast_path={"kind": "checks", "checks": [pending()]})
        row = snapshot(reader, 2, "omit")
        self.assertEqual(row["ci"]["kind"], "ci-pending")
        self.assertEqual(reader.calls, ["pullRequest", "reviewThreadPage:null", "checksFastPath"])

    def test_rollups_are_read_for_settled_and_failed_lists(self):
        settled = FakeReader()
        snapshot(settled, 3, "omit")
        self.assertIn("commitRollups", settled.calls)
        failing = FakeReader(fast_path={"kind": "checks", "checks": [failed()]})
        snapshot(failing, 4, "omit")
        self.assertIn("commitRollups", failing.calls)

    def test_merged_rows_short_circuit_before_threads_and_checks(self):
        reader = FakeReader(facts={"state": "MERGED", "mergedAt": "2026-07-26T00:00:00Z"})
        self.assertEqual(snapshot(reader, 5, "include")["kind"], "merged")
        self.assertEqual(reader.calls, ["pullRequest"])
        closed = FakeReader(facts={"state": "CLOSED"})
        self.assertEqual(snapshot(closed, 5)["kind"], "closed")


class DecisionTest(unittest.TestCase):
    def test_stacks_are_scanned_tier_major(self):
        frontier = snapshot(FakeReader(fast_path={"kind": "checks", "checks": [failed()]},
                                       commit_rollups=[{"oid": "head", "state": "FAILURE"}]), 10)
        upstack = snapshot(FakeReader(facts={"mergeable": "CONFLICTING"}), 11)
        decision = pw.select_tier_major_stack_decision([frontier, upstack])
        self.assertEqual(decision["kind"], "blocker")
        self.assertEqual(decision["blocker"]["kind"], "merge-conflicts")
        self.assertEqual(decision["blocker"]["pr"]["number"], 11)

    def test_a_stack_wait_names_the_pr_whose_checks_are_pending(self):
        ready_bottom = snapshot(FakeReader(), 20)
        pending_upstack = snapshot(FakeReader(fast_path={"kind": "checks", "checks": [pending("upstack-build")]}), 21)
        decision = pw.select_tier_major_stack_decision([ready_bottom, pending_upstack])
        self.assertEqual(decision["kind"], "waiting")
        self.assertEqual(decision["frontier"]["number"], 21)
        self.assertEqual(decision["reason"]["kind"], "pending-checks")
        self.assertEqual([c["name"] for c in decision["reason"]["pending"]], ["upstack-build"])

    def test_a_draft_waits_while_pending_then_hits_the_draft_gate(self):
        waiting = snapshot(FakeReader(facts={"isDraft": True}, fast_path={"kind": "checks", "checks": [pending()]}), 12)
        self.assertEqual(pw.classify_pr(waiting)["kind"], "waiting")
        settled = snapshot(FakeReader(facts={"isDraft": True}), 12)
        decision = pw.classify_pr(settled)
        self.assertEqual((decision["blocker"]["kind"], decision["blocker"]["reason"]), ("merge-gate", "draft-pr"))
        allowed = pw.classify_pr(settled, allow_draft=True)
        self.assertEqual(allowed["kind"], "ready")
        self.assertEqual(allowed["pr"]["proof"]["gate"]["draft"], "draft-allowed")

    def test_single_pr_order_is_conflicts_threads_ci_gate(self):
        threads = [{"id": "t1", "firstComment": comment()}]
        everything = FakeReader(facts={"mergeable": "CONFLICTING", "reviewDecision": "CHANGES_REQUESTED"},
                                threads=threads, fast_path={"kind": "checks", "checks": [failed()]})
        self.assertEqual(pw.classify_pr(snapshot(everything, 1))["blocker"]["kind"], "merge-conflicts")
        no_conflict = FakeReader(facts={"reviewDecision": "CHANGES_REQUESTED"}, threads=threads,
                                 fast_path={"kind": "checks", "checks": [failed()]})
        self.assertEqual(pw.classify_pr(snapshot(no_conflict, 1))["blocker"]["kind"], "review-threads")
        ci_only = FakeReader(facts={"reviewDecision": "CHANGES_REQUESTED"},
                             fast_path={"kind": "checks", "checks": [failed()]})
        self.assertEqual(pw.classify_pr(snapshot(ci_only, 1))["blocker"]["kind"], "failing-checks")
        gate = pw.classify_pr(snapshot(FakeReader(facts={"reviewDecision": "CHANGES_REQUESTED"}), 1))
        self.assertEqual(gate["blocker"]["reason"], "changes-requested")
        closed = pw.classify_pr(snapshot(FakeReader(facts={"state": "CLOSED"}), 1))
        self.assertEqual(closed["blocker"]["reason"], "closed-without-merge")
        for state in ("DIRTY", "CONFLICTING"):
            row = snapshot(FakeReader(facts={"mergeStateStatus": state}), 1)
            self.assertEqual(pw.classify_pr(row)["blocker"]["kind"], "merge-conflicts")

    def test_ready_and_merged_carry_their_proof(self):
        ready = pw.classify_pr(snapshot(FakeReader(), 1))
        self.assertEqual(ready["kind"], "ready")
        self.assertEqual(ready["pr"]["proof"]["mergeability"], "clear")
        self.assertEqual(ready["pr"]["proof"]["ci"]["kind"], "ci-clean")
        merged = pw.classify_pr(snapshot(FakeReader(facts={"state": "MERGED", "mergedAt": "t"}), 1))
        self.assertEqual(merged, {"kind": "merged", "pr": {"kind": "merged-pr", "context": ctx(1), "mergedAt": "t"}})

    def test_ready_only_when_github_agrees_the_pr_can_merge(self):
        for state in ("CLEAN", "HAS_HOOKS", "UNSTABLE"):
            self.assertEqual(pw.classify_pr(snapshot(FakeReader(facts={"mergeStateStatus": state}), 1))["kind"],
                             "ready", state)
        for facts in ({"mergeable": "UNKNOWN"}, {"mergeStateStatus": "UNKNOWN"},
                      {"mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"}):
            decision = pw.classify_pr(snapshot(FakeReader(facts=facts), 1))
            self.assertEqual((decision["kind"], decision["reason"]["kind"]), ("waiting", "github-undecided"), facts)

    def test_behind_a_required_review_and_another_block_are_named_merge_gates(self):
        cases = [({"mergeStateStatus": "BEHIND"}, [passing()], "behind-base"),
                 ({"mergeStateStatus": "BLOCKED", "reviewDecision": "REVIEW_REQUIRED"}, [passing()], "review-required"),
                 ({"mergeStateStatus": "BLOCKED"}, [passing(), check("code-review-gate", "Code Review Gate", "PENDING")],
                  "review-required"),
                 ({"mergeStateStatus": "BLOCKED"}, [passing()], "merge-blocked")]
        for facts, checks, reason in cases:
            row = snapshot(FakeReader(facts=facts, fast_path={"kind": "checks", "checks": checks}), 1, "include")
            decision = pw.classify_pr(row)
            self.assertEqual((decision["kind"], decision["blocker"]["kind"], decision["blocker"]["reason"]),
                             ("blocker", "merge-gate", reason), facts)
            self.assertIn(f"BLOCKER: {reason}\npr=1\naction=",
                          pw.render_pretty({"kind": "BLOCKER", "blocker": decision["blocker"]}))
        waits = snapshot(FakeReader(facts={"mergeStateStatus": "BLOCKED", "reviewDecision": "REVIEW_REQUIRED"},
                                    fast_path={"kind": "checks", "checks": [pending()]}), 1, "include")
        self.assertEqual(pw.classify_pr(waits)["kind"], "waiting", "the checks settle first, then the gate blocks")

    def test_retry_floor_and_cap(self):
        self.assertEqual(pw.query_backoff_seconds(1, 1), 60)
        self.assertEqual(pw.query_backoff_seconds(1, 2), 120)
        self.assertEqual(pw.query_backoff_seconds(60, 4), 300)
        self.assertEqual(pw.query_backoff_seconds(2.5, 1), 60)
        self.assertIsInstance(pw.query_backoff_seconds(2.5, 1), int)


class QueuedCadenceTest(unittest.TestCase):
    def test_a_sweep_head_drops_only_after_its_snapshot_succeeds(self):
        queue = [ctx(20), ctx(21), ctx(22)]
        state = pw.create_queue_state(queue, 0)
        state, _ = pw.apply_queue_snapshot(state, snapshot(FakeReader(), 20), 0, OPTIONS)
        self.assertEqual(state["work"]["kind"], "whole-stack-sweep")
        self.assertEqual([c["number"] for c in state["work"]["remaining"]], [21, 22])
        state, _ = pw.apply_queue_snapshot(state, snapshot(FakeReader(), 21), 60, OPTIONS)
        self.assertEqual([c["number"] for c in state["work"]["remaining"]], [22])
        with self.assertRaisesRegex(RuntimeError, "does not match sweep head"):
            pw.apply_queue_snapshot(state, snapshot(FakeReader(), 21), 60, OPTIONS)

    def test_the_sweep_resumes_at_the_pr_whose_read_failed(self):
        timeline = []

        class Reader(FakeReader):
            fail_next = True

            def pull_request(self, context):
                if context["number"] == 21 and self.fail_next:
                    self.fail_next = False
                    timeline.append("fail:21")
                    raise pw.WatcherQueryError({"kind": "command-exit", "retryable": True, "detail": "rate limited",
                                                "code": 1})
                timeline.append(f"read:{context['number']}")
                return super().pull_request(context)

        clock = FakeClock(stop_after_sleeps=2, timeline=timeline)
        with self.assertRaises(StopProof):
            pw.run_queued(deps(Reader(), clock, timeline=timeline), [ctx(20), ctx(21), ctx(22)], OPTIONS)
        self.assertEqual(timeline, ["emit:QUEUE", "read:20", "fail:21", "emit:RETRY", "sleep", "read:21", "read:22",
                                    "emit:STATUS", "emit:WAITING", "sleep"])

    def test_a_completed_sweep_is_reported_after_its_final_snapshot(self):
        queue = [ctx(30), ctx(31)]
        state = pw.create_queue_state(queue, 0)
        state, rows = pw.apply_queue_snapshot(state, snapshot(FakeReader(), 30), 0, OPTIONS)
        self.assertIsNone(rows)
        state, rows = pw.apply_queue_snapshot(state, snapshot(FakeReader(), 31), 5, OPTIONS)
        self.assertEqual([r["context"]["number"] for r in rows], [30, 31])
        self.assertEqual(state["nextSweepAt"], 305)

    def test_advance_goes_straight_to_the_new_frontier(self):
        timeline, emitted, reads = [], [], {}

        class Reader(FakeReader):
            def pull_request(self, context):
                n = context["number"]
                timeline.append(f"read:{n}")
                facts = super().pull_request(context)
                reads[n] = reads.get(n, 0) + 1
                if n == 40 and reads[n] > 1:
                    return {**facts, "state": "MERGED", "mergedAt": "2026-07-26T00:00:00Z"}
                return facts

        clock = FakeClock(stop_after_sleeps=2, timeline=timeline)
        with self.assertRaises(StopProof):
            pw.run_queued(deps(Reader(), clock, emitted, timeline), [ctx(40), ctx(41)], OPTIONS)
        advance = [e for e in emitted if e["kind"] == "ADVANCE"]
        self.assertEqual(len(advance), 1)
        self.assertEqual((advance[0]["merged"]["number"], advance[0]["frontier"]["number"], advance[0]["remaining"]),
                         (40, 41, 1))
        first = timeline.index("sleep")
        self.assertEqual(timeline[first:first + 5], ["sleep", "read:40", "emit:ADVANCE", "read:41", "emit:WAITING"])

    def test_identical_waits_are_reported_once_and_the_next_sweep_is_due(self):
        state = pw.create_queue_state([ctx(50)], 0)
        state, _ = pw.apply_queue_snapshot(state, snapshot(FakeReader(), 50), 0, OPTIONS)
        first = pw.evaluate_queue(state, 0, OPTIONS)
        self.assertEqual((first["kind"], first["emit"]), ("waiting", True))
        self.assertEqual(first["reason"], {"kind": "merge-queue", "unmergedCount": 1})
        second = pw.evaluate_queue(first["state"], 10, OPTIONS)
        self.assertEqual((second["kind"], second["emit"]), ("waiting", False))
        self.assertEqual(pw.plan_queue(second["state"], 300)["work"]["kind"], "whole-stack-sweep")
        self.assertEqual(pw.plan_queue(second["state"], 10)["work"]["kind"], "frontier-poll")

    def test_a_merged_queue_completes(self):
        emitted = []
        reader = FakeReader(facts={"state": "MERGED", "mergedAt": "t"})
        verdict = pw.run_queued(deps(reader, emitted=emitted), [ctx(1), ctx(2)], OPTIONS)
        self.assertEqual([e["kind"] for e in emitted], ["QUEUE", "STATUS"])
        self.assertEqual((verdict["kind"], verdict["exitCode"], verdict["mode"]), ("COMPLETE", 0, "queued-stack"))
        self.assertEqual([m["context"]["number"] for m in verdict["merged"]], [1, 2])

    def test_a_queued_blocker_and_a_queued_timeout(self):
        verdict = pw.run_queued(deps(FakeReader(facts={"mergeable": "CONFLICTING"})), [ctx(1)], OPTIONS)
        self.assertEqual((verdict["kind"], verdict["exitCode"]), ("BLOCKER", 2))
        clock = FakeClock()
        verdict = pw.run_queued(deps(FakeReader(), clock), [ctx(1), ctx(2)], {**OPTIONS, "timeout": 5})
        self.assertEqual((verdict["kind"], verdict["exitCode"]), ("TIMEOUT", 5))
        self.assertEqual(verdict["reason"], {"kind": "queued-stack", "frontier": ctx(1), "unmergedCount": 2})
        self.assertEqual(clock.sleeps, [10])

    def test_queued_pending_frontier_waits_on_its_own_checks(self):
        state = pw.create_queue_state([ctx(60)], 0)
        row = snapshot(FakeReader(fast_path={"kind": "checks", "checks": [pending("build")]}), 60)
        state, _ = pw.apply_queue_snapshot(state, row, 0, OPTIONS)
        wait = pw.evaluate_queue(state, 0, OPTIONS)
        self.assertEqual(wait["reason"]["kind"], "pending-checks")
        self.assertEqual(wait["state"]["lastWaitKey"], "pending:60:1")


class SimpleRunnerTest(unittest.TestCase):
    def test_pending_checks_time_out_with_exit_5(self):
        emitted, clock = [], FakeClock()
        reader = FakeReader(fast_path={"kind": "checks", "checks": [pending()]})
        verdict = pw.run_simple(deps(reader, clock, emitted), [ctx(1)], "single", False, {**OPTIONS, "timeout": 5})
        self.assertEqual([e["kind"] for e in emitted], ["WAITING", "WAITING"])
        self.assertEqual((verdict["kind"], verdict["exitCode"], verdict["reason"]["kind"]),
                         ("TIMEOUT", 5, "pending-checks"))
        self.assertEqual(clock.sleeps, [10])

    def test_github_undecided_is_read_again_not_ready(self):
        class Reader(FakeReader):
            reads = 0

            def pull_request(self, context):
                self.reads += 1
                facts = super().pull_request(context)
                return {**facts, "mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"} if self.reads < 3 else facts

        emitted, clock = [], FakeClock()
        verdict = pw.run_simple(deps(Reader(), clock, emitted), [ctx(1)], "single", False, OPTIONS)
        self.assertEqual([(e["kind"], e["reason"]["kind"]) for e in emitted],
                         [("WAITING", "github-undecided")] * 2)
        self.assertEqual((verdict["kind"], verdict["exitCode"], clock.sleeps), ("READY", 0, [10, 10]))
        stuck = pw.run_simple(deps(FakeReader(facts={"mergeable": "UNKNOWN"}), FakeClock()), [ctx(1)], "single",
                              False, {**OPTIONS, "timeout": 5})
        self.assertEqual((stuck["kind"], stuck["exitCode"], stuck["reason"]["kind"]),
                         ("TIMEOUT", 5, "github-undecided"))
        self.assertIn("GitHub never decided", pw.render_pretty(stuck))

    def test_status_only_reports_an_undecided_merge_as_waiting(self):
        emitted = []
        reader = FakeReader(facts={"mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"})
        verdict = pw.run_simple(deps(reader, emitted=emitted), [ctx(1)], "single", True, OPTIONS)
        self.assertEqual((verdict["kind"], verdict["exitCode"]), ("STATUS", 0))
        self.assertEqual([(e["kind"], e["terminal"], e["reason"]) for e in emitted],
                         [("WAITING", False, {"kind": "github-undecided", "mergeable": "UNKNOWN",
                                              "mergeStateStatus": "UNKNOWN"})])
        self.assertIn("GitHub has not decided", pw.render_pretty(emitted[0]))
        self.assertIn("| WAITING: GitHub has not decided |", pw.render_pretty(verdict))

    def test_a_queued_frontier_github_has_not_decided_is_not_merge_ready(self):
        state = pw.create_queue_state([ctx(70)], 0)
        state, _ = pw.apply_queue_snapshot(state, snapshot(FakeReader(facts={"mergeStateStatus": "UNKNOWN"}), 70),
                                           0, OPTIONS)
        wait = pw.evaluate_queue(state, 0, OPTIONS)
        self.assertEqual((wait["kind"], wait["reason"]["kind"]), ("waiting", "github-undecided"))

    def test_failed_reads_retry_with_backoff_then_exhaust_with_exit_7(self):
        class Reader(FakeReader):
            def pull_request(self, context):
                raise pw.WatcherQueryError({"kind": "command-exit", "retryable": True, "detail": "HTTP 502", "code": 1})

        emitted, clock = [], FakeClock()
        verdict = pw.run_simple(deps(Reader(), clock, emitted), [ctx(1)], "single", False,
                                {**OPTIONS, "max_query_errors": 3})
        self.assertEqual([(e["kind"], e["consecutiveFailures"], e["retryInSeconds"]) for e in emitted],
                         [("RETRY", 1, 60), ("RETRY", 2, 120)])
        self.assertEqual(clock.sleeps, [60, 120])
        self.assertEqual((verdict["exitCode"], verdict["blocker"]["kind"], verdict["blocker"]["failures"]),
                         (7, "status-query", 3))

    def test_a_failure_that_cannot_be_retried_stops_at_once(self):
        class Reader(FakeReader):
            def pull_request(self, context):
                raise pw.WatcherQueryError({"kind": "invalid-context-url", "retryable": False, "rawValue": "x",
                                            "detail": "bad url"})

        emitted = []
        verdict = pw.run_simple(deps(Reader(), emitted=emitted), [ctx(1)], "single", False, OPTIONS)
        self.assertEqual(emitted, [])
        self.assertEqual((verdict["exitCode"], verdict["blocker"]["failures"]), (7, 1))

    def test_retries_past_the_deadline_time_out(self):
        class Reader(FakeReader):
            def pull_request(self, context):
                raise pw.WatcherQueryError({"kind": "json-parse", "retryable": True, "detail": "bad json"})

        verdict = pw.run_simple(deps(Reader()), [ctx(1)], "single", False, {**OPTIONS, "timeout": 30})
        self.assertEqual((verdict["kind"], verdict["exitCode"], verdict["reason"]["kind"]),
                         ("TIMEOUT", 5, "status-unavailable"))

    def test_events_carry_the_envelope_in_order(self):
        emitted = []
        verdict = pw.run_simple(deps(FakeReader(), emitted=emitted), [ctx(1), ctx(2)], "stack", False, OPTIONS)
        events = emitted + [verdict]
        self.assertEqual([e["sequence"] for e in events], [1, 2])
        for event in events:
            self.assertEqual(list(event)[:6], ["schemaVersion", "sequence", "observedAt", "mode", "kind", "terminal"])
            self.assertEqual((event["schemaVersion"], event["observedAt"], event["mode"]), (1, OBSERVED, "stack"))
        self.assertEqual((emitted[0]["kind"], emitted[0]["terminal"], emitted[0]["reason"]), ("STATUS", False, "poll"))
        self.assertEqual((verdict["kind"], verdict["terminal"], verdict["exitCode"]), ("READY", True, 0))
        self.assertEqual(verdict["scope"]["kind"], "stack")


# ---------------------------------------------------------------------------------------------------------------
# github.test.ts


class ChecksFallbackTest(unittest.TestCase):
    def test_a_non_empty_fast_path_needs_no_rollup(self):
        reader = FakeReader(fast_path={"kind": "checks", "checks": [passing("fast")]})
        read = pw.resolve_checks(reader, ctx(42))
        self.assertEqual((read["source"], [c["name"] for c in read["checks"]]), ("gh-pr-checks", ["fast"]))
        self.assertEqual(reader.calls, ["checksFastPath"])

    def test_graphql_is_paginated_when_the_fast_path_is_unusable(self):
        reader = FakeReader(fast_path={"kind": "unusable", "exitCode": 8, "stderr": ""},
                            rollup_pages=[{"checks": [passing("first")], "endCursor": "next"},
                                          {"checks": [failed("second")], "endCursor": None}])
        read = pw.resolve_checks(reader, ctx(42))
        self.assertEqual((read["source"], [c["name"] for c in read["checks"]]), ("graphql-rollup", ["first", "second"]))
        self.assertEqual(reader.calls, ["checksFastPath", "checkRollupPage:null", "checkRollupPage:next"])

    def test_an_empty_fast_list_falls_back(self):
        reader = FakeReader(fast_path={"kind": "checks", "checks": []},
                            rollup_pages=[{"checks": [pending("fallback")], "endCursor": None}])
        self.assertEqual(pw.resolve_checks(reader, ctx(42))["checks"][0]["name"], "fallback")
        self.assertEqual(reader.calls, ["checksFastPath", "checkRollupPage:null"])

    def test_both_paths_empty_fail_closed(self):
        reader = FakeReader(fast_path={"kind": "unusable", "exitCode": 8, "stderr": "credential cannot read checks"})
        with self.assertRaises(pw.ChecksUnavailable) as caught:
            pw.resolve_checks(reader, ctx(42))
        self.assertIn("credential cannot read checks", caught.exception.failure["detail"])
        self.assertTrue(caught.exception.failure["retryable"])
        self.assertEqual(reader.calls, ["checksFastPath", "checkRollupPage:null"])


class RollupMappingTest(unittest.TestCase):
    def test_check_run_states_fail_closed(self):
        cases = [("IN_PROGRESS", None, "pending", "PENDING"), ("COMPLETED", "SUCCESS", "passed", "SUCCESS"),
                 ("COMPLETED", "NEUTRAL", "skipped", "NEUTRAL"), ("COMPLETED", "SKIPPED", "skipped", "SKIPPED"),
                 ("COMPLETED", "ACTION_REQUIRED", "failed", "ACTION_REQUIRED"),
                 ("COMPLETED", "TIMED_OUT", "failed", "FAILURE"), ("COMPLETED", "FUTURE_VALUE", "failed", "FAILURE")]
        for status, conclusion, kind, reported in cases:
            mapped = pw.map_rollup_node({"__typename": "CheckRun", "name": "ci", "status": status,
                                         "conclusion": conclusion})
            self.assertEqual((mapped["kind"], mapped["reportedState"]), (kind, reported), (status, conclusion))

    def test_an_in_progress_code_review_gate_is_the_gate(self):
        self.assertEqual(pw.map_rollup_node({"__typename": "CheckRun", "name": "Code Review Gate",
                                             "status": "IN_PROGRESS", "conclusion": None})["kind"], "code-review-gate")
        self.assertEqual(pw.map_rollup_node({"__typename": "StatusContext", "context": "Code Review Gate",
                                             "state": "PENDING"})["kind"], "code-review-gate")

    def test_a_gate_waiting_on_an_owner_approval_is_the_gate(self):
        mapped = pw.map_rollup_node({"__typename": "CheckRun", "name": "Code Review Gate", "status": "COMPLETED",
                                     "conclusion": "ACTION_REQUIRED", "description": "1 of 2 policies"})
        self.assertEqual((mapped["kind"], mapped["reportedState"]), ("code-review-gate", "ACTION_REQUIRED"))
        fast = pw.parse_fast_check({"name": "Code Review Gate", "state": "ACTION_REQUIRED", "bucket": "fail"})
        self.assertEqual((fast["kind"], fast["reportedState"]), ("code-review-gate", "ACTION_REQUIRED"))
        other = pw.parse_fast_check({"name": "ci", "state": "ACTION_REQUIRED", "bucket": "fail"})
        self.assertEqual((other["kind"], other["reportedState"]), ("failed", "ACTION_REQUIRED"))

    def test_a_configured_human_gate_is_a_gate_too(self):
        gates = pw.ReviewConfig(gate_checks=["Owner Approval"]).gate_checks
        self.assertIn("Code Review Gate", gates)
        self.assertEqual(pw.parse_fast_check({"name": "Owner Approval", "state": "PENDING", "bucket": "pending"},
                                             gates)["kind"], "code-review-gate")
        self.assertEqual(pw.parse_fast_check({"name": "Owner Approval", "state": "PENDING", "bucket": "pending"})["kind"],
                         "pending")
        reader = FakeReader(fast_path={"kind": "checks", "checks": [passing(), check(
            "code-review-gate", "Owner Approval", "PENDING")]})
        self.assertEqual(pw.classify_pr(snapshot(reader, 1, "include"))["kind"], "ready")

    def test_fast_check_buckets(self):
        def kind(state, bucket):
            return pw.parse_fast_check({"name": "ci", "state": state, "bucket": bucket})["kind"]
        self.assertEqual(kind("SUCCESS", "pass"), "passed")
        self.assertEqual(kind("skipped", "skipping"), "skipped")
        self.assertEqual(kind("IN_PROGRESS", "pending"), "pending")
        self.assertEqual(kind("ERROR", "pass"), "failed")
        self.assertEqual(kind("CANCELLED", "cancel"), "failed")
        self.assertEqual(pw.parse_fast_check({"name": "ci", "state": "success", "bucket": "pass",
                                              "link": "https://x", "workflow": "w"}),
                         {"name": "ci", "description": "", "link": "https://x", "workflow": "w", "kind": "passed",
                          "reportedState": "SUCCESS"})
        with self.assertRaises(pw.WatcherQueryError):
            pw.parse_fast_check({"name": "ci", "state": "SUCCESS"})

    def test_status_context_states_and_unknown_typenames(self):
        mapped = pw.map_rollup_node({"__typename": "StatusContext", "context": "ci", "state": "EXPECTED",
                                     "targetUrl": "https://ci"})
        self.assertEqual((mapped["kind"], mapped["reportedState"], mapped["link"]), ("pending", "PENDING", "https://ci"))
        future = pw.map_rollup_node({"__typename": "StatusContext", "context": "ci", "state": "FUTURE_VALUE"})
        self.assertEqual((future["kind"], future["reportedState"]), ("failed", "FUTURE_VALUE"))
        self.assertIsNone(pw.map_rollup_node({"__typename": "FutureNode"}))


RAW_PR = {"mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN", "reviewDecision": "APPROVED", "headRefOid": "head",
          "headRefName": "feature", "baseRefName": "main", "state": "OPEN", "mergedAt": None, "isDraft": False}


class ClosedEnumTest(unittest.TestCase):
    def test_conflicting_merge_state_is_known(self):
        facts = pw.parse_pull_request({**RAW_PR, "mergeStateStatus": "CONFLICTING"}, ctx(42))
        self.assertEqual(facts["mergeStateStatus"], "CONFLICTING")

    def test_an_empty_review_decision_is_no_decision(self):
        self.assertIsNone(pw.parse_pull_request({**RAW_PR, "reviewDecision": ""}, ctx(42))["reviewDecision"])
        self.assertIsNone(pw.parse_pull_request({**RAW_PR, "reviewDecision": None}, ctx(42))["reviewDecision"])

    def test_unknown_values_fail_closed_with_the_raw_value(self):
        with self.assertRaises(pw.WatcherQueryError):
            pw.parse_pull_request({**RAW_PR, "reviewDecision": "MAYBE"}, ctx(42))
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.parse_pull_request({**RAW_PR, "mergeStateStatus": "FUTURE_STATE"}, ctx(42))
        failure = caught.exception.failure
        self.assertEqual((failure["kind"], failure["retryable"], failure["rawValue"]),
                         ("missing-key", True, '"FUTURE_STATE"'))
        for key, value in (("mergeable", "MAYBE"), ("state", "DRAFTED"), ("isDraft", "no"), ("headRefName", None)):
            with self.assertRaises(pw.WatcherQueryError, msg=key):
                pw.parse_pull_request({**RAW_PR, key: value}, ctx(42))
        missing = dict(RAW_PR)
        del missing["state"]
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.parse_pull_request(missing, ctx(42))
        self.assertEqual(caught.exception.failure["detail"], "missing pull request.state")
        self.assertNotIn("rawValue", caught.exception.failure)


def thread_response(nodes, has_next=False, cursor=None):
    return {"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}}}}}


def thread_node(thread_id, body, author, resolved=False, path=None, line=None):
    return {"id": thread_id, "isResolved": resolved, "comments": {"nodes": [
        {"body": body, "createdAt": "now", "path": path, "line": line,
         "author": None if author is None else {"login": author}}]}}


class ReviewBotTest(unittest.TestCase):
    def test_bot_threads_carry_distinct_review_pass_counts(self):
        response = thread_response([thread_node("one", "RUN_ID: run-1", "bugbot", path="a.ts", line=1),
                                    thread_node("two", "CURSOR_AUTOMATION_ID: run-2 severity high", "cursor"),
                                    thread_node("resolved", "RUN_ID: run-3", "bugbot", resolved=True)])
        threads = pw.build_review_threads(pw.parse_review_thread_page(response)["threads"])
        self.assertEqual([t["id"] for t in threads], ["one", "two"])
        self.assertEqual([t["isReviewBot"] for t in threads], [True, True])
        self.assertEqual([t["reviewBotPasses"] for t in threads], [3, 3])

    def test_the_default_author_list_and_pass_key(self):
        response = thread_response([
            thread_node("rabbit", "Nitpick\nREVIEW_RUN: r-1", "coderabbitai[bot]"),
            thread_node("copilot", "Consider a guard here.", "Copilot-Pull-Request-Reviewer[bot]"),
            thread_node("actions", "REVIEW_RUN: r-2", "github-actions[bot]"),
            thread_node("human", "RUN_ID: not-a-bot", "alice"),
            thread_node("ghost", "RUN_ID: ghost", None)])
        threads = pw.build_review_threads(pw.parse_review_thread_page(response)["threads"])
        self.assertEqual([t["isReviewBot"] for t in threads], [True, True, True, False, False])
        self.assertEqual({t["reviewBotPasses"] for t in threads}, {2})

    def test_keyless_bot_threads_count_as_one_pass(self):
        keyless = [raw_thread("a", comment("bugbot", "a finding")), raw_thread("b", comment("bugbot", "another"))]
        self.assertEqual({t["reviewBotPasses"] for t in pw.build_review_threads(keyless)}, {1})
        humans = [raw_thread("a", comment("alice", "RUN_ID: x"))]
        self.assertEqual(pw.build_review_threads(humans)[0]["reviewBotPasses"], 0)

    def test_the_author_list_and_pass_key_are_configurable(self):
        config = pw.ReviewConfig(bot_authors="MyBot", pass_key=r"pass=(\d+)")
        threads = [raw_thread("a", comment("mybot-app", "pass=7 found x")), raw_thread("b", comment("mybot", "pass=8")),
                   raw_thread("c", comment("cursor", "RUN_ID: r"))]
        built = pw.build_review_threads(threads, config)
        self.assertEqual([t["isReviewBot"] for t in built], [True, True, False])
        self.assertEqual(built[0]["reviewBotPasses"], 2)
        whole = pw.ReviewConfig(pass_key=r"pass-[a-z]+")
        self.assertEqual(pw.review_pass_key(comment("bugbot", "see pass-alpha"), whole), "pass-alpha")
        off = pw.ReviewConfig(bot_authors="")
        self.assertEqual(off.bot_authors, ())
        self.assertFalse(pw.build_review_threads([raw_thread("a", comment("cursor", "x"))], off)[0]["isReviewBot"])


class ThreadPaginationTest(unittest.TestCase):
    def test_pages_are_walked_until_the_cursor_ends(self):
        reader = FakeReader(thread_pages=[{"threads": [raw_thread("one")], "endCursor": "next"},
                                          {"threads": [raw_thread("two")], "endCursor": "last"},
                                          {"threads": [raw_thread("three")], "endCursor": None}])
        self.assertEqual([t["id"] for t in pw.resolve_review_threads(reader, ctx(42))], ["one", "two", "three"])
        self.assertEqual(reader.calls, ["reviewThreadPage:null", "reviewThreadPage:next", "reviewThreadPage:last"])

    def test_an_unresolved_thread_past_the_first_page_is_seen(self):
        reader = FakeReader(thread_pages=[{"threads": [raw_thread("early", resolved=True)], "endCursor": "next"},
                                          {"threads": [raw_thread("late")], "endCursor": None}])
        self.assertEqual([t["id"] for t in pw.resolve_review_threads(reader, ctx(42))], ["late"])

    def test_a_single_page_stops(self):
        reader = FakeReader(thread_pages=[{"threads": [raw_thread("only")], "endCursor": None}])
        self.assertEqual(len(pw.resolve_review_threads(reader, ctx(42))), 1)
        self.assertEqual(reader.calls, ["reviewThreadPage:null"])

    def test_passes_are_counted_across_every_page(self):
        reader = FakeReader(thread_pages=[
            {"threads": [raw_thread("one", comment("bugbot", "RUN_ID: run-1"))], "endCursor": "next"},
            {"threads": [raw_thread("two", comment("bugbot", "RUN_ID: run-2"))], "endCursor": None}])
        self.assertEqual([t["reviewBotPasses"] for t in pw.resolve_review_threads(reader, ctx(42))], [2, 2])

    def test_resolved_threads_on_later_pages_are_dropped(self):
        reader = FakeReader(thread_pages=[{"threads": [raw_thread("one")], "endCursor": "next"},
                                          {"threads": [raw_thread("two", resolved=True)], "endCursor": None}])
        self.assertEqual([t["id"] for t in pw.resolve_review_threads(reader, ctx(42))], ["one"])

    def test_a_page_without_page_info_is_rejected(self):
        response = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
        with self.assertRaises(pw.WatcherQueryError):
            pw.parse_review_thread_page(response)
        with self.assertRaises(pw.WatcherQueryError):
            pw.parse_review_thread_page({"data": {"repository": None}})
        cursor = pw.parse_review_thread_page(thread_response([], has_next=True, cursor="c1"))
        self.assertEqual(cursor["endCursor"], "c1")
        bad_line = thread_response([thread_node("x", "b", "a", line="7")])
        with self.assertRaises(pw.WatcherQueryError):
            pw.parse_review_thread_page(bad_line)


class ContextAndStackTest(unittest.TestCase):
    def test_a_fully_explicit_context_reads_nothing(self):
        reader = FakeReader()
        self.assertEqual(pw.resolve_context(reader, "explicit", "repo", 42),
                         {"owner": "explicit", "repo": "repo", "number": 42})
        self.assertEqual(reader.calls, [])

    def test_the_local_origin_comes_before_current_pr(self):
        reader = FakeReader(origin={"owner": "local", "repo": "checkout"})
        self.assertEqual(pw.resolve_context(reader, None, None, 42), {"owner": "local", "repo": "checkout", "number": 42})
        self.assertEqual(reader.calls, ["originRepo"])
        no_origin = FakeReader(origin=None, current={"owner": "o", "repo": "r", "number": 9})
        self.assertEqual(pw.resolve_context(no_origin, None, None, None), {"owner": "o", "repo": "r", "number": 9})
        self.assertEqual(no_origin.calls, ["currentPr"])

    def test_the_connected_stack_is_ordered_bottom_to_top(self):
        open_prs = [{"number": 41, "headRefName": "base-feature", "baseRefName": "main"},
                    {"number": 42, "headRefName": "feature", "baseRefName": "base-feature"},
                    {"number": 43, "headRefName": "upstack", "baseRefName": "feature"},
                    {"number": 44, "headRefName": "upstack-b", "baseRefName": "feature"},
                    {"number": 45, "headRefName": "top", "baseRefName": "upstack"},
                    {"number": 50, "headRefName": "unrelated", "baseRefName": "main"}]
        self.assertEqual([c["number"] for c in pw.order_stack(ctx(42), open_prs)], [41, 42, 43, 45, 44])
        self.assertEqual(pw.order_stack(ctx(99), open_prs), [ctx(99)])

    def test_branches_based_on_each_other_do_not_loop(self):
        open_prs = [{"number": 1, "headRefName": "a", "baseRefName": "b"},
                    {"number": 2, "headRefName": "b", "baseRefName": "a"}]
        self.assertEqual([c["number"] for c in pw.order_stack(ctx(1), open_prs)], [2, 1])


# ---------------------------------------------------------------------------------------------------------------
# GhReader over a fake gh runner


def gh_kind(argv):
    if argv[:3] == ["gh", "pr", "view"]:
        return "view"
    if argv[:3] == ["gh", "pr", "checks"]:
        return "checks"
    if argv[:3] == ["gh", "pr", "list"]:
        return "list"
    if argv[:3] == ["gh", "api", "graphql"]:
        query = next(a for a in argv if a.startswith("query="))
        for name in ("ReviewThreads", "PrCommitStatuses", "PrCheckRollup"):
            if f"query {name}(" in query:
                return name
    if argv[:3] == ["git", "remote", "get-url"]:
        return "origin"
    raise AssertionError(f"unexpected command {argv}")


class FakeGh:
    """A gh runner: canned (exit code, stdout, stderr) per command kind; a list answers successive calls."""

    def __init__(self, **responses):
        self.responses, self.calls = responses, []

    def __call__(self, argv, cwd=None):
        self.calls.append(list(argv))
        answer = self.responses[gh_kind(argv)]
        if isinstance(answer, list):
            answer = answer.pop(0)
        code, out = answer[0], answer[1]
        out = out if isinstance(out, str) else json.dumps(out)
        return code, out, answer[2] if len(answer) > 2 else ""


def rollup_response(nodes, has_next=False, cursor=None, rollup="present"):
    commit = {"statusCheckRollup": None if rollup is None else {
        "contexts": {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}}}
    return {"data": {"repository": {"pullRequest": {"commits": {"nodes": [{"commit": commit}]}}}}}


def commits_response(*pairs):
    return {"data": {"repository": {"pullRequest": {"commits": {"nodes": [
        {"commit": {"oid": oid, "statusCheckRollup": None if state is None else {"state": state}}}
        for oid, state in pairs]}}}}}


class GhReaderTest(unittest.TestCase):
    def test_pull_request_command_and_parse(self):
        gh = FakeGh(view=(0, RAW_PR))
        facts = pw.GhReader(gh).pull_request(ctx(7))
        self.assertEqual(gh.calls, [["gh", "pr", "view", "7", "--repo", "owner/repo", "--json",
                                     pw.PULL_REQUEST_FIELDS]])
        self.assertEqual((facts["context"], facts["state"], facts["isDraft"]), (ctx(7), "OPEN", False))

    def test_command_and_json_failures_are_retryable_query_failures(self):
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.GhReader(FakeGh(view=(4, "", "HTTP 401: Bad credentials\nmore detail"))).pull_request(ctx(7))
        self.assertEqual(caught.exception.failure, {"kind": "command-exit", "retryable": True, "code": 4,
                                                    "detail": "HTTP 401: Bad credentials"})
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.GhReader(FakeGh(view=(1, "", ""))).pull_request(ctx(7))
        self.assertIn("exited 1", caught.exception.failure["detail"])
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.GhReader(FakeGh(view=(0, "not json"))).pull_request(ctx(7))
        self.assertEqual((caught.exception.failure["kind"], caught.exception.failure["retryable"]),
                         ("json-parse", True))

    def test_checks_fast_path_accepts_exit_0_1_and_8(self):
        listing = [{"name": "build", "state": "IN_PROGRESS", "bucket": "pending", "description": "", "link": "l",
                    "workflow": "w"}]
        for code in (0, 1, 8):
            result = pw.GhReader(FakeGh(checks=(code, listing))).checks_fast_path(ctx(7))
            self.assertEqual((result["kind"], result["checks"][0]["kind"]), ("checks", "pending"), code)
        for answer in [(2, listing, "boom"), (0, ""), (0, {"not": "a list"}), (0, [{"name": "x"}]), (8, "garbage")]:
            result = pw.GhReader(FakeGh(checks=answer)).checks_fast_path(ctx(7))
            self.assertEqual(result["kind"], "unusable", answer)
        result = pw.GhReader(FakeGh(checks=(2, "", "boom"))).checks_fast_path(ctx(7))
        self.assertEqual(result, {"kind": "unusable", "exitCode": 2, "stderr": "boom"})

    def test_check_rollup_pages_and_cursor(self):
        gh = FakeGh(PrCheckRollup=[
            (0, rollup_response([{"__typename": "CheckRun", "name": "a", "status": "COMPLETED", "conclusion": "SUCCESS",
                                  "detailsUrl": "https://a"}, {"__typename": "Other"}], True, "c1")),
            (0, rollup_response([{"__typename": "StatusContext", "context": "b", "state": "ERROR"}]))])
        reader = pw.GhReader(gh)
        first = reader.check_rollup_page(ctx(7), None)
        self.assertEqual(([c["name"] for c in first["checks"]], first["endCursor"]), (["a"], "c1"))
        self.assertEqual(first["checks"][0]["link"], "https://a")
        second = reader.check_rollup_page(ctx(7), "c1")
        self.assertEqual((second["checks"][0]["kind"], second["endCursor"]), ("failed", None))
        self.assertNotIn("after=c1", gh.calls[0])
        self.assertEqual(gh.calls[1][-2:], ["-f", "after=c1"])
        self.assertIn("-F", gh.calls[0])
        self.assertIn("pr=7", gh.calls[0])
        empty = pw.GhReader(FakeGh(PrCheckRollup=(0, rollup_response([], rollup=None)))).check_rollup_page(ctx(7), None)
        self.assertEqual(empty, {"checks": [], "endCursor": None})

    def test_commit_rollups_fail_closed_on_an_unknown_state(self):
        rollups = pw.GhReader(FakeGh(PrCommitStatuses=(0, commits_response(("a", "SUCCESS"), ("b", None)))))
        self.assertEqual(rollups.commit_rollups(ctx(7)), [{"oid": "a", "state": "SUCCESS"}, {"oid": "b", "state": None}])
        with self.assertRaises(pw.WatcherQueryError) as caught:
            pw.GhReader(FakeGh(PrCommitStatuses=(0, commits_response(("a", "FUTURE"))))).commit_rollups(ctx(7))
        self.assertEqual(caught.exception.failure["rawValue"], '"FUTURE"')

    def test_current_pr_reads_the_canonical_url(self):
        gh = FakeGh(view=(0, {"number": 12, "url": "https://github.com/acme/app/pull/12"}))
        self.assertEqual(pw.GhReader(gh).current_pr(None), {"owner": "acme", "repo": "app", "number": 12})
        self.assertEqual(gh.calls, [["gh", "pr", "view", "--json", "number,url"]])
        for url in ("https://gitlab.com/acme/app/pull/12", "https://github.com/acme/app/issues/12",
                    "http://github.com/acme/app/pull/12", "https://github.com/acme/app/pull/12?x=1",
                    "https://github.com/acme/app/pull/zero"):
            with self.assertRaises(pw.WatcherQueryError) as caught:
                pw.GhReader(FakeGh(view=(0, {"number": 12, "url": url}))).current_pr(None)
            failure = caught.exception.failure
            self.assertEqual((failure["kind"], failure["retryable"], failure["rawValue"]),
                             ("invalid-context-url", False, url))

    def test_open_pull_requests_and_origin(self):
        listing = [{"number": 3, "headRefName": "b", "baseRefName": "main"}]
        self.assertEqual(pw.GhReader(FakeGh(list=(0, listing))).open_pull_requests({"owner": "o", "repo": "r"}),
                         listing)
        with self.assertRaises(pw.WatcherQueryError):
            pw.GhReader(FakeGh(list=(0, [{"number": 0, "headRefName": "b", "baseRefName": "m"}]))).open_pull_requests(
                {"owner": "o", "repo": "r"})
        remotes = {"git@github.com:acme/app.git\n": {"owner": "acme", "repo": "app"},
                   "ssh://git@github.com/acme/app": {"owner": "acme", "repo": "app"},
                   "https://github.com/acme/app.git": {"owner": "acme", "repo": "app"},
                   "https://gitlab.com/acme/app": None, "https://github.com/acme/app/extra": None,
                   "https://user@github.com/acme/app": None}
        for remote, expected in remotes.items():
            self.assertEqual(pw.GhReader(FakeGh(origin=(0, remote))).origin_repo(), expected, remote)
        self.assertIsNone(pw.GhReader(FakeGh(origin=(2, "", "no remote"))).origin_repo())

    def test_comment_text_stays_data(self):
        hostile = "\x1b[31m$(touch /tmp/pwned) `rm -rf ~`; echo \"x\" | sh\nsecond line"
        gh = FakeGh(ReviewThreads=(0, thread_response([thread_node("t1", hostile, "bugbot", path="a.py", line=3)])))
        page = pw.GhReader(gh).review_thread_page(ctx(7), None)
        self.assertEqual(page["threads"][0]["firstComment"]["body"], hostile)
        for argv in gh.calls:
            self.assertIsInstance(argv, list)
            self.assertFalse(any("pwned" in a for a in argv))
        threads = pw.build_review_threads(page["threads"])
        rendered = pw.render_pretty({"kind": "BLOCKER", "blocker": {"kind": "review-threads", "pr": ctx(7),
                                                                    "threads": threads}})
        self.assertIn("isReviewBot=true reviewBotPasses=1 ?[31m$(touch /tmp/pwned)", rendered)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("second line", rendered)

    def test_main_through_the_gh_reader(self):
        listing = [{"name": "test", "state": "FAILURE", "bucket": "fail", "description": "2 failed",
                    "link": "https://ci/1", "workflow": "ci"}]
        gh = FakeGh(view=(0, RAW_PR), ReviewThreads=(0, thread_response([])), checks=(1, listing),
                    PrCommitStatuses=(0, commits_response(("head", "FAILURE"))))
        out = []
        runtime = pw.Runtime(pw.GhReader(gh), FakeClock(), out.append, out.append)
        self.assertEqual(pw.main(["--owner", "acme", "--repo", "app", "--pr", "7"], runtime), 4)
        verdict = json.loads(out[0])
        self.assertEqual((verdict["blocker"]["kind"], verdict["blocker"]["ci"]["failed"][0]["link"]),
                         ("failing-checks", "https://ci/1"))
        self.assertTrue(all(argv[0] == "gh" for argv in gh.calls))


# ---------------------------------------------------------------------------------------------------------------
# cli.test.ts


def harness(reader):
    out, err = [], []
    clock = FakeClock(stop_after_sleeps=0)
    return pw.Runtime(reader, clock, out.append, err.append), out, err


class ParseArgsTest(unittest.TestCase):
    def test_the_defaults(self):
        options = pw.parse_args([])
        self.assertEqual({k: options[k] for k in ("owner", "repo", "pr", "mode", "stack_prs", "status_only", "pretty")},
                         {"owner": None, "repo": None, "pr": None, "mode": "single", "stack_prs": [],
                          "status_only": False, "pretty": False})
        self.assertEqual(options["polling"], {"interval": 60, "sweep_interval": 300, "timeout": 0,
                                              "max_query_errors": 5, "allow_draft": False})
        self.assertEqual(options["review"].bot_authors,
                         ("cursor", "bugbot", "coderabbitai", "copilot-pull-request-reviewer", "github-actions"))
        self.assertEqual(options["review"].pass_key.pattern, r"(RUN_ID|CURSOR_AUTOMATION_ID|REVIEW_RUN):\s*(\S+)")
        self.assertEqual(options["review"].gate_checks, frozenset({"Code Review Gate"}))

    def test_a_frozen_queued_stack(self):
        options = pw.parse_args(["--queued-stack", "--stack-prs", "#10, 11,#12", "--interval", "2.5",
                                 "--sweep-interval", "30", "--timeout=0", "--max-query-errors", "3", "--allow-draft",
                                 "--pretty", "--human-gate-check", "Owner Approval", "--human-gate-check", "Sign-off",
                                 "--review-bot-authors", "mybot", "--pr", "#10"])
        self.assertEqual((options["mode"], options["stack_prs"], options["pr"]), ("queued-stack", [10, 11, 12], 10))
        self.assertEqual(options["polling"], {"interval": 2.5, "sweep_interval": 30, "timeout": 0,
                                              "max_query_errors": 3, "allow_draft": True})
        self.assertTrue(options["pretty"])
        self.assertEqual(options["review"].gate_checks, frozenset({"Code Review Gate", "Owner Approval", "Sign-off"}))
        self.assertEqual(options["review"].bot_authors, ("mybot",))
        self.assertEqual(pw.parse_args(["--stack"])["mode"], "stack")

    def test_every_invalid_shape_is_usage(self):
        invalid = [["--unknown"], ["--interval", "0"], ["--sweep-interval", "-1"], ["--timeout", "-1"],
                   ["--max-query-errors", "1.5"], ["--stack", "--queued-stack"], ["--stack-prs", "1,2"],
                   ["--queued-stack", "--stack-prs", "1,1"], ["--queued-stack", "--stack-prs", "1,,2"],
                   ["--pr", "abc"], ["--pr", "0"], ["--pr"], ["--interval", "nan"], ["--timeout", "Infinity"],
                   ["--review-bot-pass-key", "(unclosed"], ["--human-gate-check", " "], ["--stack=yes"], ["12"]]
        for argv in invalid:
            runtime, out, err = harness(FakeReader())
            self.assertEqual(pw.main(argv, runtime), 64, argv)
            self.assertEqual(out, [], argv)
            self.assertIn("error:", "".join(err), argv)
            self.assertEqual(runtime.reader.calls, [], argv)

    def test_a_usage_error_names_the_option(self):
        runtime, out, err = harness(FakeReader())
        self.assertEqual(pw.main(["--interval", "0"], runtime), 64)
        self.assertIn("option '--interval <seconds>' argument '0' is invalid", "".join(err))


STATUS = {"schemaVersion": 1, "sequence": 1, "observedAt": OBSERVED, "mode": "single", "kind": "STATUS",
          "terminal": True, "exitCode": 0, "reason": "status-only",
          "rows": [{"kind": "merged", "context": ctx(1), "facts": {"context": ctx(1), **RAW_PR, "state": "MERGED",
                                                                    "mergedAt": "now"}}]}


class RenderTest(unittest.TestCase):
    def test_compact_valid_json_by_default(self):
        rendered = pw.render_json(STATUS)
        self.assertTrue(rendered.endswith("\n"))
        self.assertEqual(rendered.count("\n"), 1)
        self.assertEqual(json.loads(rendered), STATUS)

    def test_the_markdown_table_from_the_same_verdict(self):
        rendered = pw.render_pretty(STATUS)
        self.assertIn("| PR | CI | Review | Merge |", rendered)
        self.assertIn("| [#1](https://github.com/owner/repo/pull/1) | - | - | merged |", rendered)

    def test_every_event_renders_as_plain_text(self):
        runtime, out, _ = harness(FakeReader(facts={"isDraft": True}))
        self.assertEqual(pw.main(["--owner", "owner", "--repo", "repo", "--pr", "1", "--allow-draft", "--pretty"],
                                 runtime), 0)
        self.assertIn("note=draft allowed (--allow-draft)", out[0])
        self.assertIn("reviewDecision=APPROVED", out[0])
        rows = [snapshot(FakeReader(fast_path={"kind": "checks", "checks": [failed(), pending()]},
                                    commit_rollups=[{"oid": "x", "state": "SUCCESS"}]), 1, "include")]
        events = [
            {"kind": "QUEUE", "queue": [ctx(1), ctx(2)]}, {"kind": "STATUS", "rows": rows},
            {"kind": "WAITING", "frontier": ctx(1), "reason": {"kind": "pending-checks", "pending": [pending()]}},
            {"kind": "WAITING", "frontier": ctx(1), "reason": {"kind": "merge-queue", "unmergedCount": 2}},
            {"kind": "ADVANCE", "merged": ctx(1), "frontier": ctx(2), "remaining": 1},
            {"kind": "RETRY", "retryInSeconds": 60, "failure": {"detail": "HTTP 502"}},
            {"kind": "COMPLETE", "queue": [ctx(1)]},
            {"kind": "TIMEOUT", "reason": {"kind": "queued-stack", "frontier": ctx(2), "unmergedCount": 1}},
            {"kind": "BLOCKER", "blocker": {"kind": "status-query", "failures": 3, "failure": {"detail": "x"}}},
            {"kind": "BLOCKER", "blocker": {"kind": "merge-gate", "pr": ctx(1), "reason": "draft-pr"}}]
        text = "".join(pw.render_pretty(e) for e in events)
        self.assertIn("1 failed, 1 pending, was passing", text)
        self.assertIn("QUEUE: captured 2 PRs bottom-to-top: #1,#2", text)
        self.assertIn("WAITING: frontier=#1; 1 check pending", text)
        self.assertIn("ADVANCE: merged #1; next=#2; remaining=1", text)
        self.assertIn("TIMEOUT: queued stack still has 1 PR unmerged; frontier=#2", text)
        self.assertFalse(any(ord(ch) > 127 for ch in text), "plain text only")
        with self.assertRaises(RuntimeError):
            pw.render_pretty({"kind": "SOMETHING_NEW"})


class MainTest(unittest.TestCase):
    def run_main(self, argv, reader):
        runtime, out, err = harness(reader)
        code = pw.main(argv, runtime)
        return code, [json.loads(line) for line in out], err

    def test_queued_stack_status_only_skips_the_queue_machine(self):
        code, out, _ = self.run_main(["--owner", "owner", "--repo", "repo", "--queued-stack", "--stack-prs", "1",
                                      "--status-only"], FakeReader())
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["kind"], out[0]["terminal"], out[0]["exitCode"], out[0]["mode"]),
                         ("STATUS", True, 0, "queued-stack"))

    def test_status_only_exits_0_even_when_blocked(self):
        code, out, _ = self.run_main(["--pr", "1", "--status-only"], FakeReader(facts={"mergeable": "CONFLICTING"}))
        self.assertEqual((code, out[0]["kind"], out[0]["mode"]), (0, "STATUS", "single"))

    def test_a_hidden_github_refusal_exits_4(self):
        reader = FakeReader(facts={"mergeStateStatus": "BLOCKED"}, commit_rollups=[{"oid": "head", "state": "FAILURE"}])
        code, out, _ = self.run_main(["--owner", "owner", "--repo", "repo", "--pr", "1"], reader)
        self.assertEqual(code, 4)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["kind"], out[0]["exitCode"], out[0]["blocker"]["ci"]["kind"]),
                         ("BLOCKER", 4, "ci-github-rejected"))

    def test_one_exit_code_per_blocker_class(self):
        cases = [({"facts": {"mergeable": "CONFLICTING"}}, 2, "merge-conflicts"),
                 ({"threads": [{"id": "t", "firstComment": comment()}]}, 3, "review-threads"),
                 ({"fast_path": {"kind": "checks", "checks": [failed()]}}, 4, "failing-checks"),
                 ({"facts": {"isDraft": True}}, 6, "merge-gate"),
                 ({"facts": {"state": "CLOSED"}}, 6, "merge-gate"),
                 ({"facts": {"mergeStateStatus": "BEHIND"}}, 6, "merge-gate"),
                 ({"facts": {"mergeStateStatus": "BLOCKED", "reviewDecision": "REVIEW_REQUIRED"}}, 6, "merge-gate")]
        for kwargs, expected, kind in cases:
            code, out, _ = self.run_main(["--pr", "1"], FakeReader(**kwargs))
            self.assertEqual((code, out[-1]["exitCode"], out[-1]["blocker"]["kind"]), (expected, expected, kind))
        code, out, _ = self.run_main(["--pr", "1"], FakeReader())
        self.assertEqual((code, out[0]["kind"], out[0]["scope"]["kind"]), (0, "READY", "single"))
        code, out, _ = self.run_main(["--pr", "1"], FakeReader(facts={"state": "MERGED", "mergedAt": "t"}))
        self.assertEqual((code, out[0]["scope"]["pr"]["kind"]), (0, "merged-pr"))

    def test_an_unreadable_context_exits_7(self):
        class Reader(FakeReader):
            def current_pr(self, pr):
                raise pw.WatcherQueryError({"kind": "command-exit", "retryable": True, "code": 1,
                                            "detail": "no pull requests found for branch"})

        code, out, _ = self.run_main([], Reader(origin=None))
        self.assertEqual(code, 7)
        self.assertEqual((out[0]["sequence"], out[0]["blocker"]["failures"], out[0]["blocker"]["failure"]["detail"]),
                         (1, 1, "no pull requests found for branch"))

    def test_stack_mode_discovers_the_connected_stack(self):
        reader = FakeReader(open_prs=[{"number": 41, "headRefName": "base", "baseRefName": "main"},
                                      {"number": 42, "headRefName": "feature", "baseRefName": "base"}])
        code, out, _ = self.run_main(["--pr", "42", "--stack", "--status-only"], reader)
        self.assertEqual((code, [r["context"]["number"] for r in out[0]["rows"]]), (0, [41, 42]))
        code, out, _ = self.run_main(["--pr", "42", "--stack"], reader)
        self.assertEqual([(e["kind"], e["terminal"]) for e in out], [("STATUS", False), ("READY", True)])

    def test_help_touches_nothing(self):
        for flag in ("--help", "-h"):
            reader = FakeReader()
            runtime, out, _ = harness(reader)
            self.assertEqual(pw.main([flag], runtime), 0)
            self.assertIn("JSON (NDJSON while polling)", "".join(out))
            self.assertEqual(reader.calls, [])


class ScriptTest(unittest.TestCase):
    def test_help_and_usage_from_the_command_line(self):
        for args in (["--help"], ["-h"], ["land-check", "--help"]):
            out = subprocess.run([sys.executable, str(WATCH), *args], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, args)
            self.assertIn("pr_watch.py", out.stdout)
            for word in ("Exit codes", "--review-bot-authors", "--human-gate-check", "land-check", "schemaVersion"):
                self.assertIn(word, out.stdout)
        out = subprocess.run([sys.executable, str(WATCH), "--bogus"], capture_output=True, text=True, timeout=60)
        self.assertEqual((out.returncode, out.stdout), (64, ""))
        self.assertIn("unknown option '--bogus'", out.stderr)

    def test_a_failing_gh_is_a_status_query_blocker(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "gh"
            fake.write_text("#!/bin/sh\necho 'gh: not logged in' >&2\nexit 4\n")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "HOME": d, **GIT_ENV}
            out = subprocess.run([sys.executable, str(WATCH), "--owner", "o", "--repo", "r", "--pr", "1",
                                  "--max-query-errors", "1"], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(out.returncode, 7, out.stderr)
        verdict = json.loads(out.stdout)
        self.assertEqual((verdict["blocker"]["failure"]["detail"], verdict["blocker"]["failure"]["code"]),
                         ("gh: not logged in", 4))


# ---------------------------------------------------------------------------------------------------------------
# land-check


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def acceptance(did, milestone, fp, owner=True, title=None):
    source = f'Source: [owner 2026-10-01] "Yes, accept {milestone}. It works."' if owner else "Source: [proposed]"
    return (f"\n## {did} · 2026-10-01 · {title or 'Accept ' + milestone}\n"
            f"Accept {milestone} · contract 0123456789abcdef · fingerprint {fp} · review "
            f"reviews/{milestone}.md\n{source}\n")


SID = "11111111-2222-3333-4444-555555555555"


def prove(project, home):
    """Record a rulings.py proof for every owner entry in the project's decisions.md, from a transcript in which
    the owner typed each quoted sentence."""
    import re
    text = (Path(project) / "docs/project/decisions.md").read_text(encoding="utf-8")
    pairs = []
    for block in re.split(r"(?m)^(?=## D-)", text):
        head, quote = re.match(r"## (D-\d+)", block), re.search(r'\[owner [\d-]+\] "([^"]+)"', block)
        if head and quote:
            pairs.append((head.group(1), quote.group(1)))
    transcript = Path(home) / ".claude/projects/p" / f"{SID}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("".join(json.dumps({"type": "user", "uuid": f"u{i}", "timestamp": "t",
                                              "message": {"content": quote}}) + "\n"
                                  for i, (_, quote) in enumerate(pairs)), encoding="utf-8")
    for did, quote in pairs:
        subprocess.run([sys.executable, str(SCRIPTS / "rulings.py"), "record", str(project), "--id", did, "--quote",
                        quote, "--session", SID], env={**os.environ, "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"},
                       capture_output=True, text=True, check=True)


def milestones(project, **statuses):
    (Path(project) / "docs/project/milestones.md").write_text("# Milestones\n" + "".join(
        f"\n## {mid} · Part {mid}\nStatus: {status}\nPromise: x\n" for mid, status in statuses.items()),
        encoding="utf-8")


class AcceptedFingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"
        self.home = Path(self.tmp.name) / "home"
        (self.project / "docs/project").mkdir(parents=True)
        milestones(self.project, M1="accepted", M10="accepted", M2="building")

    def tearDown(self):
        self.tmp.cleanup()

    def decisions(self, text, proven=True):
        (self.project / "docs/project/decisions.md").write_text("# Decisions\n" + text, encoding="utf-8")
        if proven:
            prove(self.project, self.home)

    def refused(self, milestone="M1"):
        with self.assertRaises(pw.LandCheckError) as caught:
            pw.accepted_fingerprint(self.project, milestone)
        return str(caught.exception)

    def test_the_latest_owner_acceptance_of_that_milestone(self):
        self.decisions(acceptance("D-003", "M1", "product:1111111111111111")
                       + acceptance("D-004", "M10", "product:aaaaaaaaaaaaaaaa")
                       + acceptance("D-005", "M1", "product:2222222222222222", title="decision")
                       + acceptance("D-006", "M1", "product:3333333333333333", owner=False))
        self.assertEqual(pw.accepted_fingerprint(self.project, "M1"), ("D-005", "product:2222222222222222"))
        self.assertEqual(pw.accepted_fingerprint(self.project, "M10"), ("D-004", "product:aaaaaaaaaaaaaaaa"))

    def test_an_owner_source_rulings_cannot_prove_is_refused(self):
        self.decisions(acceptance("D-005", "M1", "product:1111111111111111"), proven=False)
        self.assertIn("D-005 of M1 is not a proven owner ruling", self.refused())

    def test_an_acceptance_a_later_proven_entry_supersedes_is_refused(self):
        reopen = ('\n## D-006 · 2026-10-02 · Reopen M1: the export loses rows\n'
                  "Decision: M1 goes back to building.\nSupersedes: D-005\n"
                  'Source: [owner 2026-10-02] "Reopen M1, the export loses rows."\n')
        self.decisions(acceptance("D-005", "M1", "product:1111111111111111") + reopen)
        self.assertIn("superseded by D-006", self.refused())
        proposed = reopen.replace('Source: [owner 2026-10-02] "Reopen M1, the export loses rows."', "Source: [proposed]")
        self.decisions(acceptance("D-005", "M1", "product:1111111111111111") + proposed)
        self.assertEqual(pw.accepted_fingerprint(self.project, "M1")[0], "D-005", "a proposal supersedes nothing")

    def test_the_milestone_must_be_accepted_in_milestones_md(self):
        self.decisions(acceptance("D-005", "M2", "product:1111111111111111"))
        self.assertIn("milestones.md shows M2 with Status building, not accepted", self.refused("M2"))
        self.decisions(acceptance("D-005", "M7", "product:1111111111111111"))
        self.assertIn("shows M7 with no Status", self.refused("M7"))
        milestones(self.project, M2="Accepted")
        self.decisions(acceptance("D-005", "M2", "product:1111111111111111"))
        self.assertEqual(pw.accepted_fingerprint(self.project, "M2")[0], "D-005", "read without case")

    def test_only_the_fixed_form_is_an_acceptance(self):
        self.decisions('\n## D-007 · 2026-10-01 · Do not Accept M1 until the export is fixed\n'
                       "Decision: hold back the candidate with fingerprint product:1111111111111111.\n"
                       'Source: [owner 2026-10-01] "Do not accept M1 yet."\n')
        self.assertIn("no owner acceptance of M1", self.refused())

    def test_missing_proposed_or_unfingerprinted_acceptances_are_refused(self):
        with self.assertRaises(pw.LandCheckError):
            pw.accepted_fingerprint(self.project, "M1")
        self.decisions(acceptance("D-002", "M1", "product:1111111111111111", owner=False))
        with self.assertRaises(pw.LandCheckError) as caught:
            pw.accepted_fingerprint(self.project, "M1")
        self.assertIn("D-002", str(caught.exception))
        self.decisions('\n## D-002 · 2026-10-01 · Accept M1\nAccept M1 · contract 0123456789abcdef\n'
                       'Source: [owner 2026-10-01] "Accept M1, the fingerprint is fine."\n')
        with self.assertRaises(pw.LandCheckError) as caught:
            pw.accepted_fingerprint(self.project, "M1")
        self.assertIn("names no fingerprint", str(caught.exception))


class LandCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patch = mock.patch.dict(os.environ, {**GIT_ENV, "HOME": str(d / "home")})
        self.patch.start()
        self.origin, self.project, self.other, self.wt_root = d / "origin.git", d / "project", d / "other", d / "wt"
        self.wt_root.mkdir()
        git("init", "-q", "--bare", "-b", "main", str(self.origin))
        git("clone", "-q", str(self.origin), str(self.project))
        (self.project / "app.py").write_text("print('v1')\n")
        git("add", "app.py", cwd=self.project)
        git("commit", "-qm", "v1", cwd=self.project)
        git("branch", "-M", "main", cwd=self.project)
        git("push", "-q", "origin", "main", cwd=self.project)
        git("checkout", "-qb", "feature", cwd=self.project)
        (self.project / "app.py").write_text("print('v2')\n")
        (self.project / "tool.sh").write_text("echo hi\n")
        (self.project / "tool.sh").chmod(0o755)
        git("add", "app.py", "tool.sh", cwd=self.project)
        git("commit", "-qm", "v2", cwd=self.project)
        git("push", "-q", "origin", "feature", cwd=self.project)
        self.head = git("rev-parse", "HEAD", cwd=self.project)
        # The owner accepted this working tree at the gate: the planning folder is not part of the product.
        (self.project / "docs/project").mkdir(parents=True)
        (self.project / "docs/project/state.md").write_text("# State\n")
        milestones(self.project, M1="accepted", M2="accepted")
        self.accepted = fingerprint_mod.fingerprint(self.project, "product")[0]
        self.write_decisions(acceptance("D-005", "M1", self.accepted))
        git("checkout", "-q", "main", cwd=self.project)
        self.gh_calls, self.git_calls = [], []

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write_decisions(self, text, proven=True):
        (self.project / "docs/project/decisions.md").write_text("# Decisions\n" + text)
        if proven:
            prove(self.project, Path(self.tmp.name) / "home")

    def runner(self, oid, ref="feature", gh_code=0):
        def run(argv, cwd=None):
            if argv[0] == "gh":
                self.gh_calls.append((list(argv), cwd))
                return gh_code, json.dumps({"headRefOid": oid, "headRefName": ref}), "gh failed" if gh_code else ""
            self.git_calls.append(list(argv))
            return pw.run_command(argv, cwd)
        return run

    def land(self, *args, run=None, fingerprint_fn=None):
        out, err = [], []
        code = pw.land_check_main(list(args), run or self.runner(self.head), self.wt_root, fingerprint_fn,
                                  out.append, err.append)
        return code, "".join(out), "".join(err)

    def assert_cleaned_up(self):
        self.assertEqual(list(self.wt_root.iterdir()), [])
        listed = git("worktree", "list", "--porcelain", cwd=self.project)
        self.assertEqual(listed.count("worktree "), 1, listed)

    def test_the_accepted_head_matches(self):
        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"pr": 12, "head": self.head, "milestone": "M1",
                                           "accepted_fingerprint": self.accepted, "head_fingerprint": self.accepted,
                                           "match": True})
        self.assertEqual(self.gh_calls, [(["gh", "pr", "view", "12", "--json", "headRefOid,headRefName"],
                                          str(self.project))])
        self.assertFalse(any("fetch" in argv for argv in self.git_calls), "a present commit is not fetched")
        self.assert_cleaned_up()

    def test_a_changed_head_is_fetched_and_does_not_match(self):
        git("clone", "-q", "-b", "feature", str(self.origin), str(self.other))
        (self.other / "app.py").write_text("print('v3')\n")
        git("commit", "-qam", "v3", cwd=self.other)
        git("push", "-q", "origin", "feature", cwd=self.other)
        changed = git("rev-parse", "HEAD", cwd=self.other)
        missing = subprocess.run(["git", "-C", str(self.project), "cat-file", "-e", f"{changed}^{{commit}}"],
                                 capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        code, out, err = self.land("#12", "--project", str(self.project), "--milestone=M1",
                                   run=self.runner(changed))
        self.assertEqual(code, 1, err)
        result = json.loads(out)
        self.assertEqual((result["head"], result["accepted_fingerprint"], result["match"]),
                         (changed, self.accepted, False))
        self.assertNotEqual(result["head_fingerprint"], self.accepted)
        self.assertIn(pw.LAND_MISMATCH, err)
        self.assertIn("D-005", err)
        self.assertIn(["git", "-C", str(self.project), "fetch", "--quiet", "--no-tags", "origin", changed],
                      self.git_calls)
        self.assert_cleaned_up()

    def test_the_branch_is_fetched_when_the_commit_cannot_be(self):
        # A new commit that touches only planning files: a new head, the same product.
        git("clone", "-q", "-b", "feature", str(self.origin), str(self.other))
        (self.other / "docs/project").mkdir(parents=True)
        (self.other / "docs/project/notes.md").write_text("notes\n")
        git("add", "docs/project/notes.md", cwd=self.other)
        git("commit", "-qm", "notes", cwd=self.other)
        git("push", "-q", "origin", "feature", cwd=self.other)
        changed = git("rev-parse", "HEAD", cwd=self.other)

        def run(argv, cwd=None):
            if argv[0] == "git" and "fetch" in argv and argv[-1] in (changed, "refs/pull/12/head"):
                self.git_calls.append(list(argv))
                return 128, "", f"fatal: couldn't find remote ref {argv[-1]}"
            return self.runner(changed)(argv, cwd)

        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1", run=run)
        self.assertEqual(code, 0, err)
        self.assertEqual((json.loads(out)["head"], json.loads(out)["match"]), (changed, True))
        self.assertEqual([argv[-1] for argv in self.git_calls if "fetch" in argv],
                         [changed, "refs/pull/12/head", "refs/heads/feature"])

    def test_no_owner_acceptance_stops_before_github(self):
        self.write_decisions(acceptance("D-005", "M1", self.accepted, owner=False)
                             + acceptance("D-006", "M2", self.accepted))
        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no owner acceptance of M1", err)
        code, _, err = self.land("12", "--project", str(self.project), "--milestone", "M3")
        self.assertEqual(code, 2)
        self.assertEqual(self.gh_calls, [])
        (self.project / "docs/project/decisions.md").unlink()
        code, _, err = self.land("12", "--project", str(self.project), "--milestone", "M1")
        self.assertEqual(code, 2)
        self.assertIn("no acceptance of M1", err)

    def test_an_unproven_acceptance_stops_before_github(self):
        self.write_decisions(acceptance("D-005", "M1", self.accepted), proven=False)
        (self.project / ".evidence/rulings.jsonl").unlink(missing_ok=True)
        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("D-005 of M1 is not a proven owner ruling", err)
        self.assertEqual(self.gh_calls, [])

    def test_the_newest_acceptance_is_the_one_compared(self):
        self.write_decisions(acceptance("D-005", "M1", self.accepted)
                             + acceptance("D-009", "M1", "product:0000000000000000"))
        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1")
        self.assertEqual(code, 1, err)
        self.assertEqual(json.loads(out)["accepted_fingerprint"], "product:0000000000000000")
        self.assertIn("D-009", err)

    def test_the_worktree_is_removed_when_fingerprinting_fails(self):
        seen = []

        def boom(tree):
            seen.append(tree)
            self.assertTrue((tree / "app.py").is_file())
            raise RuntimeError("disk on fire")

        code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1", fingerprint_fn=boom)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("internal error", err)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].exists())
        self.assert_cleaned_up()

    def test_an_unusable_head_is_never_given_to_git(self):
        for oid in ("--upload-pack=touch /tmp/x", "main", None, "abc"):
            code, out, err = self.land("12", "--project", str(self.project), "--milestone", "M1",
                                       run=self.runner(oid))
            self.assertEqual((code, out), (2, ""), oid)
            self.assertIn("no usable head commit", err)
        self.assertFalse(any("fetch" in argv or "worktree" in argv for argv in self.git_calls))
        code, _, err = self.land("12", "--project", str(self.project), "--milestone", "M1",
                                 run=self.runner(self.head, gh_code=1))
        self.assertEqual(code, 2)
        self.assertIn("gh could not read PR #12: gh failed", err)
        self.assert_cleaned_up()

    def test_a_head_origin_does_not_have_is_exit_2(self):
        code, _, err = self.land("12", "--project", str(self.project), "--milestone", "M1",
                                 run=self.runner("f" * 40))
        self.assertEqual(code, 2)
        self.assertIn("could not fetch the PR head", err)
        self.assert_cleaned_up()

    def test_usage_is_exit_2(self):
        for args in ([], ["12"], ["12", "--project", str(self.project)], ["x", "--project", str(self.project),
                     "--milestone", "M1"], ["12", "--project", str(self.project), "--milestone", "1"],
                     ["12", "--project", str(self.project / "nope"), "--milestone", "M1"],
                     ["12", "13", "--project", str(self.project), "--milestone", "M1"],
                     ["12", "--project", str(self.project), "--milestone", "M1", "--force"]):
            code, out, err = self.land(*args)
            self.assertEqual((code, out), (2, ""), args)
            self.assertIn("Usage: pr_watch.py land-check", err)
        self.assertEqual(self.gh_calls, [])

    def test_a_project_in_a_subfolder_is_compared_folder_to_folder(self):
        git("checkout", "-q", "feature", cwd=self.project)
        sub = self.project / "service"
        (sub / "docs/project").mkdir(parents=True)
        (sub / "main.py").write_text("print('service')\n")
        git("add", "service/main.py", cwd=self.project)
        git("commit", "-qm", "service", cwd=self.project)
        head = git("rev-parse", "HEAD", cwd=self.project)
        accepted = fingerprint_mod.fingerprint(sub, "product")[0]
        self.assertNotEqual(accepted, fingerprint_mod.fingerprint(self.project, "product")[0])
        (sub / "docs/project/decisions.md").write_text("# Decisions\n" + acceptance("D-002", "M1", accepted))
        milestones(sub, M1="accepted")
        prove(sub, Path(self.tmp.name) / "home")
        git("checkout", "-q", "main", cwd=self.project)
        sub.mkdir(exist_ok=True)
        code, out, err = self.land("12", "--project", str(sub), "--milestone", "M1", run=self.runner(head))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["head_fingerprint"], accepted)
        self.assert_cleaned_up()

    def test_the_command_line_with_gh_on_the_path(self):
        fake_bin = Path(self.tmp.name) / "bin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        gh.write_text("#!/bin/sh\n" + f"echo '{json.dumps({'headRefOid': self.head, 'headRefName': 'feature'})}'\n")
        gh.chmod(0o755)
        tmp = Path(self.tmp.name) / "tmp"
        tmp.mkdir()
        env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "TMPDIR": str(tmp)}
        out = subprocess.run([sys.executable, str(WATCH), "land-check", "12", "--project", str(self.project),
                              "--milestone", "M1"], capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(json.loads(out.stdout)["match"])
        self.assertEqual(list(tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
