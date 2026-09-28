"""Tests for browse.py: the URL and file boundary, and (when Playwright is installed) a real headless run."""
import http.server
import importlib.util
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROWSE = ROOT / "skills/_shared/scripts/browse.py"
PY = sys.executable
spec = importlib.util.spec_from_file_location("browse", BROWSE)
browse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browse)

try:
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

PAGE = """<!doctype html><html><head><title>List</title>
<script src="https://example.com/tracker.js"></script></head>
<body><h1>Grocery list</h1>
<img src="file://{outside}/secret.png">
<input id="item"><button id="add" onclick="add()">Add</button><ul id="items"></ul>
<script>
function add() {{ const li = document.createElement('li'); li.textContent = document.getElementById('item').value;
  document.getElementById('items').appendChild(li); }}
</script></body></html>
"""


class BoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "copy").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "outside/intent.md").write_text("secret goal")
        (self.root / "copy/link.md").symlink_to(self.root / "outside/intent.md")
        (self.root / "copy/page.html").write_text("<p>hi</p>")

    def tearDown(self):
        self.tmp.cleanup()

    def test_url_rules(self):
        c = self.root / "copy"
        self.assertTrue(browse.url_ok("http://localhost:3000/a", c))
        self.assertTrue(browse.url_ok("http://127.0.0.1:8080", c))
        self.assertTrue(browse.url_ok("http://[::1]:8080/", c))
        self.assertTrue(browse.url_ok(f"file://{c}/page.html", c))
        self.assertTrue(browse.url_ok("data:text/html,hi", c))
        self.assertFalse(browse.url_ok("https://example.com/", c))
        self.assertFalse(browse.url_ok("http://localhost.evil.com/", c))
        self.assertFalse(browse.url_ok(f"file://{self.root}/outside/intent.md", c))
        self.assertFalse(browse.url_ok(f"file://{c}/link.md", c), "a symlink out of the copy is outside")
        self.assertFalse(browse.url_ok(f"file://{c}/../outside/intent.md", c))
        self.assertFalse(browse.url_ok("chrome://settings", c))

    def run_cli(self, *args):
        env = {**os.environ, "HEAVY_LOCK_DIR": str(self.root / "lock"), "HEAVY_OWNER": "test"}
        env.pop("HEAVY_LOCK_HELD", None)
        return subprocess.run([PY, str(BROWSE), *args], cwd=self.root / "copy", capture_output=True, text=True,
                              env=env, timeout=120)

    def test_root_pins_the_boundary_regardless_of_cwd(self):
        env = {**os.environ, "HEAVY_LOCK_DIR": str(self.root / "lock"), "HEAVY_OWNER": "test"}
        env.pop("HEAVY_LOCK_HELD", None)
        out = subprocess.run([PY, str(BROWSE), "--root", str(self.root / "copy"),
                              f"file://{self.root}/outside/intent.md"], cwd=self.root / "outside",
                             capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(out.returncode, 2, "a file outside --root is refused even from a cwd that holds it")
        out = subprocess.run([PY, str(BROWSE), "--root", str(self.root / "nope"), "http://localhost:1"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 2)

    def test_cli_refusals_exit_2(self):
        self.assertEqual(self.run_cli("https://example.com").returncode, 2)
        self.assertEqual(self.run_cli(f"file://{self.root}/outside/intent.md").returncode, 2)
        page = f"file://{self.root}/copy/page.html"
        self.assertEqual(self.run_cli(page, "--screenshot", "../outside/s.png").returncode, 2)
        self.assertEqual(self.run_cli(page, "--goto", "https://example.com").returncode, 2)
        self.assertEqual(self.run_cli(page, "--load-state", "/etc/passwd").returncode, 2)
        self.assertEqual(self.run_cli(page, "--bogus", "x").returncode, 2)


@unittest.skipUnless(HAVE_PLAYWRIGHT, "Playwright not installed (NOT_RUN)")
class HeadlessRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "copy").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "copy/index.html").write_text(PAGE.format(outside=self.root / "outside"))
        self.env = {**os.environ, "HEAVY_LOCK_DIR": str(self.root / "lock"), "HEAVY_OWNER": "test"}
        self.env.pop("HEAVY_LOCK_HELD", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([PY, str(BROWSE), *args], cwd=self.root / "copy", capture_output=True, text=True,
                              env=self.env, timeout=180)

    def test_file_page_drives_and_blocks_outside_requests(self):
        out = self.run_cli(f"file://{self.root}/copy/index.html", "--fill", "#item=milk", "--hover", "#add",
                           "--click", "#add", "--eval", "document.querySelectorAll('li').length",
                           "--eval", "console.warn('careful'); 1", "--screenshot", "shot.png",
                           "--text", "page.txt", "--snapshot", "snap.yml", "--requests", "req.json")
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["evals"][0]["result"], 1)
        blocked = " ".join(result["blocked_requests"])
        self.assertIn("example.com", blocked)
        self.assertIn("secret.png", blocked)
        self.assertTrue((self.root / "copy/shot.png").stat().st_size > 1000)
        self.assertIn("milk", (self.root / "copy/page.txt").read_text())
        self.assertIn("Grocery list", (self.root / "copy/snap.yml").read_text())
        self.assertIn("careful", result["console_warnings"])
        reqs = json.loads((self.root / "copy/req.json").read_text())
        self.assertTrue(any(r["url"].endswith("index.html") for r in reqs), reqs)
        events = (self.root / "lock/events.log").read_text()
        self.assertIn("run-start", events, "the browser ran under the machine-wide heavy lock")

    def test_state_carries_between_calls_on_localhost(self):
        (self.root / "copy/state.html").write_text(
            "<script>if(location.hash=='#set')localStorage.setItem('k','v');"
            "document.title=localStorage.getItem('k')||'none';</script>")
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(self.root / "copy"), **k)
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            first = self.run_cli(f"http://127.0.0.1:{port}/state.html#set", "--save-state", "state.json")
            self.assertEqual(first.returncode, 0, first.stderr[-500:])
            second = self.run_cli(f"http://127.0.0.1:{port}/state.html", "--load-state", "state.json")
            self.assertEqual(json.loads(second.stdout.strip().splitlines()[-1])["title"], "v")
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
