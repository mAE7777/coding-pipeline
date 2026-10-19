#!/usr/bin/env python3
"""Project workflow control, independent of adoption and the build record.

Usage: project_policy.py on|off|status [project] [--json]
       project_policy.py check [project]   exit 0 when managed, 3 otherwise

No selection means OFF. A repository's worktrees share the main checkout's
.coding-pipeline.json. No environment variable or build artifact can enable it.

status in a project the pipeline does not manage, when the fast workflow is installed
(~/.claude/skills/dev-fast/SKILL.md), adds one line naming the installed /<name>-fast
skills to use for this project instead; --json then has "fast_workflow": true and that
line as "fast_workflow_note" ("fast_workflow" is false otherwise). A policy file that
exists but is invalid (such as {"managed": true} without "version": 1) reads OFF and
gets no fast line, since the fast workflow reads such a file as managed and stops; its
status says the file is invalid and that /pipeline on or /pipeline off rewrites it
(--json: "invalid" holds the problem).
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

NAME = ".coding-pipeline.json"
OFF_TEXT = ("Coding workflow OFF: follow the user's current request using the existing documents, design, "
            "code and tests. Adoption, owner lock, formal record repair and milestone continuation are not "
            "prerequisites. Saved pipeline documents are optional context, not workflow authority. "
            "Only an explicit project on command enables the workflow.")
AGREEMENT = ("<!-- coding-pipeline-policy:v1 -->\n"
             "The coding-pipeline working agreement below applies only when this project's\n"
             "`.coding-pipeline.json` explicitly sets `managed` to `true` (shared by Git worktrees).\n"
             "Otherwise follow the user's current request and existing project documents directly;\n"
             "adoption, owner lock, record maintenance, handoff intake and milestone stop rules\n"
             "are not prerequisites. Pipeline skills may be used as independent tools without\n"
             "enabling the workflow. This choice also applies after resume or compaction.\n")
# The fast workflow's skills (mAE7777/coding-pipeline-fast), named <name>-fast; an installed dev-fast marks it.
FAST_SKILLS = ("dev", "fix", "plan", "gate", "next", "scout", "capture", "explain", "handoff", "deploy", "polish")


def project_root(start):
    p = Path(start or ".").expanduser().resolve()
    if not p.is_dir():
        p = p.parent
    ancestors = (p, *p.parents)
    for c in ancestors:
        if (c / ".git").exists():
            return c
        if c == Path.home():
            break
    for c in ancestors:
        if ((c / NAME).exists() or
                (c / "docs/project").is_dir() or (c / "AGENTS.md").is_file()):
            return c
        if c == Path.home():
            break
    return p


def policy_path(root):
    """The main checkout is the single authority, including linked worktrees."""
    if (root / ".git").exists():
        try:
            r = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                common = Path(r.stdout.strip())
                common = (common if common.is_absolute() else root / common).resolve()
                if common.name == ".git":
                    return common.parent / NAME
        except (OSError, subprocess.TimeoutExpired):
            pass
    return root / NAME


def read(start):
    root = project_root(start)
    path = policy_path(root)
    info = {"project": str(root), "source": str(path), "managed": False,
            "mode": "OFF", "reason": "not enabled", "token": "missing"}
    try:
        raw = path.read_bytes()
        info["token"] = hashlib.sha256(raw).hexdigest()
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("version") != 1 or type(value.get("managed")) is not bool:
            raise ValueError("expected version 1 and a boolean managed value")
        info.update(managed=value["managed"], mode="ON" if value["managed"] else "OFF",
                    reason="explicit project choice")
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeError) as exc:
        info.update(reason=f"invalid or unreadable policy ({exc})", invalid=str(exc))
    return info


def managed(start):
    return read(start)["managed"]


def fast_workflow():
    """The line that routes an unmanaged project to the fast workflow when it is installed, else None."""
    skills = Path.home() / ".claude/skills"
    if not (skills / "dev-fast/SKILL.md").is_file():
        return None
    names = [f"/{n}-fast" for n in FAST_SKILLS if (skills / f"{n}-fast/SKILL.md").is_file()]
    return ("The fast workflow is installed: for this project use the matching /<name>-fast skill ("
            + ", ".join(names) + ").")


def valid(lease):
    """Revocation is observed even if the project is turned off and on again."""
    current = read(lease["project"])
    return current["managed"] and current["source"] == lease["source"] and current["token"] == lease["token"]


def require(start):
    choice = read(start)
    if not choice["managed"]:
        print(OFF_TEXT, file=sys.stderr)
        return False
    return True


def hook_project(data):
    # The actual working folder wins over stale harness environment/claims.
    return project_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ".")


def control_command(command):
    # Only the controller alone: any separator, redirection, or substitution would run something else too.
    if not isinstance(command, str) or re.search(r"[;&|<>`$()\n\r]", command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if words and re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(words[0]).name):
        words = words[1:]
    if not (2 <= len(words) <= 4 and words[1] in ("on", "off", "status", "check")):
        return False
    script = Path(words[0]).expanduser().resolve()
    try:
        # Codex's converted package carries this same controller. Both tools can revoke a gate.
        return script.name == Path(__file__).name and script.read_bytes() == Path(__file__).read_bytes()
    except OSError:
        return False


def migrate_agreement(root):
    """Condition only a recognizable generated agreement; preserve the user's map and conventions."""
    path = Path(root) / "AGENTS.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "<!-- coding-pipeline-policy:v1 -->" in text:
        return False
    match = re.search(r"^## Working agreement[ \t]*$", text, re.M)
    if not match:
        return False
    body = text[match.end():]
    if "docs/project/state.md" not in body or "continuity.py" not in body:
        return False
    path.write_text(text[:match.end()] + "\n\n" + AGREEMENT + body, encoding="utf-8")
    return True


def set_mode(start, enabled):
    if not Path(start).expanduser().is_dir():
        raise ValueError(f"not a project directory: {start}")
    root = project_root(start)
    if not root.is_dir():
        raise ValueError(f"not a project directory: {root}")
    path = policy_path(root)
    # Keep future/owner fields rather than silently discarding them.
    try:
        value = json.loads(path.read_text())
        value = value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        value = {}
    value.update(version=1, managed=enabled, revision=uuid.uuid4().hex)
    fd, tmp = tempfile.mkstemp(prefix=".coding-pipeline-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    info = read(root)
    try:
        migrate_agreement(root)
        if path.parent != root:
            migrate_agreement(path.parent)
    except (OSError, UnicodeError) as exc:
        # The switch is already durable. A protected old agreement cannot veto OFF.
        info["agreement_warning"] = str(exc)
    return info


def main(argv):
    if not argv or argv[0] not in ("on", "off", "status", "check"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    args = [a for a in argv[1:] if a != "--json"]
    if len(args) > 1:
        return 2
    root = args[0] if args else "."
    try:
        info = set_mode(root, argv[0] == "on") if argv[0] in ("on", "off") else read(root)
    except (OSError, ValueError) as exc:
        print(f"project policy: {exc}", file=sys.stderr)
        return 2
    if argv[0] == "check":
        return 0 if info["managed"] else 3
    if argv[0] == "status" and "invalid" in info:  # fast reads {"managed": true} alone as managed: no route there
        info["reason"] = (f"the policy file is invalid or unreadable ({info['invalid']}); /pipeline on or /pipeline "
                          "off rewrites it")
    fast = fast_workflow() if argv[0] == "status" and not info["managed"] and "invalid" not in info else None
    if argv[0] == "status":
        info["fast_workflow"] = fast is not None
        if fast:
            info["fast_workflow_note"] = fast
    print(json.dumps(info, indent=2) if "--json" in argv else
          f"Coding workflow {info['mode']} · {info['project']} · {info['reason']} · {info['source']}"
          + (f"\n{fast}" if fast else ""))
    return 0


if __name__ == "__main__":
    if "--help" in sys.argv[1:3] or sys.argv[1:] == ["-h"]:
        print(__doc__.strip())  # asked for, so not an error
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
