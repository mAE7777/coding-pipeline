#!/usr/bin/env python3
"""Which tool and session a command runs in, read from the variables each tool sets for its commands.

Claude Code sets CLAUDE_CODE_SESSION_ID in the commands its Bash tool runs. Codex sets CODEX_THREAD_ID in the
commands it runs (codex-rs core exec_env: injected whenever the thread has an id, even under an include-only
environment policy). When both are set, one tool was started from inside the other and the command alone
cannot tell which one is running it, so the answer is "ambiguous" and the caller must be told explicitly.

Usage: session_env.py    prints "<tool> <session id>", or "none" / "ambiguous" (exit 1)
"""
import os
import sys


def current():
    """(tool, session id); (None, None) when neither is set; ("ambiguous", None) when both are."""
    claude, codex = os.environ.get("CLAUDE_CODE_SESSION_ID"), os.environ.get("CODEX_THREAD_ID")
    if claude and codex:
        return "ambiguous", None
    if claude:
        return "claude", claude
    if codex:
        return "codex", codex
    return None, None


def main():
    tool, sid = current()
    if tool in (None, "ambiguous"):
        print(tool or "none")
        return 1
    print(f"{tool} {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
