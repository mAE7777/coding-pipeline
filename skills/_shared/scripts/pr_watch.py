#!/usr/bin/env python3
r"""Watch a GitHub pull request, a connected stack, or a frozen queued stack; check a PR head before it lands.

Usage: pr_watch.py [--pr N] [--owner OWNER --repo REPO] [--stack | --queued-stack [--stack-prs A,B,C]]
                   [--status-only] [--interval S] [--sweep-interval S] [--timeout S] [--max-query-errors N]
                   [--allow-draft] [--pretty] [--review-bot-authors A,B] [--review-bot-pass-key REGEX]
                   [--human-gate-check NAME]
       pr_watch.py land-check <pr> --project <dir> --milestone M<k>

Watching reads GitHub through the gh command-line tool. Output is JSON (NDJSON while polling): one event per
line on stdout. --pretty prints readable text instead, with a markdown table for STATUS.

Modes:
  single (default)   one PR: --pr N, or the PR of the current branch.
  --stack            the connected open stack around the PR, bottom to top: the PRs below it by base branch,
                     the PR, then the PRs above it (depth first, lower number first at a fork).
  --queued-stack     a stack frozen once at start and watched until every PR has merged. --stack-prs A,B,C
                     gives the list bottom to top (only with --queued-stack); without it the connected open
                     stack is captured once.

Options:
  --owner OWNER, --repo REPO   the repository. Default: the local origin remote, else what gh infers.
  --pr N                       the pull request (a leading # is fine).
  --status-only                read once, print one STATUS, exit 0 whatever it shows.
  --interval S                 seconds between polls (default 60).
  --sweep-interval S           queued mode: seconds between whole-stack sweeps (default 300).
  --timeout S                  give up after S seconds (default 0: no deadline).
  --max-query-errors N         consecutive failed GitHub reads before giving up (default 5).
  --allow-draft                a draft PR is not a merge gate (a ready draft stays a draft).
  --pretty                     readable text instead of JSON.
  --review-bot-authors A,B     author-login fragments that mark a review bot, matched without case as
                               substrings (default "cursor,bugbot,coderabbitai,copilot-pull-request-reviewer,
                               github-actions"). An empty value turns bot detection off.
  --review-bot-pass-key REGEX  found in a bot comment's body; its last group (the whole match when it has no
                               group) names one review pass. The default is
                                 (RUN_ID|CURSOR_AUTOMATION_ID|REVIEW_RUN):\s*(\S+)
                               Passes are distinct keys over every bot thread, resolved ones too; bot threads
                               without a key count as one pass when no thread has a key.
  --human-gate-check NAME      a check that waits on a person; repeat it for more. "Code Review Gate" always
                               is one. Such a check, while pending or waiting on an action, reads as kind
                               code-review-gate: neither pending nor failed, so the watcher never waits on a human.

What blocks, in order. One PR: merge conflicts, then unresolved review threads, then failing CI, then the merge
gate (closed without merge, draft, changes requested), then pending checks (a wait), else READY. A stack is
scanned tier by tier, bottom to top within a tier: a conflict anywhere outranks threads anywhere, and so on. A
draft whose checks are still pending waits rather than blocks. CI is failing when a check failed, and rejected
when none failed but GitHub refuses the merge: mergeStateStatus BLOCKED while the head commit's rollup is ERROR
or FAILURE (a refusal hidden behind a green check list). Checks come from gh pr checks, or from the GraphQL
rollup when that list is empty or unusable; both empty is a failed read. An enum value or shape GitHub sends
that this script does not know fails closed: the read counts as a failed query. Queued mode reports its own
frontier (the lowest unmerged PR): when it is blocker-free it waits for the merge queue, whatever is pending
above it. Failed reads are retried after min(max(interval, 60) * 2^(failures - 1), 300) seconds.

Events. Each line is one JSON object: schemaVersion (1), sequence (1, 2, ...), observedAt (UTC ISO time), mode
(single, stack, or queued-stack), kind, terminal (true on the last line only, which also carries exitCode).
  Progress: QUEUE (queued mode: the frozen list), STATUS (stack and queued modes: every row; reason poll or
  whole-stack-sweep), WAITING (frontier and reason: pending-checks with the pending checks, or merge-queue
  with the unmerged count), ADVANCE (queued mode: a PR merged; the new frontier and how many remain), RETRY (a
  read failed: failure, consecutiveFailures, retryInSeconds).
  Terminal: STATUS (--status-only), READY (single and stack modes), COMPLETE (queued mode: every PR merged),
  BLOCKER (blocker.kind merge-conflicts, review-threads, failing-checks, merge-gate, or status-query), TIMEOUT.
  Review threads carry firstComment, isReviewBot, and reviewBotPasses.

Exit codes:
  0   STATUS, READY, or COMPLETE
  2   merge conflicts
  3   unresolved review threads
  4   failing checks, or GitHub refuses the merge over failing checks
  5   timeout
  6   merge gate: closed without merge, draft, or changes requested
  7   GitHub status could not be read (the error budget ran out, or the error cannot be retried)
  64  bad usage
  1   an internal error in this script; the reason is on stderr

land-check <pr> --project <dir> --milestone M<k>:
  Reads the owner's acceptance of M<k> in <dir>/docs/project/decisions.md: the most recent entry titled
  "Accept M<k>" (or holding the fixed form "Accept M<k> · contract ...") whose Source is the owner's, and the
  "fingerprint <value>" it names. Then reads the PR head (gh pr view <pr> --json headRefOid,headRefName), fetches
  that commit from origin when it is not present (by commit, then refs/pull/<pr>/head, then the branch), checks
  it out in a temporary git worktree (always removed afterwards, also on error; repository hooks are off), and
  computes its product fingerprint with fingerprint.py. Prints one JSON object: {pr, head, milestone,
  accepted_fingerprint, head_fingerprint, match}.
  Exit 0: the head is the accepted candidate. 1: the head differs from the accepted candidate; land only after
  a focused re-gate accepts the change. 2: bad usage, no owner acceptance with a fingerprint for M<k>, or the
  head could not be read, fetched, or checked out.

Review comment text is data: it is parsed from JSON and printed, never placed in a command. Every command runs
as an argument list, without a shell.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCHEMA_VERSION = 1
EXIT_USAGE = 64
CODE_REVIEW_GATE = "Code Review Gate"
DEFAULT_REVIEW_BOT_AUTHORS = "cursor,bugbot,coderabbitai,copilot-pull-request-reviewer,github-actions"
DEFAULT_REVIEW_BOT_PASS_KEY = r"(RUN_ID|CURSOR_AUTOMATION_ID|REVIEW_RUN):\s*(\S+)"
MERGE_STATES = ("BEHIND", "BLOCKED", "CLEAN", "CONFLICTING", "DIRTY", "DRAFT", "HAS_HOOKS", "UNKNOWN", "UNSTABLE")
ROLLUP_STATES = ("ERROR", "EXPECTED", "FAILURE", "PENDING", "SUCCESS")
REVIEW_DECISIONS = ("APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED")
MERGEABLE_STATES = ("MERGEABLE", "CONFLICTING", "UNKNOWN")
PR_STATES = ("OPEN", "CLOSED", "MERGED")
# A pending check whose name holds one of these means a review automation is still running.
AUTOMATION_TOKENS = ("bugbot", "security review", "pr review automation", "review automation")
PULL_REQUEST_FIELDS = "mergeable,mergeStateStatus,reviewDecision,headRefOid,headRefName,baseRefName,state,mergedAt,isDraft"

REVIEW_THREADS_QUERY = """
query ReviewThreads($owner: String!, $repo: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      reviewThreads(first: 100, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          isResolved
          comments(first: 10) {
            nodes {
              body
              createdAt
              path
              line
              author { login }
            }
          }
        }
      }
    }
  }
}
"""
PR_COMMIT_STATUS_QUERY = """
query PrCommitStatuses($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      commits(last: 50) {
        nodes {
          commit {
            oid
            statusCheckRollup {
              state
            }
          }
        }
      }
    }
  }
}
"""
PR_CHECK_ROLLUP_QUERY = """
query PrCheckRollup($owner: String!, $repo: String!, $pr: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup {
              contexts(first: 100, after: $after) {
                pageInfo {
                  hasNextPage
                  endCursor
                }
                nodes {
                  __typename
                  ... on CheckRun {
                    name
                    status
                    conclusion
                    detailsUrl
                  }
                  ... on StatusContext {
                    context
                    state
                    targetUrl
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


# ---------------------------------------------------------------------------------------------------------------
# Configuration and errors


class ReviewConfig:
    """Which threads come from a review bot, how its passes are counted, and which checks wait on a person."""

    def __init__(self, bot_authors=None, pass_key=None, gate_checks=()):
        authors = DEFAULT_REVIEW_BOT_AUTHORS if bot_authors is None else bot_authors
        self.bot_authors = tuple(a.strip().lower() for a in authors.split(",") if a.strip())
        self.pass_key = re.compile(DEFAULT_REVIEW_BOT_PASS_KEY if pass_key is None else pass_key)
        self.gate_checks = frozenset((CODE_REVIEW_GATE,) + tuple(gate_checks))


DEFAULT_CONFIG = ReviewConfig()


class WatcherQueryError(Exception):
    """A GitHub read that failed; failure says how, and whether a retry can help."""

    def __init__(self, failure):
        super().__init__(failure["detail"])
        self.failure = failure


class ChecksUnavailable(WatcherQueryError):
    def __init__(self, detail):
        super().__init__({"kind": "checks-unavailable", "retryable": True, "detail": detail})


class UsageError(Exception):
    pass


class LandCheckError(Exception):
    """land-check could not compare the head with the acceptance (exit 2)."""


# ---------------------------------------------------------------------------------------------------------------
# Reading untrusted JSON: every shape is checked, and anything unexpected is a retryable missing-key failure.

ABSENT = object()


def _get(obj, key):
    return obj.get(key, ABSENT)


def _raw(value):
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _missing(path, value=ABSENT):
    if value is ABSENT:
        raise WatcherQueryError({"kind": "missing-key", "retryable": True, "detail": f"missing {path}"})
    raise WatcherQueryError({"kind": "missing-key", "retryable": True, "detail": f"invalid {path}: {_raw(value)}",
                             "rawValue": _raw(value)})


def _record(value, path):
    if not isinstance(value, dict):
        _missing(path, value)
    return value


def _list(value, path):
    if not isinstance(value, list):
        _missing(path, value)
    return value


def _at(value, path):
    joined = ".".join(path)
    current = value
    for key in path:
        obj = _record(current, joined)
        if key not in obj:
            _missing(joined)
        current = obj[key]
    return current


def _string(value, path):
    if not isinstance(value, str):
        _missing(path, value)
    return value


def _optional_string(value, path):
    return None if value is None else _string(value, path)


def _enum(value, values, path):
    if isinstance(value, str) and value in values:
        return value
    _missing(path, value)


def _nullable_enum(value, values, path):
    return None if value is None else _enum(value, values, path)


def _is_integer(value):
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value) and value.is_integer())


def parse_pr_number(value, label="PR number"):
    if not _is_integer(value) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def _reader_pr_number(value, label):
    try:
        return parse_pr_number(value, label)
    except ValueError:
        _missing(label, value)


def _js_number(text):
    """What JavaScript's Number() makes of a command-line string: nan when it is not a number."""
    s = text.strip()
    if not s:
        return 0.0
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+", s):
        return float(int(s, 0))
    if re.fullmatch(r"[+-]?Infinity", s):
        return float(s.replace("Infinity", "inf"))
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
        return float("nan")
    return float(s)


def _num(value):
    """An integral float as an int, so JSON shows 60 rather than 60.0."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def _first_line(value):
    return re.split(r"\r?\n", value.strip(), maxsplit=1)[0][:240]


def _parse_json(text, label):
    try:
        return json.loads(text)
    except ValueError as e:
        raise WatcherQueryError({"kind": "json-parse", "retryable": True, "detail": f"{label}: {e}"})


# ---------------------------------------------------------------------------------------------------------------
# Mapping checks, review threads, and pull requests


def _check_details(obj, name_key):
    def text(key):
        value = obj.get(key)
        return value if isinstance(value, str) else ""
    link = obj.get("link")
    if not isinstance(link, str):
        link = text("detailsUrl")
    return {"name": _string(_get(obj, name_key), name_key), "description": text("description"), "link": link,
            "workflow": text("workflow")}


def _check(details, kind, reported_state):
    return {**details, "kind": kind, "reportedState": reported_state}


def _gate_or(kind, details, reported_state, gate_checks):
    """Every read path classifies a human gate here, so the rule has one home. A gate that is pending or waits on
    an owner's action must not count as pending or failed, or the watcher waits on a human."""
    if details["name"] in gate_checks:
        return _check(details, "code-review-gate", reported_state)
    return _check(details, kind, reported_state)


def parse_fast_check(value, gate_checks=DEFAULT_CONFIG.gate_checks):
    """One entry of gh pr checks --json name,state,description,link,workflow,bucket."""
    obj = _record(value, "check")
    details = _check_details(obj, "name")
    state = _string(_get(obj, "state"), "check.state").upper()
    bucket = _string(_get(obj, "bucket"), "check.bucket")
    if state == "ACTION_REQUIRED":
        return _gate_or("failed", details, state, gate_checks)
    if bucket == "fail" or state in ("FAILURE", "ERROR"):
        return _check(details, "failed", state)
    if bucket == "pending":
        return _gate_or("pending", details, state, gate_checks)
    if bucket == "pass":
        return _check(details, "passed", state)
    if bucket == "skipping":
        return _check(details, "skipped", state)
    return _check(details, "failed", state)


def map_rollup_node(value, gate_checks=DEFAULT_CONFIG.gate_checks):
    """One node of the GraphQL status rollup; None for a node type this script does not read."""
    obj = _record(value, "rollup node")
    typename = obj.get("__typename")
    if typename not in ("CheckRun", "StatusContext"):
        return None
    details = _check_details(obj, "name" if typename == "CheckRun" else "context")
    if isinstance(obj.get("targetUrl"), str):
        details["link"] = obj["targetUrl"]
    if typename == "CheckRun":
        status = obj["status"].upper() if isinstance(obj.get("status"), str) else ""
        conclusion = obj["conclusion"].upper() if isinstance(obj.get("conclusion"), str) else ""
        if status != "COMPLETED":
            return _gate_or("pending", details, "PENDING", gate_checks)
        if conclusion == "SUCCESS":
            return _check(details, "passed", "SUCCESS")
        if conclusion in ("NEUTRAL", "SKIPPED"):
            return _check(details, "skipped", conclusion)
        if conclusion == "ACTION_REQUIRED":
            return _gate_or("failed", details, conclusion, gate_checks)
        return _check(details, "failed", "FAILURE")
    state = obj["state"].upper() if isinstance(obj.get("state"), str) else ""
    if state in ("PENDING", "EXPECTED"):
        return _gate_or("pending", details, "PENDING", gate_checks)
    if state == "SUCCESS":
        return _check(details, "passed", state)
    return _check(details, "failed", state or "FAILURE")


def parse_comment(value):
    obj = _record(value, "review comment")
    author_value = _get(obj, "author")
    author = None if author_value is None else _record(author_value, "review comment.author")
    line = _get(obj, "line")
    if line is not None and not _is_integer(line):
        _missing("review comment.line", line)
    return {
        "authorLogin": None if author is None else _optional_string(_get(author, "login"),
                                                                     "review comment.author.login"),
        "body": _string(_get(obj, "body"), "review comment.body"),
        "path": _optional_string(_get(obj, "path"), "review comment.path"),
        "line": None if line is None else int(line),
        "createdAt": _string(_get(obj, "createdAt"), "review comment.createdAt"),
    }


def is_review_bot(comment, config=DEFAULT_CONFIG):
    if comment is None:
        return False
    author = (comment.get("authorLogin") or "").lower()
    return any(fragment in author for fragment in config.bot_authors)


def review_pass_key(comment, config=DEFAULT_CONFIG):
    """The review pass a bot comment belongs to: the pass-key regex's last group, or its whole match."""
    if comment is None:
        return None
    match = config.pass_key.search(comment["body"])
    if match is None:
        return None
    key = match.group(match.re.groups) if match.re.groups else match.group(0)
    return key or None


def parse_review_thread_page(value):
    review_threads = _record(_at(value, ["data", "repository", "pullRequest", "reviewThreads"]), "reviewThreads")
    nodes = _list(_get(review_threads, "nodes"), "reviewThreads.nodes")
    threads = []
    for node in nodes:
        thread = _record(node, "review thread")
        resolved = _get(thread, "isResolved")
        if not isinstance(resolved, bool):
            _missing("review thread.isResolved", resolved)
        comments = _list(_at(thread, ["comments", "nodes"]), "review thread.comments.nodes")
        threads.append({"id": _string(_get(thread, "id"), "review thread.id"),
                        "firstComment": parse_comment(comments[0]) if comments else None,
                        "resolved": resolved})
    page = _record(_get(review_threads, "pageInfo"), "reviewThreads.pageInfo")
    has_next = _get(page, "hasNextPage")
    if not isinstance(has_next, bool):
        _missing("reviewThreads.pageInfo.hasNextPage", has_next)
    cursor = _optional_string(_get(page, "endCursor"), "reviewThreads.pageInfo.endCursor")
    return {"threads": threads, "endCursor": cursor if has_next and cursor else None}


def build_review_threads(threads, config=DEFAULT_CONFIG):
    """The unresolved threads, each marked whether a review bot opened it and how many bot passes the PR had."""
    keys, keyless = set(), False
    for thread in threads:
        if not is_review_bot(thread["firstComment"], config):
            continue
        key = review_pass_key(thread["firstComment"], config)
        if key is None:
            keyless = True
        else:
            keys.add(key)
    passes = len(keys) if keys else (1 if keyless else 0)
    return [{"id": t["id"], "firstComment": t["firstComment"], "isReviewBot": is_review_bot(t["firstComment"], config),
             "reviewBotPasses": passes} for t in threads if not t["resolved"]]


def parse_pull_request(value, context):
    obj = _record(value, "pull request")
    draft = _get(obj, "isDraft")
    if not isinstance(draft, bool):
        _missing("pull request.isDraft", draft)
    decision = _get(obj, "reviewDecision")
    # gh pr view reports no review decision as "", not null. Only this field does it, so the normalization stays
    # here: elsewhere an unexpected value must still fail closed.
    return {
        "context": context,
        "mergeable": _enum(_get(obj, "mergeable"), MERGEABLE_STATES, "pull request.mergeable"),
        "mergeStateStatus": _enum(_get(obj, "mergeStateStatus"), MERGE_STATES, "pull request.mergeStateStatus"),
        "reviewDecision": _nullable_enum(None if decision == "" else decision, REVIEW_DECISIONS,
                                         "pull request.reviewDecision"),
        "headRefOid": _optional_string(_get(obj, "headRefOid"), "pull request.headRefOid"),
        "headRefName": _string(_get(obj, "headRefName"), "pull request.headRefName"),
        "baseRefName": _string(_get(obj, "baseRefName"), "pull request.baseRefName"),
        "state": _enum(_get(obj, "state"), PR_STATES, "pull request.state"),
        "mergedAt": _optional_string(_get(obj, "mergedAt"), "pull request.mergedAt"),
        "isDraft": draft,
    }


def _canonical_github_parts(value):
    """The path parts of a plain https://github.com URL, or None when it is anything else."""
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        return None
    if (url.scheme != "https" or url.hostname != "github.com" or port not in (None, 443) or url.username
            or url.password or url.query or url.fragment):
        return None
    return url.path


def parse_remote(value):
    """owner and repo from an origin remote URL on github.com, or None."""
    normalized = value.strip()
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized[len("git@github.com:"):]
    if normalized.startswith("ssh://git@github.com/"):
        normalized = "https://github.com/" + normalized[len("ssh://git@github.com/"):]
    path = _canonical_github_parts(normalized)
    if path is None:
        return None
    parts = [p for p in re.sub(r"\.git$", "", path).split("/") if p]
    return {"owner": parts[0], "repo": parts[1]} if len(parts) == 2 else None


def parse_pr_url(value):
    try:
        path = _canonical_github_parts(value)
        parts = [p for p in (path or "").split("/") if p]
        if path is None or len(parts) != 4 or parts[2] != "pull":
            raise ValueError("not a canonical GitHub pull URL")
        return {"owner": parts[0], "repo": parts[1], "number": parse_pr_number(_js_number(parts[3]))}
    except ValueError as e:
        raise WatcherQueryError({"kind": "invalid-context-url", "retryable": False, "rawValue": value,
                                 "detail": f"could not infer owner/repo from PR URL: {value} ({e})"})


# ---------------------------------------------------------------------------------------------------------------
# The GitHub reader. Policy code talks to this interface only, so tests replace it with a fake.


def run_command(argv, cwd=None):
    """Run an argument list without a shell: (exit code, stdout, stderr). A program that cannot start is 127."""
    try:
        r = subprocess.run(list(argv), cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as e:
        return 127, "", f"could not run {argv[0]}: {e}"
    return r.returncode, r.stdout, r.stderr


def _graphql_args(query, context):
    return ["gh", "api", "graphql", "-f", f"query={query}", "-f", f"owner={context['owner']}",
            "-f", f"repo={context['repo']}", "-F", f"pr={context['number']}"]


class GitHubReader:
    """The reads the watcher needs. Each method returns plain dicts shaped like the JSON events."""

    def origin_repo(self):  # {"owner", "repo"} or None
        raise NotImplementedError

    def current_pr(self, pr):  # {"owner", "repo", "number"}
        raise NotImplementedError

    def pull_request(self, context):  # facts
        raise NotImplementedError

    def open_pull_requests(self, repository):  # [{"number", "headRefName", "baseRefName"}]
        raise NotImplementedError

    def checks_fast_path(self, context):  # {"kind": "checks", "checks"} or {"kind": "unusable", "exitCode", "stderr"}
        raise NotImplementedError

    def check_rollup_page(self, context, after):  # {"checks", "endCursor"}
        raise NotImplementedError

    def review_thread_page(self, context, after):  # {"threads": [{"id", "firstComment", "resolved"}], "endCursor"}
        raise NotImplementedError

    def commit_rollups(self, context):  # [{"oid", "state"}]
        raise NotImplementedError


class GhReader(GitHubReader):
    """Reads GitHub through the gh command-line tool. run(argv) returns (exit code, stdout, stderr)."""

    def __init__(self, run=run_command, config=DEFAULT_CONFIG):
        self.run = run
        self.gate_checks = config.gate_checks

    def _json(self, argv):
        code, out, err = self.run(argv)
        if code != 0:
            raise WatcherQueryError({"kind": "command-exit", "retryable": True, "code": code,
                                     "detail": _first_line(err) or f"{' '.join(argv)} exited {code}"})
        return _parse_json(out, " ".join(argv))

    def origin_repo(self):
        code, out, _ = self.run(["git", "remote", "get-url", "origin"])
        return parse_remote(out) if code == 0 else None

    def current_pr(self, pr):
        argv = ["gh", "pr", "view"] + ([str(pr)] if pr is not None else []) + ["--json", "number,url"]
        obj = _record(self._json(argv), "current PR")
        parsed = parse_pr_url(_string(_get(obj, "url"), "current PR.url"))
        return {**parsed, "number": pr if pr is not None else _reader_pr_number(_get(obj, "number"),
                                                                                "current PR.number")}

    def pull_request(self, context):
        return parse_pull_request(self._json(["gh", "pr", "view", str(context["number"]), "--repo",
                                              f"{context['owner']}/{context['repo']}", "--json",
                                              PULL_REQUEST_FIELDS]), context)

    def open_pull_requests(self, repository):
        value = self._json(["gh", "pr", "list", "--repo", f"{repository['owner']}/{repository['repo']}", "--state",
                            "open", "--limit", "300", "--json", "number,headRefName,baseRefName"])
        prs = []
        for index, item in enumerate(_list(value, "open PRs")):
            obj = _record(item, f"open PRs[{index}]")
            prs.append({"number": _reader_pr_number(_get(obj, "number"), f"open PRs[{index}].number"),
                        "headRefName": _string(_get(obj, "headRefName"), f"open PRs[{index}].headRefName"),
                        "baseRefName": _string(_get(obj, "baseRefName"), f"open PRs[{index}].baseRefName")})
        return prs

    def checks_fast_path(self, context):
        code, out, err = self.run(["gh", "pr", "checks", str(context["number"]), "--repo",
                                   f"{context['owner']}/{context['repo']}", "--json",
                                   "name,state,description,link,workflow,bucket"])
        # gh pr checks exits 1 when a check failed and 8 when checks are pending; its JSON is still good.
        if code in (0, 1, 8) and out.strip():
            try:
                value = _parse_json(out, "gh pr checks")
                if isinstance(value, list):
                    return {"kind": "checks", "checks": [parse_fast_check(v, self.gate_checks) for v in value]}
            except WatcherQueryError:
                pass  # unusable: the GraphQL rollup is read instead, and an empty one fails closed
        return {"kind": "unusable", "exitCode": code, "stderr": err}

    def check_rollup_page(self, context, after):
        argv = _graphql_args(PR_CHECK_ROLLUP_QUERY, context) + (["-f", f"after={after}"] if after is not None else [])
        value = self._json(argv)
        commits = _list(_at(value, ["data", "repository", "pullRequest", "commits", "nodes"]), "commits.nodes")
        if not commits:
            return {"checks": [], "endCursor": None}
        commit = _record(_at(commits[-1], ["commit"]), "commit")
        if _get(commit, "statusCheckRollup") is None:
            return {"checks": [], "endCursor": None}
        contexts = _record(_at(commit, ["statusCheckRollup", "contexts"]), "contexts")
        checks = [c for c in (map_rollup_node(n, self.gate_checks)
                              for n in _list(_get(contexts, "nodes"), "contexts.nodes")) if c is not None]
        page = _record(_get(contexts, "pageInfo"), "contexts.pageInfo")
        has_next = _get(page, "hasNextPage")
        if not isinstance(has_next, bool):
            _missing("contexts.pageInfo.hasNextPage", has_next)
        cursor = _optional_string(_get(page, "endCursor"), "contexts.pageInfo.endCursor")
        return {"checks": checks, "endCursor": cursor if has_next and cursor else None}

    def review_thread_page(self, context, after):
        argv = _graphql_args(REVIEW_THREADS_QUERY, context) + (["-f", f"after={after}"] if after is not None else [])
        return parse_review_thread_page(self._json(argv))

    def commit_rollups(self, context):
        value = self._json(_graphql_args(PR_COMMIT_STATUS_QUERY, context))
        commits = _list(_at(value, ["data", "repository", "pullRequest", "commits", "nodes"]), "commits.nodes")
        rollups = []
        for index, item in enumerate(commits):
            commit = _record(_at(item, ["commit"]), f"commits[{index}].commit")
            rollup = _get(commit, "statusCheckRollup")
            rollups.append({"oid": _string(_get(commit, "oid"), f"commits[{index}].oid"),
                            "state": None if rollup is None else _nullable_enum(
                                _at(rollup, ["state"]), ROLLUP_STATES, f"commits[{index}].statusCheckRollup.state")})
        return rollups


def resolve_checks(reader, context):
    """The PR's checks: gh pr checks when it lists any, else every page of the GraphQL rollup; none fails closed."""
    fast = reader.checks_fast_path(context)
    if fast["kind"] == "checks" and fast["checks"]:
        return {"source": "gh-pr-checks", "checks": list(fast["checks"])}
    checks, after = [], None
    while True:
        page = reader.check_rollup_page(context, after)
        checks.extend(page["checks"])
        after = page["endCursor"]
        if after is None:
            break
    if checks:
        return {"source": "graphql-rollup", "checks": checks}
    if fast["kind"] == "unusable":
        line = _first_line(fast["stderr"])
        suffix = f"fast path exit={fast['exitCode']}; GraphQL rollup was empty" + (f"; {line}" if line else "")
    else:
        suffix = "fast path and GraphQL rollup were empty"
    raise ChecksUnavailable(f"could not read PR checks: {suffix}")


def resolve_review_threads(reader, context, config=DEFAULT_CONFIG):
    threads, after = [], None
    while True:
        page = reader.review_thread_page(context, after)
        threads.extend(page["threads"])
        after = page["endCursor"]
        if after is None:
            break
    return build_review_threads(threads, config)


def resolve_context(reader, owner, repo, pr):
    if pr is not None and owner is not None and repo is not None:
        return {"owner": owner, "repo": repo, "number": pr}
    if pr is not None:
        origin = reader.origin_repo()
        if origin is not None:
            return {"owner": owner if owner is not None else origin["owner"],
                    "repo": repo if repo is not None else origin["repo"], "number": pr}
    inferred = reader.current_pr(pr)
    return {"owner": owner if owner is not None else inferred["owner"],
            "repo": repo if repo is not None else inferred["repo"],
            "number": pr if pr is not None else inferred["number"]}


def order_stack(context, open_prs):
    """The connected open stack around context, bottom to top; just context when it is not open."""
    by_number = {pr["number"]: pr for pr in open_prs}
    by_head = {pr["headRefName"]: pr for pr in open_prs}
    children = {}
    for pr in open_prs:
        children.setdefault(pr["baseRefName"], []).append(pr)
    for values in children.values():
        values.sort(key=lambda pr: pr["number"])
    start = by_number.get(context["number"])
    if start is None:
        return [context]
    down, current = [], start
    seen = {start["number"]}
    while current["baseRefName"] in by_head:
        parent = by_head[current["baseRefName"]]
        if parent["number"] in seen:
            break  # branches based on each other in a loop: stop rather than walk forever
        seen.add(parent["number"])
        down.append(parent)
        current = parent
    up = []

    def visit(parent):
        for child in children.get(parent["headRefName"], []):
            if child["number"] in seen:
                continue
            seen.add(child["number"])
            up.append(child)
            visit(child)

    visit(start)
    return [{**context, "number": pr["number"]} for pr in list(reversed(down)) + [start] + up]


def discover_stack(reader, context):
    return order_stack(context, reader.open_pull_requests(context))


# ---------------------------------------------------------------------------------------------------------------
# Policy: snapshots, blockers, and decisions


def assess_github_merge(merge_state_status, head_rollup_state):
    """GitHub's own view: BLOCKED with a failing head rollup is a refusal, whatever the visible check list says."""
    if merge_state_status == "BLOCKED":
        if head_rollup_state in ("ERROR", "FAILURE"):
            return {"kind": "refused", "mergeStateStatus": merge_state_status, "headRollupState": head_rollup_state}
        return {"kind": "allowed", "basis": "rollup", "mergeStateStatus": merge_state_status,
                "headRollupState": head_rollup_state}
    return {"kind": "allowed", "basis": "merge-state", "mergeStateStatus": merge_state_status,
            "headRollupState": head_rollup_state}


def _merge_assessment(reader, facts):
    commits = reader.commit_rollups(facts["context"])
    head = facts["headRefOid"]
    head_state = None if head is None else next((c["state"] for c in commits if c["oid"] == head), None)
    return (any(c["oid"] != head and c["state"] == "SUCCESS" for c in commits),
            assess_github_merge(facts["mergeStateStatus"], head_state))


def read_snapshot(reader, context, pending_history="include", config=DEFAULT_CONFIG):
    """One PR's row. pending_history "omit" skips the commit-rollup read while checks are only pending."""
    facts = reader.pull_request(context)
    if facts["state"] == "MERGED" or facts["mergedAt"] is not None:
        return {"kind": "merged", "context": context, "facts": facts}
    if facts["state"] == "CLOSED":
        return {"kind": "closed", "context": context, "facts": facts}
    threads = resolve_review_threads(reader, context, config)
    checks = resolve_checks(reader, context)
    failed = [c for c in checks["checks"] if c["kind"] == "failed"]
    pending = [c for c in checks["checks"] if c["kind"] == "pending"]
    if not failed and pending and pending_history == "omit":
        ci = {"kind": "ci-pending", "source": checks["source"], "all": checks["checks"], "failed": [],
              "pending": pending, "hadPreviousPassingCi": False}
    else:
        had_passing, github = _merge_assessment(reader, facts)
        base = {"source": checks["source"], "all": checks["checks"], "hadPreviousPassingCi": had_passing}
        if failed:
            ci = {**base, "kind": "ci-failing", "failed": failed, "pending": pending, "github": github}
        elif github["kind"] == "refused":
            ci = {**base, "kind": "ci-github-rejected", "failed": [], "pending": pending, "github": github}
        elif pending:
            ci = {**base, "kind": "ci-pending", "failed": [], "pending": pending}
        else:
            ci = {**base, "kind": "ci-clean", "failed": [], "pending": [], "github": github}
    running = any(c["kind"] == "pending" and any(token in c["name"].lower() for token in AUTOMATION_TOKENS)
                  for c in checks["checks"])
    return {"kind": "open", "context": context, "facts": facts, "threads": threads, "ci": ci,
            "reviewAutomationRunning": running}


def _conflict_blocker(row):
    if row["kind"] == "open" and (row["facts"]["mergeable"] == "CONFLICTING"
                                  or row["facts"]["mergeStateStatus"] in ("DIRTY", "CONFLICTING")):
        return {"kind": "merge-conflicts", "pr": row["context"], "facts": row["facts"]}
    return None


def _thread_blocker(row):
    if row["kind"] != "open" or not row["threads"]:
        return None
    return {"kind": "review-threads", "pr": row["context"], "threads": row["threads"]}


def _ci_blocker(row):
    if row["kind"] == "open" and row["ci"]["kind"] in ("ci-failing", "ci-github-rejected"):
        return {"kind": "failing-checks", "pr": row["context"], "ci": row["ci"]}
    return None


def _gate_reason(row, allow_draft):
    if row["kind"] == "merged":
        return None
    if row["kind"] == "closed":
        return "closed-without-merge"
    if row["facts"]["isDraft"] and not allow_draft:
        return "draft-pr"
    return "changes-requested" if row["facts"]["reviewDecision"] == "CHANGES_REQUESTED" else None


def _gate_blocker(row, allow_draft):
    reason = _gate_reason(row, allow_draft)
    if reason is None or (reason == "draft-pr" and row["kind"] == "open" and row["ci"]["kind"] == "ci-pending"):
        return None
    return {"kind": "merge-gate", "pr": row["context"], "reason": reason}


def _ready_contribution(row, allow_draft):
    if row["kind"] == "merged":
        return {"kind": "merged-pr", "context": row["context"], "mergedAt": row["facts"]["mergedAt"]}
    if (row["kind"] != "open" or row["ci"]["kind"] != "ci-clean" or row["threads"]
            or _conflict_blocker(row) is not None or _gate_reason(row, allow_draft) is not None):
        return None
    decision = row["facts"]["reviewDecision"]
    if decision == "CHANGES_REQUESTED":
        return None
    return {"kind": "ready-pr", "context": row["context"], "proof": {
        "mergeability": "clear", "threads": [], "ci": row["ci"],
        "gate": {"state": "OPEN", "reviewDecision": decision,
                 "draft": "draft-allowed" if row["facts"]["isDraft"] else "not-draft"}}}


def classify_pr(row, allow_draft=False):
    for blocker in (_conflict_blocker(row), _thread_blocker(row), _ci_blocker(row), _gate_blocker(row, allow_draft)):
        if blocker is not None:
            return {"kind": "blocker", "blocker": blocker}
    if row["kind"] == "open" and row["ci"]["kind"] == "ci-pending":
        return {"kind": "waiting", "frontier": row["context"], "pending": row["ci"]["pending"]}
    ready = _ready_contribution(row, allow_draft)
    if ready is None:
        raise RuntimeError("snapshot has no classified decision")
    return {"kind": "merged", "pr": ready} if ready["kind"] == "merged-pr" else {"kind": "ready", "pr": ready}


def select_tier_major_stack_decision(rows, allow_draft=False):
    """A stack's decision, tier by tier: any conflict, then any threads, then any failing CI, then any gate."""
    for tier in (_conflict_blocker, _thread_blocker, _ci_blocker):
        for row in rows:
            blocker = tier(row)
            if blocker is not None:
                return {"kind": "blocker", "blocker": blocker}
    for row in rows:
        blocker = _gate_blocker(row, allow_draft)
        if blocker is not None:
            return {"kind": "blocker", "blocker": blocker}
    for row in rows:
        if row["kind"] == "open" and row["ci"]["kind"] == "ci-pending":
            return {"kind": "waiting", "frontier": row["context"], "pending": row["ci"]["pending"]}
    prs = [p for p in (_ready_contribution(row, allow_draft) for row in rows) if p is not None]
    if not prs or len(prs) != len(rows):
        raise RuntimeError("stack has no classified decision")
    return {"kind": "clear", "prs": prs}


def query_backoff_seconds(interval, failures):
    return _num(min(max(interval, 60) * 2 ** (failures - 1), 300))


class Stamp:
    """Numbers and dates every event of one run: schemaVersion, sequence, observedAt, mode, then the payload."""

    def __init__(self, clock, mode):
        self.clock, self.mode, self.sequence = clock, mode, 0

    def __call__(self, payload, mode=None):
        self.sequence += 1
        return {"schemaVersion": SCHEMA_VERSION, "sequence": self.sequence, "observedAt": self.clock.observed_at(),
                "mode": mode or self.mode, **payload}


BLOCKER_EXIT = {"merge-conflicts": 2, "review-threads": 3, "failing-checks": 4, "merge-gate": 6}


def blocker_verdict(stamp, blocker):
    if blocker["kind"] not in BLOCKER_EXIT:
        raise RuntimeError(f"unknown blocker kind {blocker['kind']!r}")
    return stamp({"kind": "BLOCKER", "terminal": True, "exitCode": BLOCKER_EXIT[blocker["kind"]], "blocker": blocker})


def status_query_verdict(stamp, failures, failure):
    return stamp({"kind": "BLOCKER", "terminal": True, "exitCode": 7,
                  "blocker": {"kind": "status-query", "failures": failures, "failure": failure}})


class RealClock:
    def now(self):
        return time.monotonic()

    def observed_at(self):
        moment = datetime.now(timezone.utc)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"

    def sleep(self, seconds):
        time.sleep(seconds)


def _deadline_passed(started, options, now):
    return options["timeout"] > 0 and now - started >= options["timeout"]


def _poll_until_terminal(deps, options, stamp, step):
    """Run step until it returns a terminal verdict, retrying failed reads with backoff within the error budget.

    step returns ("terminal", verdict), ("sleep", seconds, on_deadline or None), or ("continue",)."""
    failures = 0
    started = deps.clock.now()
    while True:
        try:
            result = step()
            failures = 0
        except WatcherQueryError as error:
            failures += 1
            if not error.failure["retryable"] or failures >= options["max_query_errors"]:
                return status_query_verdict(stamp, failures, error.failure)
            retry_in = query_backoff_seconds(options["interval"], failures)
            deps.emit(stamp({"kind": "RETRY", "terminal": False, "failure": error.failure,
                             "consecutiveFailures": failures, "retryInSeconds": retry_in}))
            if _deadline_passed(started, options, deps.clock.now()):
                return stamp({"kind": "TIMEOUT", "terminal": True, "exitCode": 5,
                              "reason": {"kind": "status-unavailable", "failure": error.failure}})
            deps.clock.sleep(retry_in)
            continue
        if result[0] == "terminal":
            return result[1]
        if result[0] == "sleep":
            on_deadline = result[2]
            if on_deadline is not None and _deadline_passed(started, options, deps.clock.now()):
                return on_deadline()
            deps.clock.sleep(result[1])


class Dependencies:
    def __init__(self, reader, clock, emit, config=DEFAULT_CONFIG):
        self.reader, self.clock, self.emit, self.config = reader, clock, emit, config


def run_simple(deps, contexts, mode, status_only, options):
    """Single and stack modes, and --status-only in every mode."""
    stamp = Stamp(deps.clock, mode)

    def step():
        rows = [read_snapshot(deps.reader, context, "include", deps.config) for context in contexts]
        if not rows:
            raise RuntimeError("watch context cannot be empty")
        if status_only:
            return ("terminal", stamp({"kind": "STATUS", "terminal": True, "exitCode": 0, "reason": "status-only",
                                       "rows": rows}))
        if mode == "queued-stack":
            raise RuntimeError("queued-stack requires status-only in the simple runner")
        if mode == "stack":
            deps.emit(stamp({"kind": "STATUS", "terminal": False, "reason": "poll", "rows": rows}, mode))
        decision = (classify_pr(rows[0], options["allow_draft"]) if mode == "single"
                    else select_tier_major_stack_decision(rows, options["allow_draft"]))
        if decision["kind"] == "blocker":
            return ("terminal", blocker_verdict(stamp, decision["blocker"]))
        if decision["kind"] in ("ready", "merged"):
            return ("terminal", stamp({"kind": "READY", "terminal": True, "exitCode": 0,
                                       "scope": {"kind": "single", "pr": decision["pr"]}}, mode))
        if decision["kind"] == "clear":
            return ("terminal", stamp({"kind": "READY", "terminal": True, "exitCode": 0,
                                       "scope": {"kind": "stack", "prs": decision["prs"]}}, mode))
        deps.emit(stamp({"kind": "WAITING", "terminal": False, "frontier": decision["frontier"],
                         "reason": {"kind": "pending-checks", "pending": decision["pending"]}}))
        return ("sleep", options["interval"], lambda: stamp({
            "kind": "TIMEOUT", "terminal": True, "exitCode": 5,
            "reason": {"kind": "pending-checks", "pending": decision["pending"]}}))

    return _poll_until_terminal(deps, options, stamp, step)


# Queued stack: a state machine over the frozen list. A whole-stack sweep reads every unmerged PR in order; between
# sweeps only the frontier (the lowest unmerged PR) is read.


def create_queue_state(queue, now):
    return {"queue": list(queue), "snapshots": {}, "work": {"kind": "whole-stack-sweep", "remaining": list(queue)},
            "nextSweepAt": now, "frontier": None, "lastWaitKey": None, "startedAt": now}


def _ordered_rows(state):
    return [state["snapshots"][c["number"]] for c in state["queue"] if c["number"] in state["snapshots"]]


def _active_rows(state):
    return [row for row in _ordered_rows(state) if row["kind"] != "merged"]


def plan_queue(state, now):
    if state["work"] is not None:
        return state
    if not state["snapshots"] or now >= state["nextSweepAt"]:
        remaining = [c for c in state["queue"]
                     if (state["snapshots"].get(c["number"]) or {}).get("kind") != "merged"]
        if remaining:
            return {**state, "work": {"kind": "whole-stack-sweep", "remaining": remaining}}
    active = _active_rows(state)
    if not active:
        return state
    return {**state, "work": {"kind": "frontier-poll", "frontier": active[0]["context"]}}


def apply_queue_snapshot(state, snapshot, now, options):
    """(new state, the completed sweep's rows or None). A sweep head is dropped only once its read succeeded."""
    work = state["work"]
    if work is None:
        raise RuntimeError("queue has no read in flight")
    snapshots = {**state["snapshots"], snapshot["context"]["number"]: snapshot}
    base = {**state, "snapshots": snapshots}
    if work["kind"] == "frontier-poll":
        return {**base, "work": None}, None
    head, tail = work["remaining"][0], work["remaining"][1:]
    if head["number"] != snapshot["context"]["number"]:
        raise RuntimeError("snapshot does not match sweep head")
    if tail:
        return {**base, "work": {"kind": "whole-stack-sweep", "remaining": tail}}, None
    rows = [snapshots[c["number"]] for c in state["queue"] if c["number"] in snapshots]
    if len(rows) != len(state["queue"]):
        raise RuntimeError("sweep completed without every snapshot")
    return {**base, "work": None, "nextSweepAt": now + options["sweep_interval"]}, rows


def evaluate_queue(state, now, options):
    """One of: complete, blocker, advance, timeout, waiting (with emit: whether this wait is new)."""
    active = _active_rows(state)
    if not active:
        merged = [{"kind": "merged-pr", "context": row["context"], "mergedAt": row["facts"]["mergedAt"]}
                  for row in _ordered_rows(state) if row["kind"] == "merged"]
        if not merged:
            raise RuntimeError("empty queue cannot complete")
        return {"kind": "complete", "state": state, "merged": merged}
    decision = select_tier_major_stack_decision(active, options["allow_draft"])
    if decision["kind"] == "blocker":
        return {"kind": "blocker", "state": state, "blocker": decision["blocker"]}
    frontier = active[0]["context"]
    if state["frontier"] is not None and state["frontier"]["number"] != frontier["number"]:
        return {"kind": "advance", "state": {**state, "frontier": frontier, "lastWaitKey": None},
                "merged": state["frontier"], "frontier": frontier, "remaining": len(active)}
    if _deadline_passed(state["startedAt"], options, now):
        return {"kind": "timeout", "state": {**state, "frontier": frontier}, "frontier": frontier,
                "unmergedCount": len(active)}
    row = active[0]
    pending = row["ci"]["pending"] if row["kind"] == "open" and row["ci"]["kind"] == "ci-pending" else None
    if pending is None:
        reason = {"kind": "merge-queue", "unmergedCount": len(active)}
        key = f"queue:{frontier['number']}:{len(active)}"
    else:
        reason = {"kind": "pending-checks", "pending": pending}
        key = f"pending:{frontier['number']}:{len(pending)}"
    return {"kind": "waiting", "state": {**state, "frontier": frontier, "lastWaitKey": key}, "frontier": frontier,
            "reason": reason, "emit": state["lastWaitKey"] != key}


def run_queued(deps, contexts, options):
    """Queued mode: watch the frozen list until every PR merged, a blocker appears, or the deadline passes."""
    holder = {"state": create_queue_state(contexts, deps.clock.now())}
    stamp = Stamp(deps.clock, "queued-stack")
    deps.emit(stamp({"kind": "QUEUE", "terminal": False, "queue": list(contexts)}))

    def complete_verdict(merged):
        return stamp({"kind": "COMPLETE", "terminal": True, "exitCode": 0, "queue": holder["state"]["queue"],
                      "merged": merged})

    def step():
        holder["state"] = plan_queue(holder["state"], deps.clock.now())
        state = holder["state"]
        if state["work"] is None:
            done = evaluate_queue(state, deps.clock.now(), options)
            if done["kind"] != "complete":
                raise RuntimeError("queue has no work while active")
            return ("terminal", complete_verdict(done["merged"]))
        work = state["work"]
        context = work["remaining"][0] if work["kind"] == "whole-stack-sweep" else work["frontier"]
        snapshot = read_snapshot(deps.reader, context, "omit", deps.config)
        holder["state"], sweep_rows = apply_queue_snapshot(state, snapshot, deps.clock.now(), options)
        if sweep_rows is not None:
            deps.emit(stamp({"kind": "STATUS", "terminal": False, "reason": "whole-stack-sweep", "rows": sweep_rows}))
        if holder["state"]["work"] is not None:
            return ("continue",)
        evaluation = evaluate_queue(holder["state"], deps.clock.now(), options)
        holder["state"] = evaluation["state"]
        kind = evaluation["kind"]
        if kind == "complete":
            return ("terminal", complete_verdict(evaluation["merged"]))
        if kind == "blocker":
            return ("terminal", blocker_verdict(stamp, evaluation["blocker"]))
        if kind == "advance":
            deps.emit(stamp({"kind": "ADVANCE", "terminal": False, "merged": evaluation["merged"],
                             "frontier": evaluation["frontier"], "remaining": evaluation["remaining"]}))
            return ("continue",)
        if kind == "timeout":
            return ("terminal", stamp({"kind": "TIMEOUT", "terminal": True, "exitCode": 5, "reason": {
                "kind": "queued-stack", "frontier": evaluation["frontier"],
                "unmergedCount": evaluation["unmergedCount"]}}))
        if kind == "waiting":
            if evaluation["emit"]:
                deps.emit(stamp({"kind": "WAITING", "terminal": False, "frontier": evaluation["frontier"],
                                 "reason": evaluation["reason"]}))
            return ("sleep", options["interval"], None)
        raise RuntimeError(f"unknown queue evaluation {kind!r}")

    return _poll_until_terminal(deps, options, stamp, step)


# ---------------------------------------------------------------------------------------------------------------
# Rendering


def render_json(verdict):
    return json.dumps(verdict, separators=(",", ":"), ensure_ascii=False) + "\n"


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _safe_text(value):
    """Untrusted text for a terminal: control characters become '?'."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", value)


def _ci_cell(row):
    if row["kind"] != "open":
        return "-"
    ci = row["ci"]
    was = ", was passing" if ci["hadPreviousPassingCi"] else ""
    if ci["kind"] == "ci-clean":
        return "passing"
    if ci["kind"] == "ci-pending":
        return f"{len(ci['pending'])} pending{was}"
    if ci["kind"] == "ci-failing":
        more = f", {len(ci['pending'])} pending" if ci["pending"] else ""
        return f"{len(ci['failed'])} failed{more}{was}"
    if ci["kind"] == "ci-github-rejected":
        return f"GitHub reports failing checks{was}"
    raise RuntimeError(f"unknown CI state {ci['kind']!r}")


def _review_cell(row):
    if row["kind"] != "open":
        return "-"
    count = len(row["threads"])
    if row["reviewAutomationRunning"]:
        return f"bot running, {count} open" if count else "bot running"
    return f"{count} open" if count else "clear"


def _merge_cell(row):
    if row["kind"] == "merged":
        return "merged"
    if row["kind"] == "closed":
        return "closed"
    facts = row["facts"]
    if facts["isDraft"]:
        return "draft"
    if facts["reviewDecision"] == "CHANGES_REQUESTED":
        return "changes requested"
    if facts["mergeable"] == "CONFLICTING" or facts["mergeStateStatus"] in ("DIRTY", "CONFLICTING"):
        return "conflict"
    return "clear"


def render_status_table(rows):
    lines = ["| PR | CI | Review | Merge |", "| --- | --- | --- | --- |"]
    for row in rows:
        c = row["context"]
        url = f"https://github.com/{c['owner']}/{c['repo']}/pull/{c['number']}"
        lines.append(f"| [#{c['number']}]({url}) | {_ci_cell(row)} | {_review_cell(row)} | {_merge_cell(row)} |")
    return "\n".join(lines) + "\n"


def _shown(value):
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _thread_line(thread):
    comment = thread["firstComment"] or {}
    first = re.split(r"\r?\n", comment.get("body") or "", maxsplit=1)[0][:180]
    return " ".join([thread["id"], _shown(comment.get("path")), _shown(comment.get("line")),
                     _shown(comment.get("authorLogin")), f"isReviewBot={_shown(thread['isReviewBot'])}",
                     f"reviewBotPasses={thread['reviewBotPasses']}", _safe_text(first)])


def _render_blocker(blocker):
    kind = blocker["kind"]
    if kind == "merge-conflicts":
        return "\n".join(["BLOCKER: merge-conflicts", f"pr={blocker['pr']['number']}",
                          f"mergeable={blocker['facts']['mergeable']}",
                          f"mergeStateStatus={blocker['facts']['mergeStateStatus']}",
                          "action=resolve merge conflicts before waiting for CI"])
    if kind == "review-threads":
        return "\n".join(["BLOCKER: review-threads", f"pr={blocker['pr']['number']}",
                          f"unresolved={len(blocker['threads'])}"] + [_thread_line(t) for t in blocker["threads"]])
    if kind == "failing-checks":
        ci = blocker["ci"]
        failed = ci["failed"] if ci["kind"] == "ci-failing" else []
        details = [_safe_text(f"{c['name']} {c['reportedState']} {c['description']} {c['link']}") for c in failed]
        if ci["kind"] == "ci-github-rejected":
            details += [f"mergeStateStatus={ci['github']['mergeStateStatus']}",
                        f"headRollupState={ci['github']['headRollupState']}"]
        return "\n".join(["BLOCKER: failing-checks", f"pr={blocker['pr']['number']}", f"failed={len(failed)}"] + details)
    if kind == "merge-gate":
        action = {"closed-without-merge": "restore or remove the closed PR from the queued stack",
                  "draft-pr": "mark the PR ready for review before waiting for the merge queue",
                  "changes-requested": "resolve the changes-requested review before waiting for the merge queue",
                  }[blocker["reason"]]
        return "\n".join([f"BLOCKER: {blocker['reason']}", f"pr={blocker['pr']['number']}", f"action={action}"])
    if kind == "status-query":
        return "\n".join(["BLOCKER: status-query", f"failures={blocker['failures']}",
                          f"detail={_safe_text(blocker['failure']['detail'])}",
                          "action=verify current PR context, GitHub authentication, and API availability, then rearm"])
    raise RuntimeError(f"unknown blocker kind {kind!r}")


def render_pretty(verdict):
    kind = verdict["kind"]
    if kind == "QUEUE":
        queue = verdict["queue"]
        return (f"QUEUE: captured {_plural(len(queue), 'PR')} bottom-to-top: "
                f"{','.join('#' + str(c['number']) for c in queue)}\n")
    if kind == "STATUS":
        return render_status_table(verdict["rows"])
    if kind == "WAITING":
        reason = verdict["reason"]
        if reason["kind"] == "pending-checks":
            return f"WAITING: frontier=#{verdict['frontier']['number']}; {_plural(len(reason['pending']), 'check')} pending\n"
        return (f"WAITING: frontier=#{verdict['frontier']['number']} is blocker-free; waiting for merge queue "
                f"({_plural(reason['unmergedCount'], 'PR')} unmerged)\n")
    if kind == "ADVANCE":
        return (f"ADVANCE: merged #{verdict['merged']['number']}; next=#{verdict['frontier']['number']}; "
                f"remaining={verdict['remaining']}\n")
    if kind == "RETRY":
        return (f"RETRY: GitHub status query failed; retrying in {verdict['retryInSeconds']}s\n"
                f"detail={_safe_text(verdict['failure']['detail'])}\n")
    if kind == "BLOCKER":
        return _render_blocker(verdict["blocker"]) + "\n"
    if kind == "READY":
        scope = verdict["scope"]
        detail = ""
        if scope["kind"] == "single" and scope["pr"]["kind"] == "ready-pr":
            proof = scope["pr"]["proof"]
            drafted = proof["gate"]["draft"] == "draft-allowed"
            decision = proof["gate"]["reviewDecision"]
            detail = (f"\nmergeStateStatus={proof['ci']['github']['mergeStateStatus']}"
                      f"\nreviewDecision={'null' if decision is None else decision}"
                      f"\nisDraft={_shown(drafted)}"
                      + ("\nnote=draft allowed (--allow-draft); leave it a draft and do not mark it ready"
                         if drafted else ""))
        return f"READY: no merge conflicts, no unresolved review threads, no failing or pending checks{detail}\n"
    if kind == "COMPLETE":
        return f"COMPLETE: queued stack merged ({_plural(len(verdict['queue']), 'PR')})\n"
    if kind == "TIMEOUT":
        reason = verdict["reason"]
        if reason["kind"] == "pending-checks":
            return "TIMEOUT: checks still pending\n"
        if reason["kind"] == "status-unavailable":
            return "TIMEOUT: GitHub status remained unavailable\n"
        return (f"TIMEOUT: queued stack still has {_plural(reason['unmergedCount'], 'PR')} unmerged; "
                f"frontier=#{reason['frontier']['number']}\n")
    raise RuntimeError(f"unknown event kind {kind!r}")


# ---------------------------------------------------------------------------------------------------------------
# Command line


def _positive_number(value):
    n = _js_number(value)
    if not math.isfinite(n) or n <= 0:
        raise ValueError("must be greater than zero")
    return _num(n)


def _non_negative_number(value):
    n = _js_number(value)
    if not math.isfinite(n) or n < 0:
        raise ValueError("must be zero or greater")
    return _num(n)


def _positive_integer(value):
    n = _js_number(value)
    if not (math.isfinite(n) and n.is_integer() and n > 0):
        raise ValueError("must be a positive integer")
    return int(n)


def _pr_number_arg(value):
    return _positive_integer(re.sub(r"^#", "", value))


def _stack_pr_list(value):
    numbers = [_pr_number_arg(part.strip()) for part in value.split(",")]
    if len(set(numbers)) != len(numbers):
        raise ValueError("contains a duplicate PR")
    if not numbers:
        raise ValueError("cannot be empty")
    return numbers


def _regex(value):
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError(f"is not a regular expression ({e})")
    return value


def _check_name(value):
    if not value.strip():
        raise ValueError("cannot be empty")
    return value


# flag: (destination, value name, converter)
WATCH_OPTIONS = {
    "--owner": ("owner", "<owner>", str),
    "--repo": ("repo", "<repo>", str),
    "--pr": ("pr", "<number>", _pr_number_arg),
    "--stack-prs": ("stack_prs", "<n,...>", _stack_pr_list),
    "--interval": ("interval", "<seconds>", _positive_number),
    "--sweep-interval": ("sweep_interval", "<seconds>", _positive_number),
    "--timeout": ("timeout", "<seconds>", _non_negative_number),
    "--max-query-errors": ("max_query_errors", "<count>", _positive_integer),
    "--review-bot-authors": ("review_bot_authors", "<logins>", str),
    "--review-bot-pass-key": ("review_bot_pass_key", "<regex>", _regex),
    "--human-gate-check": ("human_gate_checks", "<name>", _check_name),
}
WATCH_FLAGS = {"--stack": "stack", "--queued-stack": "queued_stack", "--status-only": "status_only",
               "--allow-draft": "allow_draft", "--pretty": "pretty"}


def parse_args(argv):
    """The watcher's options; raises UsageError with a plain message."""
    raw = {"owner": None, "repo": None, "pr": None, "stack_prs": None, "interval": 60, "sweep_interval": 300,
           "timeout": 0, "max_query_errors": 5, "review_bot_authors": None, "review_bot_pass_key": None,
           "human_gate_checks": [], "stack": False, "queued_stack": False, "status_only": False,
           "allow_draft": False, "pretty": False}
    i = 0
    while i < len(argv):
        arg = argv[i]
        name, eq, inline = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        if name in WATCH_FLAGS:
            if eq:
                raise UsageError(f"option '{name}' does not take an argument")
            raw[WATCH_FLAGS[name]] = True
            i += 1
            continue
        if name in WATCH_OPTIONS:
            dest, metavar, convert = WATCH_OPTIONS[name]
            if eq:
                value, i = inline, i + 1
            elif i + 1 < len(argv):
                value, i = argv[i + 1], i + 2
            else:
                raise UsageError(f"option '{name} {metavar}' argument missing")
            try:
                converted = convert(value)
            except ValueError as e:
                raise UsageError(f"option '{name} {metavar}' argument '{value}' is invalid. {e}")
            if dest == "human_gate_checks":
                raw[dest].append(converted)
            else:
                raw[dest] = converted
            continue
        if arg.startswith("-"):
            raise UsageError(f"unknown option '{arg}'")
        raise UsageError(f"unexpected argument '{arg}' (the watcher takes options only)")
    if raw["stack"] and raw["queued_stack"]:
        raise UsageError("option '--stack' cannot be used with option '--queued-stack'")
    if raw["stack_prs"] is not None and not raw["queued_stack"]:
        raise UsageError("--stack-prs requires --queued-stack")
    return {
        "owner": raw["owner"], "repo": raw["repo"], "pr": raw["pr"],
        "mode": "queued-stack" if raw["queued_stack"] else "stack" if raw["stack"] else "single",
        "stack_prs": raw["stack_prs"] or [], "status_only": raw["status_only"], "pretty": raw["pretty"],
        "polling": {"interval": raw["interval"], "sweep_interval": raw["sweep_interval"], "timeout": raw["timeout"],
                    "max_query_errors": raw["max_query_errors"], "allow_draft": raw["allow_draft"]},
        "review": ReviewConfig(raw["review_bot_authors"], raw["review_bot_pass_key"], raw["human_gate_checks"]),
    }


def _write_stdout(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def _write_stderr(text):
    sys.stderr.write(text)
    sys.stderr.flush()


class Runtime:
    """What the watcher touches outside itself: the GitHub reader, the clock, and the two output streams."""

    def __init__(self, reader, clock=None, stdout=_write_stdout, stderr=_write_stderr):
        self.reader, self.clock, self.stdout, self.stderr = reader, clock or RealClock(), stdout, stderr


def main(argv, runtime=None):
    argv = list(argv)
    if argv and argv[0] == "land-check":
        return land_check_main(argv[1:])
    if "--help" in argv or "-h" in argv:
        (runtime.stdout if runtime else _write_stdout)(__doc__.strip() + "\n")
        return 0
    try:
        options = parse_args(argv)
    except UsageError as e:
        (runtime.stderr if runtime else _write_stderr)(f"error: {e}\nRun pr_watch.py --help for the usage.\n")
        return EXIT_USAGE
    if runtime is None:
        runtime = Runtime(GhReader(config=options["review"]))
    render = render_pretty if options["pretty"] else render_json

    def emit(verdict):
        runtime.stdout(render(verdict))

    try:
        seed_pr = options["pr"] if options["pr"] is not None else (options["stack_prs"] or [None])[0]
        seed = resolve_context(runtime.reader, options["owner"], options["repo"], seed_pr)
        if options["stack_prs"]:
            contexts = [{**seed, "number": n} for n in options["stack_prs"]]
        elif options["mode"] == "single":
            contexts = [seed]
        else:
            contexts = discover_stack(runtime.reader, seed)
    except WatcherQueryError as error:
        verdict = status_query_verdict(Stamp(runtime.clock, options["mode"]), 1, error.failure)
        runtime.stdout(render(verdict))
        return verdict["exitCode"]
    deps = Dependencies(runtime.reader, runtime.clock, emit, options["review"])
    if options["mode"] == "queued-stack" and not options["status_only"]:
        verdict = run_queued(deps, contexts, options["polling"])
    else:
        verdict = run_simple(deps, contexts, options["mode"], options["status_only"], options["polling"])
    runtime.stdout(render(verdict))
    return verdict["exitCode"]


# ---------------------------------------------------------------------------------------------------------------
# land-check: is the PR head the candidate the owner accepted?

LAND_MISMATCH = "the head differs from the accepted candidate; land only after a focused re-gate accepts the change"
DECISION = re.compile(r"^## (D-\d{3,})\b.*?(?=^## D-\d{3,}\b|\Z)", re.M | re.S)
OWNER_SOURCE = re.compile(r"^Source:\s*\[owner ", re.M)
FINGERPRINT = re.compile(r"\bfingerprint\s+`?([^\s`]+)`?")


def accepted_fingerprint(project, milestone):
    """(decision id, fingerprint) of the owner's latest acceptance of the milestone; LandCheckError when none."""
    path = Path(project) / "docs/project/decisions.md"
    if not path.is_file():
        raise LandCheckError(f"there is no {path}, so there is no acceptance of {milestone} to compare with")
    named_title = re.compile(rf"\bAccept {re.escape(milestone)}\b")
    fixed_form = re.compile(rf"\bAccept {re.escape(milestone)} ·")
    latest, not_owner = None, []
    for m in DECISION.finditer(path.read_text(encoding="utf-8")):
        lines = m.group(0).splitlines()
        if not (named_title.search(lines[0]) or any(fixed_form.search(line) for line in lines[1:])):
            continue
        if OWNER_SOURCE.search(m.group(0)):
            latest = (m.group(1), lines)
        else:
            not_owner.append(m.group(1))
    if latest is None:
        extra = f" ({', '.join(not_owner)} name it, but their Source is not the owner's)" if not_owner else ""
        raise LandCheckError(f"no owner acceptance of {milestone} in {path}: an entry 'Accept {milestone}' with "
                             f"'Source: [owner <date>]'{extra}")
    did, lines = latest
    body = [line for line in lines[1:] if not line.startswith("Source:")]
    for line in sorted(body, key=lambda line: not fixed_form.search(line)):
        found = FINGERPRINT.search(line)
        if found:
            return did, found.group(1)
    raise LandCheckError(f"acceptance {did} of {milestone} names no fingerprint, so there is no accepted candidate "
                         "to compare with")


def _git(run, project, *args):
    return run(["git", "-C", str(project), *args])


def read_pr_head(pr, project, run):
    """(head commit, head branch or None) from gh pr view, run in the project folder."""
    code, out, err = run(["gh", "pr", "view", str(pr), "--json", "headRefOid,headRefName"], cwd=str(project))
    if code != 0:
        raise LandCheckError(f"gh could not read PR #{pr}: {_first_line(err) or f'exit {code}'}")
    try:
        obj = json.loads(out)
    except ValueError:
        raise LandCheckError(f"gh pr view {pr} did not return JSON")
    obj = obj if isinstance(obj, dict) else {}
    oid, ref = obj.get("headRefOid"), obj.get("headRefName")
    if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid):
        raise LandCheckError(f"PR #{pr} names no usable head commit (headRefOid {_raw(oid)})")
    return oid, ref if isinstance(ref, str) else None


def fetch_head(pr, oid, ref, project, run):
    """Make the head commit present: by commit, then GitHub's pull ref, then the branch of that name on origin."""
    def present():
        return _git(run, project, "cat-file", "-e", f"{oid}^{{commit}}")[0] == 0
    if present():
        return
    sources = [oid, f"refs/pull/{pr}/head"]
    if ref and re.fullmatch(r"[A-Za-z0-9._/-]+", ref) and ".." not in ref:
        sources.append(f"refs/heads/{ref}")
    problems = []
    for source in sources:
        code, _, err = _git(run, project, "fetch", "--quiet", "--no-tags", "origin", source)
        if code == 0 and present():
            return
        if code != 0:
            problems.append(f"{source}: {_first_line(err) or f'exit {code}'}")
        else:
            problems.append(f"{source}: fetched, but {oid} is not in it")
    raise LandCheckError(f"could not fetch the PR head {oid} from origin ({'; '.join(problems)})")


def _product_fingerprint(tree):
    from fingerprint import fingerprint  # noqa: E402 (sibling script)
    return fingerprint(tree, "product")[0]


def head_fingerprint(project, oid, run, tmp_root=None, fingerprint_fn=None, prefix=""):
    """The product fingerprint of oid, checked out in a temporary worktree that is always removed. prefix is the
    project's folder inside the repository, so a project in a subfolder is compared folder to folder."""
    base = Path(tempfile.mkdtemp(prefix="pr-land-check-", dir=tmp_root))
    tree = base / "head"
    try:
        code, _, err = _git(run, project, "-c", f"core.hooksPath={os.devnull}", "worktree", "add", "--quiet",
                            "--detach", str(tree), oid)
        if code != 0:
            raise LandCheckError(f"could not check out {oid} in a temporary worktree: {_first_line(err)}")
        target = tree / prefix if prefix else tree
        if not target.is_dir():
            raise LandCheckError(f"the head {oid} has no folder {prefix}, where the project lives")
        return (fingerprint_fn or _product_fingerprint)(target)
    finally:
        _git(run, project, "worktree", "remove", "--force", str(tree))
        if tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
        _git(run, project, "worktree", "prune")
        shutil.rmtree(base, ignore_errors=True)
        if base.exists():
            _write_stderr(f"pr_watch land-check: could not remove the temporary worktree at {base}; "
                          "remove it and run git worktree prune\n")


def land_check(pr, project, milestone, run=run_command, tmp_root=None, fingerprint_fn=None):
    """(result object, acceptance decision id). Raises LandCheckError when the comparison cannot be made."""
    project = Path(project)
    did, accepted = accepted_fingerprint(project, milestone)
    code, prefix, _ = _git(run, project, "rev-parse", "--show-prefix")
    if code != 0:
        raise LandCheckError(f"{project} is not inside a git repository")
    oid, ref = read_pr_head(pr, project, run)
    fetch_head(pr, oid, ref, project, run)
    head_fp = head_fingerprint(project, oid, run, tmp_root, fingerprint_fn, prefix.strip())
    return {"pr": pr, "head": oid, "milestone": milestone, "accepted_fingerprint": accepted,
            "head_fingerprint": head_fp, "match": head_fp == accepted}, did


def parse_land_check_args(argv):
    """(pr, project, milestone); raises UsageError."""
    positional, values = [], {"--project": None, "--milestone": None}
    i = 0
    while i < len(argv):
        name, eq, inline = argv[i].partition("=") if argv[i].startswith("--") else (argv[i], "", "")
        if name in values:
            if eq:
                values[name], i = inline, i + 1
            elif i + 1 < len(argv):
                values[name], i = argv[i + 1], i + 2
            else:
                raise UsageError(f"{name} needs a value")
            continue
        if argv[i].startswith("-") and argv[i] != "-":
            raise UsageError(f"unknown option '{argv[i]}'")
        positional.append(argv[i])
        i += 1
    if len(positional) != 1:
        raise UsageError("give exactly one PR number")
    try:
        pr = _pr_number_arg(positional[0])
    except ValueError:
        raise UsageError(f"PR '{positional[0]}' is not a positive integer")
    if values["--project"] is None or not Path(values["--project"]).is_dir():
        raise UsageError("--project must name the project folder")
    milestone = values["--milestone"]
    if milestone is None or not re.fullmatch(r"M\d+", milestone):
        raise UsageError("--milestone must be a milestone id such as M2")
    return pr, Path(values["--project"]), milestone


def land_check_main(argv, run=run_command, tmp_root=None, fingerprint_fn=None, stdout=_write_stdout,
                    stderr=_write_stderr):
    if "--help" in argv or "-h" in argv:
        stdout(__doc__.strip() + "\n")
        return 0
    try:
        pr, project, milestone = parse_land_check_args(argv)
    except UsageError as e:
        stderr(f"pr_watch land-check: {e}\nUsage: pr_watch.py land-check <pr> --project <dir> --milestone M<k>\n")
        return 2
    try:
        result, did = land_check(pr, project, milestone, run, tmp_root, fingerprint_fn)
    except LandCheckError as e:
        stderr(f"pr_watch land-check: {e}\n")
        return 2
    except Exception as e:  # exit 1 means a mismatch, so an internal error must not exit 1
        stderr(f"pr_watch land-check: internal error, nothing was compared: {e!r}\n")
        return 2
    stdout(json.dumps(result) + "\n")
    if result["match"]:
        return 0
    stderr(f"pr_watch land-check: PR #{pr} head {result['head'][:12]} has fingerprint {result['head_fingerprint']}, "
           f"but {did} accepted {result['accepted_fingerprint']} for {milestone}: {LAND_MISMATCH}.\n")
    return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        _write_stderr("pr_watch: stopped by an interrupt before a verdict\n")
        sys.exit(130)
