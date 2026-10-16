"""Serve the page in public/ on localhost. Prints the address; an optional argument picks the port (default: a free one)."""
import functools
import http.server
import sys
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent / "public"


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PUBLIC))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving on http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
