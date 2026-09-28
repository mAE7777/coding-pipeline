#!/usr/bin/env python3
"""Drive a headless browser for an isolated checker, with its own URL and file boundary.

Usage:
  browse.py [--root <dir>] <url> [--viewport WxH] [--load-state <file.json>] [steps...]
Steps, run in the order given:
  --wait <ms> | --wait-for <selector> | --click <selector> | --hover <selector> | --press <key>
  --fill <selector>=<text> | --select <selector>=<value> | --check <selector> | --goto <url>
  --eval <js expression> | --screenshot <file.png> | --text <file.txt> | --html <file.html>
  --snapshot <file.yml> (the accessibility tree) | --requests <file.json> (every request so far, with its
  status) | --save-state <file.json>
(--fill and --select split at the first "=", so the selector itself cannot contain one.)
Example: browse.py http://localhost:3000 --fill "#item=milk" --click "text=Add" --screenshot s.png
Each call starts a fresh browser; carry a login between calls with --save-state and --load-state.

Chromium cannot start inside Claude Code's macOS sandbox, so isolated checkers run this one script
outside the sandbox: the runner exempts exactly `python3 <this file> --root <the checker's copy> ...`, called
as its own command (a chained command stays sandboxed). That makes this script's own checks the boundary,
and the boundary is the --root folder (default: the current directory), which the exemption pins:
  - the page URL must be http(s) on localhost / 127.0.0.1 / [::1], or a file:// path inside the root;
  - every request the page makes, including WebSockets and navigations, is aborted unless it meets the
    same rule (data:, blob:, and about: are allowed), so a page cannot pull in files from elsewhere on
    the disk; service workers and downloads are off;
  - every file it reads or writes (--load-state and all outputs) must be inside the root; relative paths
    are taken from the root.
It runs under the machine-wide heavy-job lock. Prints one JSON line: url, title, final_url, blocked
requests, console errors and warnings, page errors, eval results, outputs. Exit 0 on success, 1 on a page error or when
Playwright is missing (NOT_RUN), 2 on a rejected URL or path.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def inside(path, root):
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def url_ok(url, root):
    u = urlparse(url)
    if u.scheme in ("data", "blob", "about"):
        return True
    if u.scheme in ("http", "https", "ws", "wss"):
        return (u.hostname or "") in LOCAL_HOSTS
    if u.scheme == "file":
        return inside(unquote(u.path), root)
    return False


STEPS = ("wait", "wait-for", "click", "hover", "fill", "press", "select", "check", "goto", "eval", "screenshot",
         "text", "html", "snapshot", "requests", "save-state")
FILE_STEPS = ("screenshot", "text", "html", "snapshot", "requests", "save-state")


def parse(argv):
    if not argv or argv[0].startswith("--"):
        raise SystemExit(2)
    url, steps, opts = argv[0], [], {"viewport": "1280x800", "load-state": None}
    i = 1
    while i < len(argv):
        k = argv[i]
        if i + 1 >= len(argv):
            raise SystemExit(2)
        v = argv[i + 1]
        if k in ("--viewport", "--load-state"):
            opts[k[2:]] = v
        elif k.startswith("--") and k[2:] in STEPS:
            steps.append((k[2:], v))
        else:
            raise SystemExit(2)
        i += 2
    return url, steps, opts


def main(argv):
    full = list(argv)
    root = Path.cwd().resolve()
    if argv[:1] == ["--root"]:
        if len(argv) < 2 or not Path(argv[1]).is_dir():
            print("browse: --root needs an existing folder", file=sys.stderr)
            return 2
        root, argv = Path(argv[1]).resolve(), argv[2:]
    try:
        url, steps, opts = parse(argv)
    except SystemExit:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if not url_ok(url, root):
        print(f"browse: refused {url}: only localhost URLs or files inside {root}", file=sys.stderr)
        return 2
    for kind, value in steps:
        if kind in FILE_STEPS and not inside(root / value, root):
            print(f"browse: refused output path {value}: must be inside {root}", file=sys.stderr)
            return 2
        if kind == "goto" and not url_ok(value, root):
            print(f"browse: refused {value}: only localhost URLs or files inside {root}", file=sys.stderr)
            return 2
    if opts["load-state"] and not inside(root / opts["load-state"], root):
        print(f"browse: refused state file {opts['load-state']}: must be inside {root}", file=sys.stderr)
        return 2
    if not os.environ.get("HEAVY_LOCK_HELD"):
        heavy = HERE / "heavy.py"
        if heavy.exists():
            return subprocess.call([sys.executable, str(heavy), "run", "--", sys.executable, str(Path(__file__).resolve()),
                                    *full])
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        reason = ("Playwright is not installed for this Python "
                  "(pip install playwright; python -m playwright install chromium)")
        print(json.dumps({"url": url, "status": "NOT_RUN", "reason": reason}))
        print(f"browse: NOT_RUN, {reason}", file=sys.stderr)
        return 1
    w, h = (int(x) for x in opts["viewport"].lower().split("x"))
    blocked, console_errors, console_warnings, page_errors, evals, outputs = [], [], [], [], [], []
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_args = {"viewport": {"width": w, "height": h}, "service_workers": "block",
                    "accept_downloads": False}
        if opts["load-state"]:
            ctx_args["storage_state"] = str(root / opts["load-state"])
        context = browser.new_context(**ctx_args)

        def route(r):
            if url_ok(r.request.url, root):
                r.continue_()
            else:
                blocked.append(r.request.url)
                r.abort()
        context.route("**/*", route)

        def ws_route(ws):
            if url_ok(ws.url, root):
                ws.connect_to_server()
            else:
                blocked.append(ws.url)
                ws.close()
        context.route_web_socket("**/*", ws_route)
        page = context.new_page()
        def on_console(m):
            if m.type == "error":
                console_errors.append(m.text)
            elif m.type == "warning":
                console_warnings.append(m.text)
        page.on("console", on_console)
        page.on("pageerror", lambda e: page_errors.append(str(e)[:300]))
        page.on("response", lambda r: requests.append({"url": r.url, "method": r.request.method, "status": r.status,
                                                       "type": r.request.resource_type}))
        page.on("requestfailed", lambda r: requests.append({"url": r.url, "method": r.method, "status": "failed",
                                                            "type": r.resource_type,
                                                            "error": (r.failure or "")[:120] if isinstance(r.failure, str)
                                                            else str(r.failure)[:120]}))
        try:
            page.goto(url, wait_until="load", timeout=30000)
            for kind, value in steps:
                if kind == "wait":
                    page.wait_for_timeout(int(value))
                elif kind == "wait-for":
                    page.wait_for_selector(value, timeout=10000)
                elif kind == "click":
                    page.click(value, timeout=10000)
                elif kind == "hover":
                    page.hover(value, timeout=10000)
                elif kind == "fill":
                    sel, text = value.split("=", 1)
                    page.fill(sel, text, timeout=10000)
                elif kind == "select":
                    sel, choice = value.split("=", 1)
                    page.select_option(sel, choice, timeout=10000)
                elif kind == "check":
                    page.check(value, timeout=10000)
                elif kind == "press":
                    page.keyboard.press(value)
                elif kind == "goto":
                    page.goto(value, wait_until="load", timeout=30000)
                elif kind == "eval":
                    evals.append({"expression": value[:200], "result": page.evaluate(value)})
                elif kind == "screenshot":
                    page.screenshot(path=str(root / value), full_page=True)
                    outputs.append(value)
                elif kind == "text":
                    (root / value).write_text(page.inner_text("body"), encoding="utf-8")
                    outputs.append(value)
                elif kind == "html":
                    (root / value).write_text(page.content(), encoding="utf-8")
                    outputs.append(value)
                elif kind == "snapshot":
                    (root / value).write_text(page.locator("body").aria_snapshot(), encoding="utf-8")
                    outputs.append(value)
                elif kind == "requests":
                    (root / value).write_text(json.dumps(requests, indent=1), encoding="utf-8")
                    outputs.append(value)
                elif kind == "save-state":
                    context.storage_state(path=str(root / value))
                    outputs.append(value)
            result = {"url": url, "final_url": page.url, "title": page.title(), "blocked_requests": blocked,
                      "console_errors": console_errors, "console_warnings": console_warnings,
                      "page_errors": page_errors, "evals": evals, "outputs": outputs, "status": "OK"}
            code = 0
        except Exception as exc:
            result = {"url": url, "error": str(exc)[:300], "blocked_requests": blocked,
                      "console_errors": console_errors, "page_errors": page_errors, "outputs": outputs,
                      "status": "ERROR"}
            code = 1
        browser.close()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
