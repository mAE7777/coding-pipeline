#!/usr/bin/env python3
"""The one table of source-file extensions, shared by record_check.py (does this folder hold code?), adopt.py
(inventory by language), and inventory.py (which files the candidate scan reads), so the three never disagree
about what counts as code.

Usage: languages.py <path>   prints the language of a file, or "not code"
"""
import sys
from pathlib import Path

CODE = {
    ".py": "python", ".pyw": "python", ".ipynb": "python",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".swift": "swift", ".m": "objective-c", ".mm": "objective-c",
    ".kt": "kotlin", ".kts": "kotlin", ".java": "java", ".scala": "scala", ".groovy": "groovy",
    ".rb": "ruby", ".cs": "csharp", ".fs": "fsharp", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".gd": "gdscript", ".gdshader": "gdscript", ".dart": "dart",
    ".vue": "vue", ".svelte": "svelte", ".astro": "astro", ".php": "php", ".lua": "lua", ".r": "r", ".R": "r",
    ".jl": "julia", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".hs": "haskell", ".ml": "ocaml",
    ".clj": "clojure", ".zig": "zig", ".nim": "nim", ".sol": "solidity", ".tf": "terraform",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".ps1": "powershell",
    ".sql": "sql", ".html": "html", ".htm": "html", ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
}
# Markup and styles hold product code but not the control flow the inventory's patterns look for.
NOT_SCANNED = {"html", "css", "sql", "terraform"}
DOC = {".md", ".mdx", ".txt", ".rst", ".adoc", ".org"}


def language(path):
    p = Path(path)
    return CODE.get(p.suffix) or CODE.get(p.suffix.lower())


if __name__ == "__main__":
    print(language(sys.argv[1]) if len(sys.argv) > 1 and language(sys.argv[1]) else "not code")
