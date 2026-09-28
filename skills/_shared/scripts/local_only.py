#!/usr/bin/env python3
"""Keep the build record's local-only files out of commits, through git's local exclude file, never .gitignore.

Usage: local_only.py <project> [<pattern> ...]

With no patterns, adds the pipeline's standard local-only set: the working files of docs/project (brief, state,
gate settings, handoffs, reviews, research, captured sources, gate canaries), .evidence/, the browser tool's
snapshots, and AGENTS.md and CLAUDE.md (committed output carries no tooling files). Each pattern is added once;
existing lines are kept. Works from any folder inside the repository (git rev-parse finds the exclude file,
also in a worktree). Prints what it added. Exit 0; 1 when the folder is not in a git repository.

The file lives inside .git, which Claude Code never lets its file tools edit without asking; this script is
the way to change it.
"""
import subprocess
import sys
from pathlib import Path

STANDARD = ["/docs/project/brief.md", "/docs/project/state.md", "/docs/project/gate.md", "/docs/project/handoffs/",
            "/docs/project/reviews/", "/docs/project/research/", "/docs/project/sources/",
            "/docs/project/.gate-canary-*", "/.evidence/", "/.playwright-cli/", "/AGENTS.md", "/CLAUDE.md"]


def exclude_file(project):
    r = subprocess.run(["git", "-C", str(project), "rev-parse", "--git-path", "info/exclude"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    path = Path(r.stdout.strip())
    return path if path.is_absolute() else Path(project) / path


def ensure(project, patterns=None):
    """Add the patterns to the local exclude file; returns the ones added, or None outside a repository."""
    target = exclude_file(project)
    if target is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    have = set(target.read_text(encoding="utf-8").splitlines()) if target.is_file() else set()
    added = [p for p in (patterns or STANDARD) if p not in have]
    if added:
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        with open(target, "a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + "\n".join(added) + "\n")
    return added


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    added = ensure(Path(argv[0]), argv[1:] or None)
    if added is None:
        print(f"local_only: {argv[0]} is not inside a git repository", file=sys.stderr)
        return 1
    print("added: " + (", ".join(added) if added else "nothing (all present)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
